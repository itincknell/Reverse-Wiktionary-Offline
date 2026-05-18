"""
Backfill serving metadata from processed JSONL shards.

This reads the processed row contract, not the raw Wiktionary dump. It is used
for older processed runs that were created before `serving_metadata.json` became
part of the preprocessing output.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.common.run_id import utc_now_iso


def main() -> None:
    args = parse_args()
    metadata = build_serving_metadata(args.processed_dir)
    args.output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"languages: {metadata['language_count']}")
    print(f"output: {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def build_serving_metadata(processed_dir: Path) -> dict[str, Any]:
    manifest_path = processed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lang_counts: Counter[str] = Counter()
    pos_counts: Counter[str] = Counter()

    for shard_path in sorted(processed_dir.glob("shard_*.jsonl")):
        with shard_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                lang = str(row.get("lang") or "").strip()
                pos = str(row.get("pos") or "").strip()
                if lang:
                    lang_counts[lang] += 1
                if pos:
                    pos_counts[pos] += 1

    return {
        "schema_version": "v1",
        "processed_run_id": manifest.get("run_id"),
        "created_at_utc": utc_now_iso(),
        "source": "processed_shard_backfill",
        "language_count": len(lang_counts),
        "languages": [
            {"lang": lang, "rows": rows}
            for lang, rows in sorted(
                lang_counts.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ],
        "pos": [
            {"pos": pos, "rows": rows}
            for pos, rows in sorted(
                pos_counts.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ],
    }


if __name__ == "__main__":
    main()
