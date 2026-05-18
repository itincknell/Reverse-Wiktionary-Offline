"""
Embedding-run manifest helpers.

The embedding manifest records the run configuration, completed shards, and
aggregate progress needed for resume-safe indexing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.manifest import load_manifest, write_manifest
from src.common.run_id import utc_now_iso


EMBEDDING_MANIFEST_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class EmbeddingRunConfig:
    """
    Static configuration recorded for an embedding/index run.
    """

    run_id: str
    processed_run_id: str
    processed_dir: Path
    output_dir: Path
    model_name: str
    vector_size: int
    qdrant_url: str
    collection_name: str
    batch_size: int


def new_embedding_manifest(config: EmbeddingRunConfig) -> dict[str, Any]:
    """
    Create a new embedding run manifest.
    """
    return {
        "run_id": config.run_id,
        "stage": "embedding",
        "created_at_utc": utc_now_iso(),
        "schema_version": EMBEDDING_MANIFEST_SCHEMA_VERSION,
        "processed_run_id": config.processed_run_id,
        "processed_dir": str(config.processed_dir),
        "output_dir": str(config.output_dir),
        "model": {
            "name": config.model_name,
            "vector_size": config.vector_size,
        },
        "qdrant": {
            "url": config.qdrant_url,
            "collection_name": config.collection_name,
        },
        "config": {
            "batch_size": config.batch_size,
        },
        "metrics": {
            "rows_embedded": 0,
            "batches_completed": 0,
            "shards_completed": 0,
        },
        "shards": [],
    }


def load_or_create_manifest(
    manifest_path: Path,
    config: EmbeddingRunConfig,
    *,
    resume: bool,
) -> dict[str, Any]:
    """
    Load an existing manifest for resume, or create a new one.
    """
    if resume and manifest_path.exists():
        return load_manifest(manifest_path)

    return new_embedding_manifest(config)


def completed_shard_ids(manifest: dict[str, Any]) -> set[int]:
    """
    Return shard IDs marked complete.
    """
    completed: set[int] = set()

    for shard in manifest.get("shards", []):
        if not isinstance(shard, dict):
            continue

        if shard.get("status") != "complete":
            continue

        shard_id = shard.get("shard_id")
        if isinstance(shard_id, int):
            completed.add(shard_id)

    return completed


def mark_shard_complete(
    manifest: dict[str, Any],
    *,
    shard_id: int,
    shard_path: Path,
    rows: int,
    batches: int,
) -> None:
    """
    Mark a shard complete after all Qdrant upserts for that shard succeed.
    """
    manifest.setdefault("shards", []).append(
        {
            "shard_id": shard_id,
            "path": str(shard_path),
            "status": "complete",
            "rows": rows,
            "batches": batches,
            "completed_at_utc": utc_now_iso(),
        }
    )

    metrics = manifest.setdefault("metrics", {})
    metrics["rows_embedded"] = metrics.get("rows_embedded", 0) + rows
    metrics["batches_completed"] = metrics.get("batches_completed", 0) + batches
    metrics["shards_completed"] = metrics.get("shards_completed", 0) + 1


def save_embedding_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """
    Persist embedding manifest to disk.
    """
    write_manifest(path, manifest)
