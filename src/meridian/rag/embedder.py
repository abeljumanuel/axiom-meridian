"""Sentence-transformers embedder with lazy loading and auto device detection."""

from __future__ import annotations

import logging
import platform
from typing import ClassVar

logger = logging.getLogger(__name__)


class _Embedder:
    """Lazy-loaded embedder singleton."""

    _instance: ClassVar[_Embedder | None] = None
    _model: ClassVar[object | None] = None
    _device: ClassVar[str | None] = None

    MODEL_NAME: ClassVar[str] = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: ClassVar[int] = 384

    def __new__(cls) -> _Embedder:  # noqa: D102
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _detect_device(self) -> str:
        """Return the best available torch device."""
        try:
            import torch
        except ImportError:  # pragma: no cover
            return "cpu"

        if torch.cuda.is_available():
            return "cuda"
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            try:
                torch.zeros(1).to("mps")
                return "mps"
            except Exception:
                pass
        return "cpu"

    def _load(self) -> object:
        """Lazy-load the SentenceTransformer model."""
        if self._model is not None:
            return self._model

        from sentence_transformers import SentenceTransformer

        self._device = self._detect_device()
        logger.info(
            "Loading embedding model %s on device %s",
            self.MODEL_NAME,
            self._device,
        )
        self._model = SentenceTransformer(self.MODEL_NAME, device=self._device)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into embeddings."""
        model = self._load()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]


_embedder = _Embedder()


def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding vector (384-dim)."""
    return _embedder.encode([text])[0]


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in one batch."""
    return _embedder.encode(texts)
