"""
Qdrant collection management and deterministic batch upserts.

The writer creates or validates the target collection, converts normalized rows
into Qdrant payloads, and assigns point IDs from source shard metadata. The
optional background worker lets database writes overlap with later embedding
batches while still surfacing failures to the producer thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from src.embeddings.utils.shard_reader import SourceRow


DEFAULT_POINT_ID_SHARD_SIZE = 50_000


@dataclass(frozen=True)
class QdrantWriterConfig:
    """
    Configuration for Qdrant writes.

    point_id_shard_size controls the deterministic point ID layout:

        point_id = source_shard_id * point_id_shard_size + source_row_index

    It must match the preprocessing shard size to avoid point ID collisions.
    """

    url: str
    collection_name: str
    vector_size: int
    distance: Distance = Distance.COSINE
    recreate_collection: bool = False
    point_id_shard_size: int = DEFAULT_POINT_ID_SHARD_SIZE


@dataclass(frozen=True)
class UpsertBatch:
    """
    A completed embedding batch ready to be written to Qdrant.

    source_rows and vectors must have matching order and length.
    """

    source_rows: list[SourceRow]
    vectors: np.ndarray


class UpsertQueue(Queue[UpsertBatch | None]):
    """
    Queue wrapper with failure-aware drain behavior for the upsert worker.

    The standard Queue.join() blocks until every enqueued item has called
    task_done(), but it cannot wake early if the only consumer exits after a
    Qdrant failure. This wrapper keeps the normal backpressure semantics while
    periodically surfacing worker exceptions to the producer thread.
    """

    def wait_until_done_or_failed(
        self,
        worker: QdrantUpsertWorker,
        poll_seconds: float = 0.1,
    ) -> None:
        """
        Wait for all queued upserts to finish, or raise if the worker failed.

        This intentionally replaces raw Queue.join() at shard boundaries. The
        condition wait uses the same internal notification path as Queue.join(),
        but with a timeout so the producer can check whether the background
        writer has captured an exception.
        """
        while True:
            worker.raise_if_failed()
            with self.all_tasks_done:
                if self.unfinished_tasks == 0:
                    break

                self.all_tasks_done.wait(timeout=poll_seconds)

        worker.raise_if_failed()


class QdrantWriter:
    """
    Write embedded rows to Qdrant.

    Contract:
    - collection exists before upserts
    - point IDs are deterministic from source shard and row index
    - payload contains presentation/filtering metadata, not embedding text
    """

    def __init__(self, config: QdrantWriterConfig) -> None:
        if config.vector_size <= 0:
            raise ValueError("vector_size must be positive")

        if config.point_id_shard_size <= 0:
            raise ValueError("point_id_shard_size must be positive")

        self.config = config
        self.client = QdrantClient(url=config.url)

    def ensure_collection(self) -> None:
        """
        Create or validate the target collection.

        If recreate_collection is true, the existing collection is replaced.
        Otherwise, the collection is created only if missing.
        """
        if self.config.recreate_collection:
            self.client.recreate_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=self.config.distance,
                ),
            )
            return

        collections = self.client.get_collections().collections
        existing_names = {collection.name for collection in collections}

        if self.config.collection_name not in existing_names:
            self.client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=self.config.distance,
                ),
            )

    def point_id(self, source_row: SourceRow) -> int:
        """
        Build a deterministic integer point ID.

        The stride is configurable through point_id_shard_size and should match
        the preprocessing shard size. A validation error is raised if a row index
        would collide with the next shard's ID range.
        """
        if source_row.source_row_index >= self.config.point_id_shard_size:
            raise ValueError(
                "source_row_index exceeds configured point_id_shard_size: "
                f"row_index={source_row.source_row_index}, "
                f"point_id_shard_size={self.config.point_id_shard_size}"
            )

        return (
            source_row.source_shard_id * self.config.point_id_shard_size
            + source_row.source_row_index
        )

    @staticmethod
    def payload(source_row: SourceRow) -> dict[str, Any]:
        """
        Construct Qdrant payload from normalized row and source metadata.
        """
        row = source_row.row

        payload = {
            "lang": row.get("lang"),
            "word": row.get("word"),
            "pos": row.get("pos"),
            "glosses": row.get("glosses", []),
            "source_shard_id": source_row.source_shard_id,
            "source_shard_path": str(source_row.source_shard_path),
            "source_row_index": source_row.source_row_index,
        }

        if "expansion" in row:
            payload["expansion"] = row["expansion"]

        return payload

    def upsert_batch(self, source_rows: list[SourceRow], vectors: np.ndarray) -> None:
        """
        Upsert one batch of source rows and vectors.

        Args:
            source_rows: Source rows in the same order as vectors.
            vectors: NumPy array of shape (len(source_rows), vector_size).
        """
        if len(source_rows) != len(vectors):
            raise ValueError("source_rows and vectors length mismatch")

        if vectors.ndim != 2:
            raise ValueError(f"vectors must be 2D, got shape={vectors.shape}")

        if vectors.shape[1] != self.config.vector_size:
            raise ValueError(
                f"vector dimension mismatch: got {vectors.shape[1]}, "
                f"expected {self.config.vector_size}"
            )

        points = [
            PointStruct(
                id=self.point_id(source_row),
                vector=vectors[index].tolist(),
                payload=self.payload(source_row),
            )
            for index, source_row in enumerate(source_rows)
        ]

        self.client.upsert(
            collection_name=self.config.collection_name,
            points=points,
        )


class QdrantUpsertWorker:
    """
    Background worker that consumes embedded batches and writes them to Qdrant.

    The producer sends UpsertBatch objects into the queue. A None sentinel stops
    the worker after all prior batches have been processed.

    Any exception raised by Qdrant upserts is captured and can be re-raised in
    the main thread with raise_if_failed().
    """

    def __init__(self, writer: QdrantWriter, queue: UpsertQueue) -> None:
        self.writer = writer
        self.queue = queue
        self.exception: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """
        Start the background writer thread.
        """
        self._thread.start()

    def stop(self) -> None:
        """
        Send the stop sentinel and wait for the writer thread to exit.
        """
        self.queue.put(None)
        self._thread.join()

    def raise_if_failed(self) -> None:
        """
        Re-raise any exception captured in the writer thread.
        """
        if self.exception is not None:
            raise RuntimeError("Qdrant upsert worker failed") from self.exception

    def _run(self) -> None:
        """
        Consume queue items until a None sentinel is received.
        """
        while True:
            item = self.queue.get()

            try:
                if item is None:
                    return

                self.writer.upsert_batch(item.source_rows, item.vectors)

            except BaseException as exc:
                self.exception = exc
                return

            finally:
                self.queue.task_done()
