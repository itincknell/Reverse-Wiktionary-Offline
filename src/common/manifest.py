"""
Manifest helpers.

Manifests make pipeline runs inspectable and resumable. Each stage should write
a manifest that records inputs, outputs, schema/model settings, counts, and
completed shard status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .run_id import utc_now_iso


def load_manifest(path: Path) -> dict[str, Any]:
    """
    Load a JSON manifest from disk.
    """
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    if not isinstance(obj, dict):
        raise ValueError(f"Manifest is not a JSON object: {path}")

    return obj


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """
    Write a manifest as pretty JSON.

    ensure_ascii=False preserves multilingual metadata.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def base_manifest(
    *,
    run_id: str,
    stage: str,
    schema_version: str,
    inputs: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Construct a standard manifest skeleton for a pipeline stage.
    """
    return {
        "run_id": run_id,
        "stage": stage,
        "created_at_utc": utc_now_iso(),
        "schema_version": schema_version,
        "inputs": inputs or {},
        "config": config or {},
        "metrics": {},
        "artifacts": {},
    }


def completed_shard_ids(manifest: dict[str, Any]) -> set[int]:
    """
    Return shard IDs marked complete in a manifest.

    Supports manifests with:
        {"shards": [{"shard_id": 0, "status": "complete"}]}
    """
    shards = manifest.get("shards", [])

    if not isinstance(shards, list):
        return set()

    completed: set[int] = set()

    for shard in shards:
        if not isinstance(shard, dict):
            continue

        if shard.get("status") != "complete":
            continue

        shard_id = shard.get("shard_id")

        if isinstance(shard_id, int):
            completed.add(shard_id)

    return completed


def append_completed_shard(
    manifest: dict[str, Any],
    *,
    shard_id: int,
    path: str,
    rows: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Append one completed shard entry to a manifest in memory.
    """
    shard_entry: dict[str, Any] = {
        "shard_id": shard_id,
        "path": path,
        "status": "complete",
        "rows": rows,
    }

    if extra:
        shard_entry.update(extra)

    manifest.setdefault("shards", []).append(shard_entry)


def update_metrics(manifest: dict[str, Any], **metrics: Any) -> None:
    """
    Merge metric values into manifest["metrics"].
    """
    manifest.setdefault("metrics", {}).update(metrics)


def update_artifacts(manifest: dict[str, Any], **artifacts: Any) -> None:
    """
    Merge artifact paths into manifest["artifacts"].
    """
    manifest.setdefault("artifacts", {}).update(artifacts)