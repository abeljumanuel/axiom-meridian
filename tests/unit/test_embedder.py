"""Unit tests for the sentence-transformers embedder."""

from __future__ import annotations

import math
import time


from meridian.rag import embedder as embedder_module
from meridian.rag.embedder import (
    generate_embedding,
    generate_embeddings_batch,
    warm_up_in_background,
)


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


def test_warm_up_in_background_does_not_block() -> None:
    """Regression (Hallazgo 1 follow-up): warm_up_in_background must
    return immediately — it starts the load on a background thread, it
    does not wait for it."""
    start = time.perf_counter()
    warm_up_in_background()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"warm_up_in_background blocked for {elapsed:.2f}s"


def test_warm_up_in_background_eventually_loads_the_model() -> None:
    warm_up_in_background()
    deadline = time.time() + 60
    while embedder_module._embedder._model is None and time.time() < deadline:
        time.sleep(0.05)
    assert embedder_module._embedder._model is not None


def test_concurrent_warm_up_and_real_call_share_one_model_instance() -> None:
    """The background warm-up and a real request racing for the model
    must converge on the same singleton instance, not load it twice."""
    warm_up_in_background()
    result = generate_embedding("concurrent warm-up test")
    assert len(result) == 384

    model_ref = embedder_module._embedder._model
    assert model_ref is not None

    warm_up_in_background()
    time.sleep(0.2)
    assert embedder_module._embedder._model is model_ref
