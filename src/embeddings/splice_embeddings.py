#!/usr/bin/env python3

"""Upsert processed payload rows with previously saved embedding vectors."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from qdrant_client.models import Distance

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.jsonl import batched
from src.common.logging_utils import ProgressTimer
from src.common.manifest import base_manifest, load_manifest, write_manifest
from src.common.paths import find_shards
from src.common.run_id import utc_run_id
from src.embeddings.utils.qdrant_writer import QdrantWriter, QdrantWriterConfig
from src.embeddings.utils.shard_reader import (
    iter_source_rows,
    point_id_for_source_row,
    shard_id_from_path,
)


SCHEMA_VERSION = "v1"
DEFAULT_COLLECTION_NAME = "reverse_wiktionary_v5"
DEFAULT_POINT_ID_SHARD_SIZE = 50_000


def parse_distance(value: str) -> Distance:
    """
    Parse a CLI distance argument into a Qdrant Distance enum.
    """
    normalized = value.strip().lower()

    if normalized == "cosine":
        return Distance.COSINE

    if normalized == "dot":
        return Distance.DOT

    if normalized == "euclid":
        return Distance.EUCLID

    raise ValueError(f"Unsupported distance: {value}")


def vector_paths(vector_dir: Path, shard_id: int) -> tuple[Path, Path]:
    """
    Return the saved vector artifact and metadata paths for a shard.
    """
    stem = f"shard_{shard_id:05d}"
    return vector_dir / f"{stem}.npz", vector_dir / f"{stem}.json"


def load_vectors(vector_dir: Path, shard_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load saved vectors and deterministic source metadata for one shard.
    """
    artifact_path, metadata_path = vector_paths(vector_dir, shard_id)

    if not artifact_path.exists():
        raise FileNotFoundError(f"Vector artifact not found: {artifact_path}")

    if not metadata_path.exists():
        raise FileNotFoundError(f"Vector metadata not found: {metadata_path}")

    with np.load(artifact_path) as data:
        vectors = data["vectors"].astype(np.float32, copy=False)
        point_ids = data["point_ids"].astype(np.int64, copy=False)
        source_row_indices = data["source_row_indices"].astype(np.int32, copy=False)

    if vectors.ndim != 2:
        raise ValueError(f"Vectors must be 2D in {artifact_path}: shape={vectors.shape}")

    if len(vectors) != len(point_ids) or len(vectors) != len(source_row_indices):
        raise ValueError(f"Vector artifact arrays have mismatched lengths: {artifact_path}")

    return vectors, point_ids, source_row_indices


def validate_shard_alignment(
    *,
    shard_path: Path,
    source_rows: list,
    point_ids: np.ndarray,
    source_row_indices: np.ndarray,
    point_id_shard_size: int,
) -> None:
    """
    Confirm saved vectors line up exactly with the newly parsed rows.
    """
    if len(source_rows) != len(point_ids):
        raise ValueError(
            f"Row/vector count mismatch for {shard_path}: "
            f"rows={len(source_rows)} vectors={len(point_ids)}"
        )

    for index, source_row in enumerate(source_rows):
        expected_row_index = source_row.source_row_index
        actual_row_index = int(source_row_indices[index])

        if actual_row_index != expected_row_index:
            raise ValueError(
                f"source_row_index mismatch for {shard_path} at vector {index}: "
                f"expected={expected_row_index} actual={actual_row_index}"
            )

        expected_point_id = point_id_for_source_row(source_row, point_id_shard_size)
        actual_point_id = int(point_ids[index])

        if actual_point_id != expected_point_id:
            raise ValueError(
                f"point_id mismatch for {shard_path} at vector {index}: "
                f"expected={expected_point_id} actual={actual_point_id}"
            )


def splice_embeddings(
    *,
    processed_dir: Path,
    vector_dir: Path,
    output_root: Path,
    qdrant_url: str,
    collection_name: str,
    run_id: str | None,
    point_id_shard_size: int,
    upsert_batch_size: int,
    recreate_collection: bool,
    distance: Distance,
    on_disk_payload: bool,
    vectors_on_disk: bool,
    expected_vector_size: int | None,
    progress_every: int,
    max_shards: int | None,
) -> None:
    """
    Rebuild a Qdrant collection from new processed payloads and saved vectors.
    """
    if point_id_shard_size <= 0:
        raise ValueError("point_id_shard_size must be positive")

    if upsert_batch_size <= 0:
        raise ValueError("upsert_batch_size must be positive")

    processed_dir = processed_dir.resolve()
    vector_dir = vector_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = utc_run_id()

    run_dir = output_root / run_id
    manifest_path = run_dir / "manifest.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    processed_manifest_path = processed_dir / "manifest.json"
    processed_manifest = (
        load_manifest(processed_manifest_path) if processed_manifest_path.exists() else {}
    )

    shard_paths = find_shards(processed_dir)
    if max_shards is not None:
        shard_paths = shard_paths[:max_shards]

    first_vectors, _, _ = load_vectors(vector_dir, shard_id_from_path(shard_paths[0]))
    vector_size = int(first_vectors.shape[1])

    if expected_vector_size is not None and vector_size != expected_vector_size:
        raise ValueError(
            f"vector size mismatch: got {vector_size}, expected {expected_vector_size}"
        )

    writer = QdrantWriter(
        QdrantWriterConfig(
            url=qdrant_url,
            collection_name=collection_name,
            vector_size=vector_size,
            distance=distance,
            recreate_collection=recreate_collection,
            point_id_shard_size=point_id_shard_size,
            vectors_on_disk=vectors_on_disk,
            on_disk_payload=on_disk_payload,
        )
    )
    writer.ensure_collection()

    manifest = base_manifest(
        run_id=run_id,
        stage="embedding_splice",
        schema_version=SCHEMA_VERSION,
        inputs={
            "processed_dir": str(processed_dir),
            "processed_manifest": str(processed_manifest_path),
            "processed_manifest_found": bool(processed_manifest),
            "vector_dir": str(vector_dir),
        },
        config={
            "collection_name": collection_name,
            "qdrant_url": qdrant_url,
            "point_id_shard_size": point_id_shard_size,
            "upsert_batch_size": upsert_batch_size,
            "distance": distance.value,
            "recreate_collection": recreate_collection,
            "vectors_on_disk": vectors_on_disk,
            "on_disk_payload": on_disk_payload,
            "expected_vector_size": expected_vector_size,
            "vector_size": vector_size,
        },
    )
    manifest["shards"] = []
    write_manifest(manifest_path, manifest)

    timer = ProgressTimer(progress_every=progress_every)
    rows_total = 0
    batches_total = 0
    started = time.monotonic()

    for shard_path in shard_paths:
        shard_id = shard_id_from_path(shard_path)
        print(f"[splice-shard-start] shard_id={shard_id} path={shard_path}")

        source_rows = list(iter_source_rows([shard_path]))
        vectors, point_ids, source_row_indices = load_vectors(vector_dir, shard_id)

        if int(vectors.shape[1]) != vector_size:
            raise ValueError(
                f"vector size changed in shard {shard_id}: "
                f"got={vectors.shape[1]} expected={vector_size}"
            )

        validate_shard_alignment(
            shard_path=shard_path,
            source_rows=source_rows,
            point_ids=point_ids,
            source_row_indices=source_row_indices,
            point_id_shard_size=point_id_shard_size,
        )

        offset = 0
        for source_batch in batched(source_rows, upsert_batch_size):
            batch_vectors = vectors[offset : offset + len(source_batch)]
            writer.upsert_batch(source_batch, batch_vectors)
            offset += len(source_batch)
            rows_total += len(source_batch)
            batches_total += 1

            if timer.should_print(rows_total):
                timer.print_progress(records=rows_total, prefix="[splice-progress]")

        artifact_path, metadata_path = vector_paths(vector_dir, shard_id)
        manifest["shards"].append(
            {
                "shard_id": shard_id,
                "path": str(shard_path),
                "status": "complete",
                "rows": len(source_rows),
                "vector_artifact_path": str(artifact_path),
                "vector_metadata_path": str(metadata_path),
            }
        )
        manifest["metrics"] = {
            "rows_upserted": rows_total,
            "batches_completed": batches_total,
            "shards_completed": len(manifest["shards"]),
        }
        write_manifest(manifest_path, manifest)

        print(
            f"[splice-shard-complete] shard_id={shard_id} "
            f"rows={len(source_rows):,} total_rows={rows_total:,}"
        )

    elapsed = time.monotonic() - started
    manifest["metrics"] = {
        "rows_upserted": rows_total,
        "batches_completed": batches_total,
        "shards_completed": len(manifest["shards"]),
        "elapsed_seconds": elapsed,
        "rows_per_second": rows_total / elapsed if elapsed else 0.0,
    }
    write_manifest(manifest_path, manifest)

    print("=== Splice Complete ===")
    print(f"run id: {run_id}")
    print(f"processed dir: {processed_dir}")
    print(f"vector dir: {vector_dir}")
    print(f"manifest: {manifest_path}")
    print(f"collection: {collection_name}")
    print(f"rows upserted: {rows_total:,}")
    print(f"elapsed seconds: {elapsed:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Qdrant from processed rows and saved vector shards."
    )
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--vector-dir", required=True)
    parser.add_argument("--output-root", default="data/splices")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--point-id-shard-size",
        type=int,
        default=DEFAULT_POINT_ID_SHARD_SIZE,
    )
    parser.add_argument("--upsert-batch-size", type=int, default=256)
    parser.add_argument("--recreate-collection", action="store_true")
    parser.add_argument(
        "--distance",
        default="cosine",
        choices=["cosine", "dot", "euclid"],
    )
    parser.add_argument("--on-disk-payload", action="store_true")
    parser.add_argument("--vectors-on-disk", action="store_true")
    parser.add_argument("--expected-vector-size", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=100_000)
    parser.add_argument("--max-shards", type=int, default=None)
    args = parser.parse_args()

    splice_embeddings(
        processed_dir=Path(args.processed_dir),
        vector_dir=Path(args.vector_dir),
        output_root=Path(args.output_root),
        qdrant_url=args.qdrant_url,
        collection_name=args.collection_name,
        run_id=args.run_id,
        point_id_shard_size=args.point_id_shard_size,
        upsert_batch_size=args.upsert_batch_size,
        recreate_collection=args.recreate_collection,
        distance=parse_distance(args.distance),
        on_disk_payload=args.on_disk_payload,
        vectors_on_disk=args.vectors_on_disk,
        expected_vector_size=args.expected_vector_size,
        progress_every=args.progress_every,
        max_shards=args.max_shards,
    )


if __name__ == "__main__":
    main()
