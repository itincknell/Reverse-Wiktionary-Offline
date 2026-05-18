"""
JSONL streaming helpers.

These helpers keep large-file handling consistent across preprocessing and
embedding generation. They avoid loading full datasets into memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


def iter_jsonl(path: Path, *, skip_bad_json: bool = True) -> Iterator[dict[str, Any]]:
    """
    Stream dictionary records from a JSONL file.

    Args:
        path: JSONL file path.
        skip_bad_json: If True, malformed lines are skipped. If False, parsing
            errors are raised.

    Yields:
        Dictionary records. Non-dictionary JSON values are skipped.
    """
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                if skip_bad_json:
                    continue
                raise ValueError(f"Invalid JSON in {path} at line {line_number}")

            if isinstance(obj, dict):
                yield obj


def write_jsonl_row(file: TextIO, row: dict[str, Any]) -> int:
    """
    Write one JSONL row and return the number of UTF-8 bytes written.

    ensure_ascii=False preserves Unicode text for multilingual Wiktionary data.
    """
    line = json.dumps(row, ensure_ascii=False) + "\n"
    file.write(line)
    return len(line.encode("utf-8"))


def jsonl_row_bytes(row: dict[str, Any]) -> int:
    """
    Return the exact UTF-8 byte size of a row if written as JSONL.
    """
    return len((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """
    Write rows to a JSONL file and return the number of rows written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            write_jsonl_row(f, row)
            count += 1

    return count


def batched(iterable: Iterable[Any], batch_size: int) -> Iterator[list[Any]]:
    """
    Yield lists of up to batch_size items from an iterable.

    This is used by embedding generation to avoid loading entire shards into
    memory.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    batch: list[Any] = []

    for item in iterable:
        batch.append(item)

        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch