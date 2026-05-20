#!/usr/bin/env python3

"""Compile reviewed taxonomy override candidates from override-prep artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_PREP_DIR = Path("data/taxonomy_review/current/override_prep")
DEFAULT_MIN_ROWS = 25
DEFAULT_OUTPUT_JSON = DEFAULT_PREP_DIR / "final_override_candidates.json"
DEFAULT_OUTPUT_CSV = DEFAULT_PREP_DIR / "final_override_candidates.csv"

CANDIDATE_COLUMNS = [
    "label",
    "rows",
    "family",
    "branch",
    "glottocode",
    "source",
    "decision",
    "reason",
]

def main() -> None:
    args = parse_args()
    candidates = {}
    add_markdown_candidates(candidates, args.prep_dir / "unmatched_research_ge25.md")
    add_markdown_candidates(candidates, args.prep_dir / "review_research_ge25.md")
    add_markdown_candidates(candidates, args.prep_dir / "false_positive_no_target_ge25.md")
    add_known_candidates(candidates, args.prep_dir / "likely_override_candidates.csv", min_rows=args.min_rows)
    add_known_candidates(candidates, args.prep_dir / "known_false_positive_candidates.csv", min_rows=args.min_rows)

    rows = sorted(candidates.values(), key=lambda row: (-row["rows"], row["label"].casefold()))
    args.output_json.write_text(
        json.dumps({row["label"]: override_payload(row) for row in rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"candidates": len(rows), "min_rows": args.min_rows, "output_json": str(args.output_json)}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prep-dir", type=Path, default=DEFAULT_PREP_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    return parser.parse_args()


def add_markdown_candidates(candidates: dict[str, dict[str, Any]], path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        rows, label, _candidate, decision, target, evidence = parts[:6]
        if decision not in {"ready_override", "accept_candidate", "branch_override"}:
            continue
        family, branch, glottocode = parse_target(target)
        add_candidate(
            candidates,
            label=label,
            rows=int(rows),
            family=family,
            branch=branch,
            glottocode=glottocode,
            source=path.name,
            decision=decision,
            reason=evidence,
        )


def add_known_candidates(candidates: dict[str, dict[str, Any]], path: Path, *, min_rows: int) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["rows"]) < min_rows:
                continue
            family = row.get("target_family") or ""
            branch = row.get("target_branch") or ""
            glottocode = row.get("target_glottocode") or ""
            if not family and not branch and not glottocode:
                continue
            reason = row.get("notes") or "Ledger-backed override candidate."
            add_candidate(
                candidates,
                label=row["label"],
                rows=int(row["rows"]),
                family=family,
                branch=branch,
                glottocode=glottocode,
                source=path.name,
                decision=row["recommended_action"],
                reason=reason,
            )


def parse_target(target: str) -> tuple[str, str, str]:
    glottocode = ""
    main = target
    if "; glottocode `" in target:
        main, raw_glottocode = target.split("; glottocode `", 1)
        glottocode = raw_glottocode.split("`", 1)[0]
    if " / " not in main:
        return main.strip(), main.strip(), glottocode
    family, branch = main.split(" / ", 1)
    return family.strip(), branch.strip(), glottocode


def add_candidate(
    candidates: dict[str, dict[str, Any]],
    *,
    label: str,
    rows: int,
    family: str,
    branch: str,
    glottocode: str,
    source: str,
    decision: str,
    reason: str,
) -> None:
    if not family:
        return
    candidates[label] = {
        "label": label,
        "rows": rows,
        "family": family,
        "branch": branch or family,
        "glottocode": glottocode,
        "source": source,
        "decision": decision,
        "reason": reason,
    }


def override_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "family": row["family"],
        "branch": row["branch"],
        "path": [row["family"], row["branch"]],
        "reason": row["reason"],
    }
    if row.get("glottocode"):
        payload["glottocode"] = row["glottocode"]
    return payload


if __name__ == "__main__":
    main()
