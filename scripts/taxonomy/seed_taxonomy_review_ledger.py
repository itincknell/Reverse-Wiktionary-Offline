#!/usr/bin/env python3

"""Add labels to the taxonomy override review ledger."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.taxonomy.taxonomy_review_workflow import LEDGER_COLUMNS, read_ledger, write_ledger


def main() -> None:
    args = parse_args()
    rows = read_ledger(args.ledger)
    seed_rows = []
    for seed_csv in args.seed_csv:
        seed_rows.extend(read_seed_rows(seed_csv))

    for row in seed_rows:
        label = row["label"]
        existing = rows.get(label, {})
        merged = {column: existing.get(column, "") for column in LEDGER_COLUMNS}
        for column in LEDGER_COLUMNS:
            if row.get(column):
                merged[column] = row[column]
        merged["label"] = label
        rows[label] = merged

    write_ledger(args.ledger, rows)
    print(f"seeded {len(seed_rows)} labels into {args.ledger}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed_csv", type=Path, nargs="+")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/taxonomy_review/override_review_ledger.csv"),
    )
    return parser.parse_args()


def read_seed_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    main()
