"""
SentenceTransformer wrapper used by offline embedding generation.

The wrapper centralizes model loading, device selection, normalization, and
shape checks so the pipeline code can treat encoding as a stable batch
operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from sentence_transformers import SentenceTransformer


DeviceName = Literal["cpu", "cuda", "mps", "auto"]


@dataclass(frozen=True)
class EmbeddingModelConfig:
    """
    Configuration for embedding model loading and encoding.

    normalize_embeddings should generally be true when using cosine similarity
    in the vector index.
    """

    model_name: str
    device: DeviceName = "auto"
    normalize_embeddings: bool = True


class EmbeddingModel:
    """
    Thin wrapper around SentenceTransformer.

    Contract:
    - model is loaded once
    - encode preserves input order
    - number of returned vectors equals number of input texts
    - returned vectors are float32 NumPy arrays
    """

    def __init__(self, config: EmbeddingModelConfig) -> None:
        self.config = config
        self.model = SentenceTransformer(
            config.model_name,
            device=None if config.device == "auto" else config.device,
        )

    @property
    def embedding_dimension(self) -> int:
        """
        Return output vector dimension for the loaded model.
        """
        return int(self.model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        """
        Encode a batch of texts into dense vectors.

        Args:
            texts: Input texts.
            batch_size: Internal SentenceTransformer batch size.

        Returns:
            NumPy array with shape (len(texts), embedding_dimension).
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        if not texts:
            return np.empty((0, self.embedding_dimension), dtype=np.float32)

        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self.config.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        if len(vectors) != len(texts):
            raise RuntimeError("Embedding count does not match input text count")

        return vectors.astype(np.float32, copy=False)
