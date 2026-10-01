"""Unit tests for rag/vector_store.py's delete_rule/delete_lesson."""

from __future__ import annotations

import pytest

from meridian.rag import vector_store
from meridian.rag.vector_store import reset_client

pytest.importorskip("chromadb")


@pytest.fixture
def tmp_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(tmp_path))
    reset_client()
    yield
    reset_client()


def test_delete_rule_removes_it_from_semantic_search(tmp_chroma):
    vector_store.upsert_rule(
        "RN-JAVA-001", "Some rule text", [0.1] * 384, {"scope_id": "global-java"}
    )
    before = vector_store.search_rules([0.1] * 384, ["global-java"])
    assert any(r["id"] == "RN-JAVA-001" for r in before)

    vector_store.delete_rule("RN-JAVA-001")

    after = vector_store.search_rules([0.1] * 384, ["global-java"])
    assert all(r["id"] != "RN-JAVA-001" for r in after)


def test_delete_lesson_removes_it_from_semantic_search(tmp_chroma):
    vector_store.upsert_lesson(
        "LL-JAVA-001", "Some lesson text", [0.2] * 384, {"scope_id": "global-java"}
    )
    before = vector_store.search_lessons([0.2] * 384, ["global-java"])
    assert any(lesson["id"] == "LL-JAVA-001" for lesson in before)

    vector_store.delete_lesson("LL-JAVA-001")

    after = vector_store.search_lessons([0.2] * 384, ["global-java"])
    assert all(lesson["id"] != "LL-JAVA-001" for lesson in after)


def test_delete_rule_on_never_upserted_id_does_not_raise(tmp_chroma):
    vector_store.delete_rule("RN-NEVER-EXISTED")  # must not raise


def test_delete_lesson_on_never_upserted_id_does_not_raise(tmp_chroma):
    vector_store.delete_lesson("LL-NEVER-EXISTED")  # must not raise
