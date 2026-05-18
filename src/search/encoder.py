"""
Query embedding model lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass(frozen=True)
class QueryEncoderConfig:
    """
    Runtime configuration for query embedding in a web worker.
    """

    model_name: str
    device: str = "auto"
    normalize_embeddings: bool = True


class QueryEncoder:
    """
    SentenceTransformer query encoder loaded once per worker process.

    Multiple FastAPI workers each construct their own encoder. This avoids a
    central model bottleneck and makes worker count a hardware tuning decision.
    """

    def __init__(self, config: QueryEncoderConfig) -> None:
        self.config = config
        self.model = SentenceTransformer(
            config.model_name,
            device=None if config.device == "auto" else config.device,
        )

    @property
    def embedding_dimension(self) -> int:
        """
        Return the query vector dimension expected by Qdrant.
        """
        return int(self.model.get_sentence_embedding_dimension())

    def is_loaded(self) -> bool:
        """
        Report whether the model object is available for health checks.
        """
        return self.model is not None

    def encode_query(self, query: str) -> list[float]:
        """
        Encode one search query as a normalized vector.
        """
        vector = self.model.encode(
            [query],
            normalize_embeddings=self.config.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        array = np.asarray(vector, dtype=np.float32)

        if array.shape != (1, self.embedding_dimension):
            raise RuntimeError(f"Unexpected query embedding shape: {array.shape}")

        return array[0].tolist()
