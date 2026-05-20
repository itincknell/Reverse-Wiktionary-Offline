#!/usr/bin/env python3

"""Run sharded taxonomy matching experiments and maintain a review ledger."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.taxonomy.build_language_taxonomy import (
    apply_override,
    apply_override_fields,
    display_branch,
    display_family,
    enrich_match,
    serving_metadata_languages,
)
from src.taxonomy.glottolog_lookup import GlottologLookup, MatchResult, normalize_label


DEFAULT_CONFIGS = [
    "review075:auto=0.96,review=0.75",
    "review080:auto=0.96,review=0.80",
    "review088:auto=0.96,review=0.88",
]
LEDGER_COLUMNS = [
    "label",
    "status",
    "decision",
    "target_family",
    "target_branch",
    "target_glottocode",
    "expected_match_method",
    "expected_candidate_name",
    "last_seen_config",
    "last_seen_stream",
    "last_seen_match_method",
    "last_seen_candidate_name",
    "last_seen_confidence",
    "last_seen_family",
    "last_seen_branch",
    "rows",
    "notes",
]


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    auto_threshold: float
    review_threshold: float


def main() -> None:
    args = parse_args()
    output_root = args.output_root / args.run_id
    output_root.mkdir(parents=True, exist_ok=True)

    serving_metadata = load_json(args.serving_metadata)
    languages = serving_metadata_languages(serving_metadata)
    overrides = load_json(args.overrides) if args.overrides.exists() else {}
    lookup = GlottologLookup.from_csv(args.glottolog_csv)
    configs = [parse_config(value) for value in (args.config or DEFAULT_CONFIGS)]

    write_json(
        output_root / "run_manifest.json",
        {
            "run_id": args.run_id,
            "serving_metadata": str(args.serving_metadata),
            "glottolog_csv": str(args.glottolog_csv),
            "overrides": str(args.overrides),
            "configs": [config.__dict__ for config in configs],
            "shard_size": args.shard_size,
        },
    )

    ledger_rows = read_ledger(args.ledger)
    summary = []
    for config in configs:
        config_dir = output_root / config.name
        config_summary = run_experiment(
            config=config,
            languages=languages,
            lookup=lookup,
            overrides=overrides,
            output_dir=config_dir,
            shard_size=args.shard_size,
        )
        summary.append(config_summary)
        update_ledger_from_experiment(
            ledger_rows=ledger_rows,
            records_path=config_dir / "records.jsonl",
            config_name=config.name,
        )

    latest_ledger_rows = read_ledger(args.ledger)
    merged_ledger_rows = merge_ledger_rows(latest_ledger_rows, ledger_rows)
    write_ledger(args.ledger, merged_ledger_rows)
    write_json(output_root / "summary.json", {"configs": summary})
    print(json.dumps({"output_root": str(output_root), "summary": summary}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serving-metadata",
        type=Path,
        default=Path("data/processed/20260518T191021Z/serving_metadata.json"),
    )
    parser.add_argument(
        "--glottolog-csv",
        type=Path,
        default=Path("data/reference/glottolog/5.3/glottolog_languoid.csv"),
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path("src/taxonomy/language_taxonomy_overrides.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/taxonomy_review"),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/taxonomy_review/override_review_ledger.csv"),
    )
    parser.add_argument("--run-id", default="current")
    parser.add_argument("--config", action="append")
    parser.add_argument("--shard-size", type=int, default=100)
    return parser.parse_args()


def parse_config(value: str) -> ExperimentConfig:
    name, raw_settings = value.split(":", 1)
    settings = {}
    for item in raw_settings.split(","):
        key, raw_value = item.split("=", 1)
        settings[key.strip()] = float(raw_value)
    return ExperimentConfig(
        name=name,
        auto_threshold=settings.get("auto", 0.96),
        review_threshold=settings.get("review", 0.80),
    )


def run_experiment(
    *,
    config: ExperimentConfig,
    languages: list[dict[str, Any]],
    lookup: GlottologLookup,
    overrides: dict[str, Any],
    output_dir: Path,
    shard_size: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    streams: dict[str, list[dict[str, Any]]] = {
        "matched": [],
        "review": [],
        "unmatched": [],
    }

    records_path = output_dir / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for language in languages:
            record = match_language(
                language=language,
                lookup=lookup,
                overrides=overrides,
                auto_threshold=config.auto_threshold,
                review_threshold=config.review_threshold,
            )
            streams[record["stream"]].append(record)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    for stream_name, records in streams.items():
        stream_dir = output_dir / stream_name
        stream_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(stream_dir / "all.jsonl", records)
        write_shards(records=records, output_dir=stream_dir / "shards", shard_size=shard_size)

    summary = {
        "config": config.name,
        "auto_threshold": config.auto_threshold,
        "review_threshold": config.review_threshold,
        "matched": len(streams["matched"]),
        "review": len(streams["review"]),
        "unmatched": len(streams["unmatched"]),
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def match_language(
    *,
    language: dict[str, Any],
    lookup: GlottologLookup,
    overrides: dict[str, Any],
    auto_threshold: float,
    review_threshold: float,
) -> dict[str, Any]:
    label = language["lang"]
    rows = int(language["rows"])
    override = overrides.get(label)
    match: MatchResult | None

    if override and override.get("glottocode"):
        match = lookup.match_glottocode(label, override["glottocode"])
        enriched = enrich_match(label=label, rows=rows, match=match)
        enriched = apply_override_fields(enriched, override)
    elif override:
        match = None
        enriched = apply_override(label=label, rows=rows, override=override)
    else:
        match = lookup.match(
            label,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
        )
        enriched = enrich_match(label=label, rows=rows, match=match)

    if enriched["match_method"] in {"unmatched"}:
        stream = "unmatched"
    elif enriched["match_method"] in {"fuzzy_review"}:
        stream = "review"
    else:
        stream = "matched"

    candidate = summarize_candidate(match) if match and match.languoid else None
    return {
        "label": label,
        "rows": rows,
        "stream": stream,
        "match_method": enriched["match_method"],
        "match_confidence": enriched["match_confidence"],
        "family": enriched["family"],
        "branch": enriched["branch"],
        "selectable": enriched["selectable"],
        "candidate_name": enriched.get("candidate_name"),
        "candidate": candidate,
        "override_present": bool(override),
        "normalized_label": normalize_label(label),
        "risk_flags": risk_flags(label=label, stream=stream, enriched=enriched, candidate=candidate),
    }


def summarize_candidate(match: MatchResult) -> dict[str, Any]:
    assert match.languoid is not None
    family = display_family(match.languoid)
    return {
        "name": match.languoid.name,
        "glottocode": match.languoid.glottocode,
        "level": match.languoid.level,
        "family": family,
        "branch": display_branch(family, match.languoid.classification_names),
        "path": match.languoid.classification_names,
    }


def risk_flags(
    *,
    label: str,
    stream: str,
    enriched: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> list[str]:
    flags = []
    if stream == "review":
        flags.append("not_selectable")
    if len(label) <= 5 and enriched["match_method"] == "fuzzy_review":
        flags.append("short_label")
    if label.startswith(("Proto-", "Old ", "Middle ", "Early ", "Classical ", "Ancient ")):
        flags.append("historical_or_proto")
    if candidate and candidate["family"] in {"Bookkeeping", "Unclassifiable"}:
        flags.append("candidate_excluded_family")
    if (
        candidate
        and enriched["match_method"] == "fuzzy_review"
        and candidate["family"] != enriched["family"]
        and enriched["family"] != "Unmatched"
    ):
        flags.append("candidate_family_differs")
    return flags


def write_shards(*, records: list[dict[str, Any]], output_dir: Path, shard_size: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for index in range(0, len(records), shard_size):
        shard_id = index // shard_size
        write_jsonl(output_dir / f"shard_{shard_id:04d}.jsonl", records[index:index + shard_size])


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_ledger(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["label"]: row
            for row in csv.DictReader(handle)
            if row.get("label")
        }


def update_ledger_from_experiment(
    *,
    ledger_rows: dict[str, dict[str, str]],
    records_path: Path,
    config_name: str,
) -> None:
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            row = ledger_rows.get(record["label"])
            if row is None:
                continue
            row["last_seen_config"] = config_name
            row["last_seen_stream"] = record["stream"]
            row["last_seen_match_method"] = record["match_method"]
            row["last_seen_candidate_name"] = record.get("candidate_name") or ""
            row["last_seen_confidence"] = str(record["match_confidence"])
            row["last_seen_family"] = record["family"]
            row["last_seen_branch"] = record["branch"]
            row["rows"] = str(record["rows"])
            expected = row.get("expected_match_method")
            if expected and expected == record["match_method"]:
                row["status"] = "still_required"
            elif expected:
                row["status"] = "recheck"


def merge_ledger_rows(
    base_rows: dict[str, dict[str, str]],
    update_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = {
        label: {column: row.get(column, "") for column in LEDGER_COLUMNS}
        for label, row in base_rows.items()
    }
    run_update_columns = {
        "status",
        "last_seen_config",
        "last_seen_stream",
        "last_seen_match_method",
        "last_seen_candidate_name",
        "last_seen_confidence",
        "last_seen_family",
        "last_seen_branch",
        "rows",
    }

    for label, update_row in update_rows.items():
        existing = merged.get(label)
        if existing is None:
            merged[label] = {column: update_row.get(column, "") for column in LEDGER_COLUMNS}
            continue
        for column in run_update_columns:
            if update_row.get(column):
                existing[column] = update_row[column]
    return merged


def write_ledger(path: Path, ledger_rows: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(ledger_rows.values())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
