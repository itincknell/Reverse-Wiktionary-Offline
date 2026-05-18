"""
Read processed JSONL shards and attach stable source metadata.

The embedding stage uses this module to stream valid rows in deterministic shard
order. `SourceRow` carries the shard ID and row index used later for stable
Qdrant point IDs and recovery diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from src.common.jsonl import iter_jsonl
from src.common.paths import find_shards


@dataclass(frozen=True)
class SourceRow:
    """
    One normalized row plus stable source metadata.

    source_shard_id and source_row_index are used to construct deterministic
    point IDs and to support debugging/recovery.
    """

    row: dict[str, Any]
    embedding_text: str
    source_shard_id: int
    source_shard_path: Path
    source_row_index: int


@dataclass(frozen=True)
class EmbeddingBatch:
    """
    A batch of rows ready for embedding.

    The order of texts must match the order of source_rows.
    """

    source_rows: list[SourceRow]
    texts: list[str]


def shard_id_from_path(path: Path) -> int:
    """
    Extract integer shard ID from filenames like shard_00042.jsonl.
    """
    stem = path.stem

    if not stem.startswith("shard_"):
        raise ValueError(f"Unexpected shard filename: {path}")

    return int(stem.removeprefix("shard_"))


def iter_source_rows(shard_paths: list[Path]) -> Iterator[SourceRow]:
    """
    Stream valid embedding rows from shard files in deterministic order.

    Rows without a non-empty string embedding_text are skipped.
    """
    for shard_path in sorted(shard_paths):
        shard_id = shard_id_from_path(shard_path)

        for row_index, row in enumerate(iter_jsonl(shard_path), start=0):
            embedding_text = row.get("embedding_text")

            if not isinstance(embedding_text, str) or not embedding_text.strip():
                continue

            yield SourceRow(
                row=row,
                embedding_text=embedding_text,
                source_shard_id=shard_id,
                source_shard_path=shard_path,
                source_row_index=row_index,
            )


def iter_embedding_batches(
    processed_dir: Path,
    batch_size: int,
    *,
    max_shards: int | None = None,
    limit_rows: int | None = None,
) -> Iterator[EmbeddingBatch]:
    """
    Yield embedding batches from a processed run directory.

    Args:
        processed_dir: Directory containing shard_*.jsonl files.
        batch_size: Number of rows per embedding batch.
        max_shards: Optional maximum number of shards to read.
        limit_rows: Optional maximum number of valid rows to yield.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    shard_paths = find_shards(processed_dir)

    if max_shards is not None:
        shard_paths = shard_paths[:max_shards]

    batch: list[SourceRow] = []
    rows_seen = 0

    for source_row in iter_source_rows(shard_paths):
        if limit_rows is not None and rows_seen >= limit_rows:
            break

        batch.append(source_row)
        rows_seen += 1

        if len(batch) >= batch_size:
            yield EmbeddingBatch(
                source_rows=batch,
                texts=[item.embedding_text for item in batch],
            )
            batch = []

    if batch:
        yield EmbeddingBatch(
            source_rows=batch,
            texts=[item.embedding_text for item in batch],
        )
