"""Integration tests for RAG (embeddings + semantic search)."""

from __future__ import annotations

import json
import shutil

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.rag.vector_store import reset_client
from meridian.tools.knowledge_consumption import query_rules
from meridian.tools.knowledge_management import (
    generate_embeddings,
    index_rules_from_markdown,
)


@pytest.fixture
def tmp_kb(tmp_path, monkeypatch):
    """Create a temporary knowledge base with an initialised DB."""
    kb_path = tmp_path / "kb"
    kb_path.mkdir()
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)

    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    reset_client()  # invalidate any cached ChromaDB client

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def test_generate_embeddings_populates_ids(tmp_kb):
    """After indexing and generating embeddings, all rules must have
    embedding_id set."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = generate_embeddings(conn)
    assert result["processed"] == 3
    assert result["errors"] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM rules WHERE embedding_id IS NOT NULL")
    assert cursor.fetchone()[0] == 3


def test_rag_query_returns_relevant(tmp_kb):
    """Semantic search for 'logging structured JSON' must return RN-JAVA-002."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)

    result = query_rules("global-java", query_text="logging structured JSON")
    data = json.loads(result)

    codes = [r["code"] for r in data]
    assert "RN-JAVA-002" in codes


def test_rag_fallback_to_sql(tmp_kb):
    """Without embeddings generated, a query with query_text must fall back to
    SQL and return normal results without error."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    # intentionally skip generate_embeddings

    result = query_rules("global-java", query_text="logging")
    data = json.loads(result)

    assert len(data) == 3


def test_rag_and_sql_same_results_for_exact_filter(tmp_kb):
    """A semantic query with an exact metadata filter must return the same set
    of rules as the pure-SQL query (order may differ)."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)

    sql_result = query_rules("global-java", severity="critical")
    rag_result = query_rules(
        "global-java", severity="critical", query_text="java"
    )

    sql_data = json.loads(sql_result)
    rag_data = json.loads(rag_result)

    sql_codes = {r["code"] for r in sql_data}
    rag_codes = {r["code"] for r in rag_data}

    assert sql_codes == rag_codes
