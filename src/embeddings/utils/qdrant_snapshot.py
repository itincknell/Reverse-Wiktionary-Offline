"""
Qdrant collection snapshot utilities.

Snapshots are portable backups created by Qdrant and are safer to move between
machines than live storage directories. Blob upload and VM lifecycle management
remain in the surrounding shell scripts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class QdrantSnapshotConfig:
    """
    Configuration for Qdrant snapshot operations.
    """

    qdrant_url: str
    collection_name: str
    output_dir: Path
    timeout_seconds: int = 600
    poll_interval_seconds: float = 2.0


def _base_url(qdrant_url: str) -> str:
    """
    Normalize the Qdrant base URL by removing a trailing slash.
    """
    return qdrant_url.rstrip("/")


def create_collection_snapshot(config: QdrantSnapshotConfig) -> dict[str, Any]:
    """
    Create a Qdrant snapshot for one collection.

    Returns:
        Snapshot metadata returned by Qdrant.
    """
    url = f"{_base_url(config.qdrant_url)}/collections/{config.collection_name}/snapshots"

    response = requests.post(url, timeout=config.timeout_seconds)
    response.raise_for_status()

    data = response.json()
    result = data.get("result")

    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected Qdrant snapshot response: {data}")

    return result


def snapshot_name(snapshot_metadata: dict[str, Any]) -> str:
    """
    Extract the snapshot name from Qdrant snapshot metadata.
    """
    name = snapshot_metadata.get("name")

    if not isinstance(name, str) or not name:
        raise RuntimeError(f"Snapshot metadata does not contain a valid name: {snapshot_metadata}")

    return name


def list_collection_snapshots(
    *,
    qdrant_url: str,
    collection_name: str,
    timeout_seconds: int = 60,
) -> list[dict[str, Any]]:
    """
    List snapshots available for a Qdrant collection.
    """
    url = f"{_base_url(qdrant_url)}/collections/{collection_name}/snapshots"

    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()

    data = response.json()
    result = data.get("result")

    if not isinstance(result, list):
        raise RuntimeError(f"Unexpected Qdrant snapshot list response: {data}")

    return result


def wait_for_snapshot(
    *,
    qdrant_url: str,
    collection_name: str,
    name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """
    Wait until a snapshot appears in the collection snapshot list.

    Snapshot creation is usually quick, but explicit polling makes the caller
    robust to slower collections.
    """
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        snapshots = list_collection_snapshots(
            qdrant_url=qdrant_url,
            collection_name=collection_name,
            timeout_seconds=timeout_seconds,
        )

        for snapshot in snapshots:
            if snapshot.get("name") == name:
                return snapshot

        time.sleep(poll_interval_seconds)

    raise TimeoutError(f"Timed out waiting for Qdrant snapshot: {name}")


def download_collection_snapshot(
    *,
    qdrant_url: str,
    collection_name: str,
    name: str,
    output_dir: Path,
    timeout_seconds: int = 600,
) -> Path:
    """
    Download a collection snapshot to output_dir.

    Returns:
        Local path to the downloaded snapshot file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    url = f"{_base_url(qdrant_url)}/collections/{collection_name}/snapshots/{name}"
    output_path = output_dir / name

    with requests.get(url, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()

        with output_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return output_path


def create_and_download_snapshot(config: QdrantSnapshotConfig) -> Path:
    """
    Create a collection snapshot, wait for it to become available, and download it.

    Returns:
        Local path to the downloaded snapshot file.
    """
    metadata = create_collection_snapshot(config)
    name = snapshot_name(metadata)

    wait_for_snapshot(
        qdrant_url=config.qdrant_url,
        collection_name=config.collection_name,
        name=name,
        timeout_seconds=config.timeout_seconds,
        poll_interval_seconds=config.poll_interval_seconds,
    )

    return download_collection_snapshot(
        qdrant_url=config.qdrant_url,
        collection_name=config.collection_name,
        name=name,
        output_dir=config.output_dir,
        timeout_seconds=config.timeout_seconds,
    )
