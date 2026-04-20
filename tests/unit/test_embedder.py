"""Unit tests for the sentence-transformers embedder."""

from __future__ import annotations

import math

import pytest

from meridian.rag.embedder import generate_embedding, generate_embeddings_batch


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def test_generate_embedding_dimensions() -> None:
    """A single text must produce a vector of exactly 384 dimensions."""
    embedding = generate_embedding("This is a test sentence.")
    assert isinstance(embedding, list)
    assert len(embedding) == 384
    assert all(isinstance(v, float) for v in embedding)


def test_generate_batch() -> None:
    """A batch of 3 texts must produce 3 vectors of 384 dimensions each."""
    texts = [
        "First test sentence.",
        "Second test sentence.",
        "Third test sentence.",
    ]
    embeddings = generate_embeddings_batch(texts)
    assert len(embeddings) == 3
    for emb in embeddings:
        assert len(emb) == 384
        assert all(isinstance(v, float) for v in emb)


def test_similar_texts_closer() -> None:
    """Semantically similar texts must have high cosine similarity;
    unrelated texts must have low similarity.
    """
    texts = [
        "exception handling in Java",
        "Java error management",
        "Flutter widget layout",
    ]
    embeddings = generate_embeddings_batch(texts)

    sim_0_1 = _cosine_similarity(embeddings[0], embeddings[1])
    sim_0_2 = _cosine_similarity(embeddings[0], embeddings[2])
    sim_1_2 = _cosine_similarity(embeddings[1], embeddings[2])

    assert sim_0_1 > 0.7, f"Expected > 0.7, got {sim_0_1}"
    assert sim_0_2 < 0.6, f"Expected < 0.6, got {sim_0_2}"
    assert sim_1_2 < 0.6, f"Expected < 0.6, got {sim_1_2}"
