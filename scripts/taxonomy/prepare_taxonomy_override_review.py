#!/usr/bin/env python3

"""Prepare override-review documentation from a taxonomy review run."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_RUN_ROOT = Path("data/taxonomy_review/current")
DEFAULT_CONFIG = "review080"
DEFAULT_LEDGER = Path("data/taxonomy_review/override_review_ledger.csv")
DEFAULT_OUTPUT_DIR = DEFAULT_RUN_ROOT / "override_prep"
HIGH_ROW_RESEARCH_THRESHOLD = 25

OUTPUT_COLUMNS = [
    "label",
    "rows",
    "stream",
    "match_method",
    "match_confidence",
    "candidate_name",
    "candidate_family",
    "candidate_branch",
    "current_family",
    "current_branch",
    "ledger_decision",
    "ledger_status",
    "target_family",
    "target_branch",
    "target_glottocode",
    "recommended_action",
    "reason",
    "notes",
]
EXPERIMENT_COLUMNS = [
    "config",
    "records",
    "matched",
    "review",
    "unmatched",
    "ledger_rows_seen",
    "known_false_positive_labels",
    "known_false_positive_rows",
    "known_false_negative_labels",
    "known_false_negative_rows",
    "review_caught_known_false_negative_labels",
    "review_caught_known_false_negative_rows",
    "unmatched_known_false_negative_labels",
    "unmatched_known_false_negative_rows",
    "known_false_positive_review_labels",
    "known_false_positive_review_rows",
    "high_row_nonselectable_labels",
    "high_row_nonselectable_rows",
    "high_row_review_labels",
    "high_row_review_rows",
    "high_row_unmatched_labels",
    "high_row_unmatched_rows",
    "matcher_resolved_ledger_labels",
    "estimated_manual_override_labels",
    "estimated_manual_override_rows",
    "cost_score",
]
DELTA_COLUMNS = [
    "config",
    "label",
    "rows",
    "preferred_stream",
    "preferred_match_method",
    "preferred_candidate_name",
    "experiment_stream",
    "experiment_match_method",
    "experiment_candidate_name",
    "experiment_family",
    "experiment_branch",
    "ledger_decision",
    "target_family",
    "target_branch",
]


def main() -> None:
    args = parse_args()
    config_dir = args.run_root / args.config
    records = read_jsonl(config_dir / "records.jsonl")
    ledger = read_ledger(args.ledger)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    annotated = [
        annotate_record(record=record, ledger_row=ledger.get(record["label"]))
        for record in records
    ]
    nonselectable = [
        row for row in annotated
        if row["stream"] in {"review", "unmatched"}
    ]
    priority_queue = [
        row for row in nonselectable
        if row["recommended_action"] in {
            "research_for_override",
            "likely_manual_override",
            "false_positive_guard",
        }
    ]
    likely_overrides = [
        row for row in annotated
        if row["recommended_action"] == "likely_manual_override"
    ]
    false_positive_guards = [
        row for row in annotated
        if row["recommended_action"] == "false_positive_guard"
    ]
    matcher_resolved = [
        row for row in annotated
        if row["recommended_action"] == "matcher_resolved"
    ]

    for rows in (
        annotated,
        nonselectable,
        priority_queue,
        likely_overrides,
        false_positive_guards,
        matcher_resolved,
    ):
        rows.sort(key=sort_key)

    write_csv(output_dir / "nonselectable_by_rows.csv", nonselectable)
    write_csv(output_dir / "priority_search_queue.csv", priority_queue)
    write_csv(output_dir / "likely_override_candidates.csv", likely_overrides)
    write_csv(output_dir / "known_false_positive_candidates.csv", false_positive_guards)
    write_csv(output_dir / "matcher_resolved_cases.csv", matcher_resolved)
    experiment_eval = evaluate_experiments(run_root=args.run_root, ledger=ledger)
    write_csv(
        output_dir / "experiment_error_estimates.csv",
        experiment_eval,
        columns=EXPERIMENT_COLUMNS,
    )
    write_csv(
        output_dir / "experiment_deltas_from_preferred.csv",
        experiment_deltas(run_root=args.run_root, preferred_config=args.config, ledger=ledger),
        columns=DELTA_COLUMNS,
    )

    summary = build_summary(
        run_root=args.run_root,
        config=args.config,
        config_settings=read_config_settings(args.run_root, args.config),
        records=annotated,
        ledger=ledger,
        nonselectable=nonselectable,
        priority_queue=priority_queue,
        likely_overrides=likely_overrides,
        false_positive_guards=false_positive_guards,
        matcher_resolved=matcher_resolved,
    )
    write_json(output_dir / "summary.json", summary)
    write_readme(
        output_dir / "README.md",
        summary=summary,
        nonselectable=nonselectable,
        priority_queue=priority_queue,
        likely_overrides=likely_overrides,
        false_positive_guards=false_positive_guards,
        matcher_resolved=matcher_resolved,
        experiment_eval=experiment_eval,
    )

    print(json.dumps({"output_dir": str(output_dir), "summary": summary}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_ledger(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["label"]: row
            for row in csv.DictReader(handle)
            if row.get("label")
        }


def read_config_settings(run_root: Path, config: str) -> dict[str, Any]:
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("configs", []):
        if item.get("name") == config:
            return item
    return {}


def annotate_record(
    *,
    record: dict[str, Any],
    ledger_row: dict[str, str] | None,
) -> dict[str, Any]:
    candidate = record.get("candidate") or {}
    ledger_decision = (ledger_row or {}).get("decision", "")
    ledger_status = (ledger_row or {}).get("status", "")
    target_family = (ledger_row or {}).get("target_family", "")
    target_branch = (ledger_row or {}).get("target_branch", "")
    target_glottocode = (ledger_row or {}).get("target_glottocode", "")
    notes = (ledger_row or {}).get("notes", "")
    action, reason = recommend_action(
        record=record,
        ledger_decision=ledger_decision,
        target_family=target_family,
        target_branch=target_branch,
        notes=notes,
    )

    return {
        "label": record["label"],
        "rows": int(record["rows"]),
        "stream": record["stream"],
        "match_method": record["match_method"],
        "match_confidence": record["match_confidence"],
        "candidate_name": record.get("candidate_name") or "",
        "candidate_family": candidate.get("family", ""),
        "candidate_branch": candidate.get("branch", ""),
        "current_family": record["family"],
        "current_branch": record["branch"],
        "ledger_decision": ledger_decision,
        "ledger_status": ledger_status,
        "target_family": target_family,
        "target_branch": target_branch,
        "target_glottocode": target_glottocode,
        "recommended_action": action,
        "reason": reason,
        "notes": notes,
    }


def recommend_action(
    *,
    record: dict[str, Any],
    ledger_decision: str,
    target_family: str,
    target_branch: str,
    notes: str,
) -> tuple[str, str]:
    if record["stream"] == "matched":
        if ledger_decision:
            return "matcher_resolved", "Current preferred run emits a selectable match."
        return "no_action", "Selectable match in current preferred run."

    if ledger_decision == "false_positive_review":
        return "false_positive_guard", "Ledger marks the current or prior candidate as a false positive."

    if ledger_decision in {"manual_override", "accept_glottolog", "possible_override"}:
        if target_family or target_branch:
            return "likely_manual_override", "Ledger already has a proposed target but current run is non-selectable."
        return "research_for_override", "Ledger says override-like case, but target is incomplete."

    if ledger_decision == "leave_unmatched":
        return "leave_unmatched_or_review", "Ledger says to leave this outside selectable taxonomy."

    if record["stream"] == "review":
        candidate = record.get("candidate") or {}
        if candidate.get("family") in {"Bookkeeping", "Unclassifiable", "Unattested"}:
            return "leave_unmatched_or_review", "Review candidate belongs to an excluded source family."
        if record["rows"] >= HIGH_ROW_RESEARCH_THRESHOLD:
            return "research_for_override", "High-row non-selectable review candidate needs final judgment."
        return "low_priority_review", "Low-row review candidate; inspect after high-row queue."

    if record["rows"] >= HIGH_ROW_RESEARCH_THRESHOLD:
        return "research_for_override", "High-row unmatched label; prioritize by rows before final overrides."

    if "false positive" in notes.lower():
        return "false_positive_guard", "Ledger note mentions false positive behavior."

    return "low_priority_review", "Low-row unmatched label; defer unless pattern suggests broader rule."


def sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return (-int(row["rows"]), row["label"].casefold())


def build_summary(
    *,
    run_root: Path,
    config: str,
    config_settings: dict[str, Any],
    records: list[dict[str, Any]],
    ledger: dict[str, dict[str, str]],
    nonselectable: list[dict[str, Any]],
    priority_queue: list[dict[str, Any]],
    likely_overrides: list[dict[str, Any]],
    false_positive_guards: list[dict[str, Any]],
    matcher_resolved: list[dict[str, Any]],
) -> dict[str, Any]:
    stream_counts = Counter(row["stream"] for row in records)
    action_counts = Counter(row["recommended_action"] for row in records)
    method_counts = Counter(row["match_method"] for row in records)
    ledger_seen = sum(1 for row in records if row["ledger_decision"])
    return {
        "run_root": str(run_root),
        "config": config,
        "auto_threshold": config_settings.get("auto_threshold"),
        "review_threshold": config_settings.get("review_threshold"),
        "records": len(records),
        "ledger_rows": len(ledger),
        "ledger_rows_seen_in_run": ledger_seen,
        "stream_counts": dict(sorted(stream_counts.items())),
        "match_method_counts": dict(method_counts.most_common()),
        "recommended_action_counts": dict(action_counts.most_common()),
        "nonselectable_count": len(nonselectable),
        "priority_queue_count": len(priority_queue),
        "likely_override_count": len(likely_overrides),
        "false_positive_guard_count": len(false_positive_guards),
        "matcher_resolved_count": len(matcher_resolved),
        "cost_function": [
            "Known false positives: ledger-labeled wrong matches that become selectable, or selectable matches that conflict with ledger targets.",
            "Known false negatives: ledger-labeled valid taxonomy targets left non-selectable.",
            "Proxy false negatives: high-row non-selectable labels without ledger truth labels.",
            "Review-caught misses are cheaper than unmatched misses because the candidate family/branch is available for review.",
            "False-positive review candidates are counted as review burden, but much cheaper than false selectable matches.",
            "Estimated manual override cost is the known false negatives plus high-row proxy false negatives, weighted by row count.",
            "Cost score weights false selectable matches highest, then unmatched known misses, review-caught known misses, and proxy misses.",
        ],
    }


def evaluate_experiments(
    *,
    run_root: Path,
    ledger: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    evaluations = []
    for records_path in sorted(run_root.glob("*/records.jsonl")):
        config = records_path.parent.name
        records = read_jsonl(records_path)
        evaluations.append(evaluate_experiment(config=config, records=records, ledger=ledger))
    evaluations.sort(key=lambda row: (float(row["cost_score"]), row["config"]))
    return evaluations


def experiment_deltas(
    *,
    run_root: Path,
    preferred_config: str,
    ledger: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    preferred_path = run_root / preferred_config / "records.jsonl"
    preferred = {
        record["label"]: record
        for record in read_jsonl(preferred_path)
    }
    deltas = []
    for records_path in sorted(run_root.glob("*/records.jsonl")):
        config = records_path.parent.name
        if config == preferred_config:
            continue
        for record in read_jsonl(records_path):
            base = preferred[record["label"]]
            if not record_changed(base, record):
                continue
            ledger_row = ledger.get(record["label"], {})
            deltas.append(
                {
                    "config": config,
                    "label": record["label"],
                    "rows": int(record["rows"]),
                    "preferred_stream": base["stream"],
                    "preferred_match_method": base["match_method"],
                    "preferred_candidate_name": base.get("candidate_name") or "",
                    "experiment_stream": record["stream"],
                    "experiment_match_method": record["match_method"],
                    "experiment_candidate_name": record.get("candidate_name") or "",
                    "experiment_family": record["family"],
                    "experiment_branch": record["branch"],
                    "ledger_decision": ledger_row.get("decision", ""),
                    "target_family": ledger_row.get("target_family", ""),
                    "target_branch": ledger_row.get("target_branch", ""),
                }
            )
    deltas.sort(key=lambda row: (row["config"], -row["rows"], row["label"].casefold()))
    return deltas


def record_changed(base: dict[str, Any], record: dict[str, Any]) -> bool:
    return (
        base["stream"] != record["stream"]
        or base["match_method"] != record["match_method"]
        or (base.get("candidate_name") or "") != (record.get("candidate_name") or "")
    )


def evaluate_experiment(
    *,
    config: str,
    records: list[dict[str, Any]],
    ledger: dict[str, dict[str, str]],
) -> dict[str, Any]:
    stream_counts = Counter(record["stream"] for record in records)
    known_fp_labels = 0
    known_fp_rows = 0
    known_fn_labels = 0
    known_fn_rows = 0
    review_caught_known_fn = 0
    review_caught_known_fn_rows = 0
    unmatched_known_fn = 0
    unmatched_known_fn_rows = 0
    known_fp_review_labels = 0
    known_fp_review_rows = 0
    high_row_nonselectable_labels = 0
    high_row_nonselectable_rows = 0
    high_row_review_labels = 0
    high_row_review_rows = 0
    high_row_unmatched_labels = 0
    high_row_unmatched_rows = 0
    matcher_resolved_ledger_labels = 0
    estimated_manual_override_labels = 0
    estimated_manual_override_rows = 0
    ledger_rows_seen = 0

    for record in records:
        ledger_row = ledger.get(record["label"])
        if ledger_row:
            ledger_rows_seen += 1
            if is_known_false_positive(record, ledger_row):
                known_fp_labels += 1
                known_fp_rows += int(record["rows"])
            if (
                ledger_row.get("decision") == "false_positive_review"
                and record["stream"] == "review"
            ):
                known_fp_review_labels += 1
                known_fp_review_rows += int(record["rows"])
            if is_known_false_negative(record, ledger_row):
                known_fn_labels += 1
                known_fn_rows += int(record["rows"])
                estimated_manual_override_labels += 1
                estimated_manual_override_rows += int(record["rows"])
                if record["stream"] == "review":
                    review_caught_known_fn += 1
                    review_caught_known_fn_rows += int(record["rows"])
                elif record["stream"] == "unmatched":
                    unmatched_known_fn += 1
                    unmatched_known_fn_rows += int(record["rows"])
            elif record["stream"] == "matched" and ledger_row.get("decision"):
                matcher_resolved_ledger_labels += 1

        if (
            record["stream"] in {"review", "unmatched"}
            and int(record["rows"]) >= HIGH_ROW_RESEARCH_THRESHOLD
            and not is_known_false_negative(record, ledger_row or {})
            and not is_known_non_taxonomy(record, ledger_row or {})
        ):
            high_row_nonselectable_labels += 1
            high_row_nonselectable_rows += int(record["rows"])
            estimated_manual_override_labels += 1
            estimated_manual_override_rows += int(record["rows"])
            if record["stream"] == "review":
                high_row_review_labels += 1
                high_row_review_rows += int(record["rows"])
            elif record["stream"] == "unmatched":
                high_row_unmatched_labels += 1
                high_row_unmatched_rows += int(record["rows"])

    cost_score = (
        known_fp_rows * 100
        + known_fp_review_rows * 3
        + review_caught_known_fn_rows * 4
        + unmatched_known_fn_rows * 12
        + high_row_review_rows
        + high_row_unmatched_rows * 3
    )
    return {
        "config": config,
        "records": len(records),
        "matched": stream_counts["matched"],
        "review": stream_counts["review"],
        "unmatched": stream_counts["unmatched"],
        "ledger_rows_seen": ledger_rows_seen,
        "known_false_positive_labels": known_fp_labels,
        "known_false_positive_rows": known_fp_rows,
        "known_false_negative_labels": known_fn_labels,
        "known_false_negative_rows": known_fn_rows,
        "review_caught_known_false_negative_labels": review_caught_known_fn,
        "review_caught_known_false_negative_rows": review_caught_known_fn_rows,
        "unmatched_known_false_negative_labels": unmatched_known_fn,
        "unmatched_known_false_negative_rows": unmatched_known_fn_rows,
        "known_false_positive_review_labels": known_fp_review_labels,
        "known_false_positive_review_rows": known_fp_review_rows,
        "high_row_nonselectable_labels": high_row_nonselectable_labels,
        "high_row_nonselectable_rows": high_row_nonselectable_rows,
        "high_row_review_labels": high_row_review_labels,
        "high_row_review_rows": high_row_review_rows,
        "high_row_unmatched_labels": high_row_unmatched_labels,
        "high_row_unmatched_rows": high_row_unmatched_rows,
        "matcher_resolved_ledger_labels": matcher_resolved_ledger_labels,
        "estimated_manual_override_labels": estimated_manual_override_labels,
        "estimated_manual_override_rows": estimated_manual_override_rows,
        "cost_score": cost_score,
    }


def is_known_false_positive(record: dict[str, Any], ledger_row: dict[str, str]) -> bool:
    if record["stream"] != "matched":
        return False
    target_family = ledger_row.get("target_family", "")
    target_branch = ledger_row.get("target_branch", "")
    if target_family and target_family != record["family"]:
        return True
    if target_branch and target_branch != record["branch"]:
        return True
    decision = ledger_row.get("decision", "")
    if decision == "false_positive_review" and not (target_family or target_branch):
        return True
    return False


def is_known_false_negative(record: dict[str, Any], ledger_row: dict[str, str]) -> bool:
    if record["stream"] == "matched":
        return False
    decision = ledger_row.get("decision", "")
    has_target = bool(ledger_row.get("target_family") or ledger_row.get("target_branch"))
    return decision in {"manual_override", "accept_glottolog", "possible_override"} and has_target


def is_known_non_taxonomy(record: dict[str, Any], ledger_row: dict[str, str]) -> bool:
    if ledger_row.get("decision") == "leave_unmatched":
        return True
    candidate = record.get("candidate") or {}
    return candidate.get("family") in {"Bookkeeping", "Unclassifiable", "Unattested"}


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_readme(
    path: Path,
    *,
    summary: dict[str, Any],
    nonselectable: list[dict[str, Any]],
    priority_queue: list[dict[str, Any]],
    likely_overrides: list[dict[str, Any]],
    false_positive_guards: list[dict[str, Any]],
    matcher_resolved: list[dict[str, Any]],
    experiment_eval: list[dict[str, Any]],
) -> None:
    lines = [
        "# Taxonomy Override Prep",
        "",
        f"Run root: `{summary['run_root']}`",
        f"Preferred config: `{summary['config']}`",
        "",
        "This packet uses the current preferred matcher settings for override prep:",
        "",
        f"- `auto_threshold={summary.get('auto_threshold')}`",
        f"- `review_threshold={summary.get('review_threshold')}`",
        "- `fuzzy_review` and `unmatched` remain non-selectable diagnostics",
        "- external/Wikipedia research is reserved for the final override pass",
        "",
        "## Cost Function",
        "",
        "- Known false positives are ledger-labeled wrong matches that become selectable, or selectable matches that conflict with ledger targets.",
        "- Known false negatives are ledger-labeled valid taxonomy targets left non-selectable.",
        "- Proxy false negatives are high-row non-selectable labels without ledger truth labels.",
        "- Review-caught misses are cheaper than unmatched misses because the candidate family/branch is available for review.",
        "- False-positive review candidates are counted as review burden, but much cheaper than false selectable matches.",
        "- Estimated manual override cost is the known false negatives plus high-row proxy false negatives, weighted by row count.",
        "- The cost score weights false selectable matches highest, then unmatched known misses, review-caught known misses, and proxy misses.",
        "",
        "## Outputs",
        "",
        "- `priority_search_queue.csv`: high-value ambiguous/non-selectable cases sorted by rows.",
        "- `likely_override_candidates.csv`: ledger-backed cases that still need a selectable final override.",
        "- `known_false_positive_candidates.csv`: wrong candidates or dangerous lookalikes to guard against.",
        "- `matcher_resolved_cases.csv`: ledger cases now resolved by matcher behavior.",
        "- `nonselectable_by_rows.csv`: all review/unmatched labels sorted by row count.",
        "- `summary.json`: machine-readable counts and settings.",
        "- `experiment_error_estimates.csv`: threshold comparison using estimated false positives and false negatives.",
        "- `experiment_deltas_from_preferred.csv`: exact label-level changes versus the chosen diagnostic setting.",
        "",
        "## Counts",
        "",
        f"- Records: {summary['records']}",
        f"- Streams: {summary['stream_counts']}",
        f"- Non-selectable labels: {summary['nonselectable_count']}",
        f"- Priority queue labels: {summary['priority_queue_count']}",
        f"- Likely override labels: {summary['likely_override_count']}",
        f"- False-positive guard labels: {summary['false_positive_guard_count']}",
        f"- Matcher-resolved ledger labels: {summary['matcher_resolved_count']}",
        "",
        "## Experiment Error Estimates",
        "",
        markdown_table_with_columns(
            experiment_eval,
            [
                "config",
                "matched",
                "review",
                "unmatched",
                "known_false_positive_rows",
                "known_false_positive_review_rows",
                "review_caught_known_false_negative_rows",
                "unmatched_known_false_negative_rows",
                "high_row_review_rows",
                "high_row_unmatched_rows",
                "estimated_manual_override_rows",
                "cost_score",
            ],
        ),
        "",
        (
            "Recommendation: use the lowest-cost setting as the diagnostic queue, "
            "not as automatic promotion. In the current sweep `auto096_review075` "
            "wins narrowly because review is non-selectable and catches a little "
            "more high-row work. Keep explicit overrides as the promotion mechanism, "
            "and re-run this packet after ledger updates."
        ),
        "",
        "## Top Priority Search Queue",
        "",
        markdown_table(priority_queue[:30]),
        "",
        "## Likely Overrides From Ledger",
        "",
        markdown_table(likely_overrides[:30]),
        "",
        "## False-Positive Guards",
        "",
        markdown_table(false_positive_guards[:30]),
        "",
        "## Matcher-Resolved Cases",
        "",
        markdown_table(matcher_resolved[:30]),
        "",
        "## Notes For The Final Override Pass",
        "",
        "- Re-run this prep after any branch-ranking change before editing final overrides.",
        "- The ledger may have `last_seen_*` fields from comparison thresholds; this packet uses the actual preferred run records.",
        "- Germanic variants now surface in review or exact/alias/token-sort paths; unresolved ones should become explicit display-policy overrides.",
        "- Contact-language policy: do not promote creoles or pidgins into a lexifier/source family unless the reviewed target explicitly requires it.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]]) -> str:
    columns = [
        "label",
        "rows",
        "stream",
        "match_method",
        "candidate_name",
        "candidate_family",
        "candidate_branch",
        "target_family",
        "target_branch",
        "recommended_action",
    ]
    if not rows:
        return "_None._"

    rendered = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(markdown_cell(row.get(column, "")) for column in columns) + " |")
    return "\n".join(rendered)


def markdown_table_with_columns(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_None._"
    rendered = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(markdown_cell(row.get(column, "")) for column in columns) + " |")
    return "\n".join(rendered)


def markdown_cell(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
