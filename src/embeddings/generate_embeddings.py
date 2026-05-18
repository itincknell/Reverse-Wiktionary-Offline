#!/usr/bin/env python3

"""
Generate embeddings for normalized Wiktionary shards and upsert them to Qdrant.

This script is the orchestration layer for the embedding/indexing stage.

Responsibilities:
- Resolve processed input and embedding output paths
- Load the SentenceTransformer model
- Create or validate the Qdrant collection
- Stream normalized JSONL shards in deterministic order
- Encode `embedding_text` batches
- Send completed vector batches to a background Qdrant upsert worker
- Checkpoint completed shards in an embedding manifest
- Update the embeddings/latest symlink after a successful run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from queue import Full

from qdrant_client.models import Distance

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.jsonl import batched
from src.common.logging_utils import ProgressTimer
from src.common.manifest import load_manifest
from src.common.paths import find_shards, update_latest_symlink
from src.common.run_id import utc_run_id

from src.embeddings.utils.embedding_manifest import (
    EmbeddingRunConfig,
    completed_shard_ids,
    load_or_create_manifest,
    mark_shard_complete,
    save_embedding_manifest,
)
from src.embeddings.utils.embedding_model import EmbeddingModel, EmbeddingModelConfig
from src.embeddings.utils.qdrant_writer import (
    QdrantUpsertWorker,
    QdrantWriter,
    QdrantWriterConfig,
    UpsertBatch,
    UpsertQueue,
)
from src.embeddings.utils.shard_reader import iter_source_rows, shard_id_from_path


DEFAULT_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
DEFAULT_COLLECTION_NAME = "reverse_wiktionary_v1"
DEFAULT_BATCH_SIZE = 128
DEFAULT_QUEUE_SIZE = 4
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


def load_processed_run_id(processed_dir: Path) -> str:
    """
    Return the processed run ID associated with the input directory.

    If the input path is a `latest` symlink, the resolved target directory name
    is used. Otherwise, the input directory name is used directly.
    """
    if processed_dir.name == "latest":
        return processed_dir.resolve().name

    return processed_dir.name


def embedding_manifest_path(output_dir: Path) -> Path:
    """
    Return the conventional embedding manifest path for a run directory.
    """
    return output_dir / "manifest.json"


def process_shard(
    *,
    shard_path: Path,
    model: EmbeddingModel,
    upsert_queue,
    upsert_worker,
    encode_batch_size: int,
    progress_timer: ProgressTimer,
    total_state: dict[str, int],
    limit_rows_remaining: int | None,
) -> tuple[int, int]:
    """
    Encode one shard and enqueue completed vector batches for Qdrant upsert.

    The function does not mark the shard complete. Completion is recorded only
    after the caller drains the upsert queue and confirms that the writer worker
    has not failed.

    Returns:
        A tuple of (rows_processed, batches_processed).
    """
    shard_rows = 0
    shard_batches = 0

    source_rows_iter = iter_source_rows([shard_path])

    for source_batch in batched(source_rows_iter, encode_batch_size):
        if limit_rows_remaining is not None:
            remaining = limit_rows_remaining - total_state["rows"]
            if remaining <= 0:
                break

            source_batch = source_batch[:remaining]

        texts = [source_row.embedding_text for source_row in source_batch]
        vectors = model.encode(texts, batch_size=encode_batch_size)

        # Preserve bounded-queue backpressure while still giving the producer a
        # chance to notice if the background writer has failed.
        while True:
            upsert_worker.raise_if_failed()

            try:
                upsert_queue.put(
                    UpsertBatch(
                        source_rows=source_batch,
                        vectors=vectors,
                    ),
                    timeout=0.1,
                )
                break
            except Full:
                time.sleep(0.1)
                continue

        batch_size = len(source_batch)
        shard_rows += batch_size
        shard_batches += 1

        total_state["rows"] += batch_size
        total_state["batches"] += 1

        if progress_timer.should_print(total_state["rows"]):
            progress_timer.print_progress(
                records=total_state["rows"],
                prefix="[embedding-progress]",
            )

    return shard_rows, shard_batches


def generate_embeddings(
    *,
    processed_dir: Path,
    output_root: Path,
    qdrant_url: str,
    collection_name: str,
    model_name: str,
    device: str,
    encode_batch_size: int,
    queue_size: int,
    point_id_shard_size: int,
    recreate_collection: bool,
    resume: bool,
    run_id: str | None,
    max_shards: int | None,
    limit_rows: int | None,
    progress_every: int,
    distance: Distance,
) -> None:
    """
    Run the embedding/indexing pipeline.

    The main thread owns shard reading and model inference. A background worker
    owns Qdrant upserts so database writes can overlap with later embedding
    batches.
    """
    if encode_batch_size <= 0:
        raise ValueError("encode_batch_size must be positive")

    if queue_size <= 0:
        raise ValueError("queue_size must be positive")

    if point_id_shard_size <= 0:
        raise ValueError("point_id_shard_size must be positive")

    processed_dir = processed_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = utc_run_id()

    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = embedding_manifest_path(output_dir)

    processed_run_id = load_processed_run_id(processed_dir)
    processed_manifest_path = processed_dir / "manifest.json"

    processed_manifest = {}
    if processed_manifest_path.exists():
        processed_manifest = load_manifest(processed_manifest_path)

    shard_paths = find_shards(processed_dir)

    if max_shards is not None:
        shard_paths = shard_paths[:max_shards]

    model = EmbeddingModel(
        EmbeddingModelConfig(
            model_name=model_name,
            device=device,
            normalize_embeddings=True,
        )
    )

    vector_size = model.embedding_dimension

    writer = QdrantWriter(
        QdrantWriterConfig(
            url=qdrant_url,
            collection_name=collection_name,
            vector_size=vector_size,
            distance=distance,
            recreate_collection=recreate_collection,
            point_id_shard_size=point_id_shard_size,
        )
    )

    writer.ensure_collection()

    config = EmbeddingRunConfig(
        run_id=run_id,
        processed_run_id=processed_run_id,
        processed_dir=processed_dir,
        output_dir=output_dir,
        model_name=model_name,
        vector_size=vector_size,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
        batch_size=encode_batch_size,
    )

    manifest = load_or_create_manifest(
        manifest_path,
        config,
        resume=resume,
    )

    manifest.setdefault("inputs", {})
    manifest["inputs"]["processed_manifest"] = str(processed_manifest_path)
    manifest["inputs"]["processed_manifest_found"] = bool(processed_manifest)

    manifest.setdefault("config", {})
    manifest["config"]["queue_size"] = queue_size
    manifest["config"]["point_id_shard_size"] = point_id_shard_size
    manifest["config"]["distance"] = distance.value
    manifest["config"]["recreate_collection"] = recreate_collection

    completed = completed_shard_ids(manifest)

    upsert_queue = UpsertQueue(maxsize=queue_size)
    upsert_worker = QdrantUpsertWorker(writer, upsert_queue)
    upsert_worker.start()

    timer = ProgressTimer(progress_every=progress_every)

    metrics = manifest.get("metrics", {})
    total_state = {
        "rows": int(metrics.get("rows_embedded", 0)),
        "batches": int(metrics.get("batches_completed", 0)),
    }

    try:
        for shard_path in shard_paths:
            shard_id = shard_id_from_path(shard_path)

            if resume and shard_id in completed:
                print(f"[skip] shard {shard_id} already complete: {shard_path}")
                continue

            if limit_rows is not None and total_state["rows"] >= limit_rows:
                break

            print(f"[shard-start] shard_id={shard_id} path={shard_path}")

            shard_rows, shard_batches = process_shard(
                shard_path=shard_path,
                model=model,
                upsert_queue=upsert_queue,
                upsert_worker=upsert_worker,
                encode_batch_size=encode_batch_size,
                progress_timer=timer,
                total_state=total_state,
                limit_rows_remaining=limit_rows,
            )

            upsert_queue.wait_until_done_or_failed(upsert_worker)

            if shard_rows == 0:
                print(f"[shard-empty] shard_id={shard_id} path={shard_path}")
                continue

            mark_shard_complete(
                manifest,
                shard_id=shard_id,
                shard_path=shard_path,
                rows=shard_rows,
                batches=shard_batches,
            )
            save_embedding_manifest(manifest_path, manifest)

            print(
                f"[shard-complete] shard_id={shard_id} "
                f"rows={shard_rows:,} batches={shard_batches:,} "
                f"total_rows={total_state['rows']:,}"
            )

    finally:
        # Drain any in-flight upserts before stopping the worker so successful
        # batches are not abandoned, while still surfacing worker failures.
        upsert_queue.wait_until_done_or_failed(upsert_worker)
        upsert_worker.stop()
        upsert_worker.raise_if_failed()

    update_latest_symlink(output_root, run_id)

    elapsed = timer.elapsed()

    print("=== Embedding Run Complete ===")
    print(f"run id: {run_id}")
    print(f"processed run id: {processed_run_id}")
    print(f"processed dir: {processed_dir}")
    print(f"output dir: {output_dir}")
    print(f"manifest: {manifest_path}")
    print(f"qdrant url: {qdrant_url}")
    print(f"collection: {collection_name}")
    print(f"model: {model_name}")
    print(f"vector size: {vector_size}")
    print(f"rows embedded: {total_state['rows']:,}")
    print(f"batches completed: {total_state['batches']:,}")
    print(f"elapsed seconds: {elapsed:.2f}")

    if elapsed > 0:
        print(f"rows/sec: {total_state['rows'] / elapsed:.1f}")
    else:
        print("rows/sec: 0.0")


def main() -> None:
    """
    CLI entry point.
    """
    parser = argparse.ArgumentParser(
        description="Generate embeddings from normalized Wiktionary shards and upsert to Qdrant."
    )

    parser.add_argument(
        "--processed-dir",
        default="data/processed/latest",
        help="Directory containing processed shard_*.jsonl files.",
    )

    parser.add_argument(
        "--output-root",
        default="data/embeddings",
        help="Root directory for timestamped embedding run outputs.",
    )

    parser.add_argument(
        "--qdrant-url",
        default=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant URL. Defaults to QDRANT_URL or http://localhost:6333.",
    )

    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help="Qdrant collection name.",
    )

    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="SentenceTransformer model name.",
    )

    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="Embedding device.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="SentenceTransformer encode batch size.",
    )

    parser.add_argument(
        "--queue-size",
        type=int,
        default=DEFAULT_QUEUE_SIZE,
        help="Maximum number of completed embedding batches waiting for Qdrant upsert.",
    )

    parser.add_argument(
        "--point-id-shard-size",
        type=int,
        default=DEFAULT_POINT_ID_SHARD_SIZE,
        help="Point ID stride. Must match preprocessing shard size.",
    )

    parser.add_argument(
        "--distance",
        default="cosine",
        choices=["cosine", "dot", "euclid"],
        help="Qdrant vector distance metric.",
    )

    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Delete and recreate the Qdrant collection before writing.",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing embedding manifest in the selected run directory.",
    )

    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional embedding run ID. Defaults to a UTC timestamp.",
    )

    parser.add_argument(
        "--max-shards",
        type=int,
        default=None,
        help="Optional maximum number of shards to process.",
    )

    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Optional maximum number of rows to embed.",
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=100_000,
        help="Print progress every N embedded rows.",
    )

    args = parser.parse_args()

    generate_embeddings(
        processed_dir=Path(args.processed_dir),
        output_root=Path(args.output_root),
        qdrant_url=args.qdrant_url,
        collection_name=args.collection_name,
        model_name=args.model_name,
        device=args.device,
        encode_batch_size=args.batch_size,
        queue_size=args.queue_size,
        point_id_shard_size=args.point_id_shard_size,
        recreate_collection=args.recreate_collection,
        resume=args.resume,
        run_id=args.run_id,
        max_shards=args.max_shards,
        limit_rows=args.limit_rows,
        progress_every=args.progress_every,
        distance=parse_distance(args.distance),
    )


if __name__ == "__main__":
    main()
