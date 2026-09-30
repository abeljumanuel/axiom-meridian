"""Integration tests for RAG (embeddings + semantic search)."""

from __future__ import annotations

import json
import logging
import shutil

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.rag import vector_store
from meridian.rag.vector_store import reset_client
from meridian.tools.knowledge_consumption import query_lessons, query_rules
from meridian.tools.knowledge_management import (
    approve_proposal,
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


def test_approve_create_proposal_embeds_new_rule(tmp_kb):
    """Regression (Hallazgo 5): a newly-approved rule must be findable via
    semantic search without a separate generate_embeddings call —
    previously embedding_id stayed NULL until someone ran it manually."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, metadata, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "prop-0001",
            "rule",
            "global-java",
            "Use records for immutable DTOs instead of plain classes.",
            json.dumps(
                {"category": "style", "severity": "medium", "tags": ["records", "dto"]}
            ),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal("prop-0001")
    code = result["code"]

    row = conn.execute(
        "SELECT embedding_id FROM rules WHERE code = ?", (code,)
    ).fetchone()
    assert row[0] is not None

    search_result = query_rules("global-java", query_text="immutable DTO records")
    codes = [r["code"] for r in json.loads(search_result)]
    assert code in codes


def test_approve_update_proposal_refreshes_vector_store_entry(tmp_kb):
    """Regression (Hallazgo 5): approving an UPDATE must replace the
    vector-store entry under the same id, not leave the pre-update
    text/tags stale — previously embedding_id reset to NULL but nothing
    ever re-upserted ChromaDB's copy."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)

    # RN-JAVA-003 is about constructor injection / "cdi" tag; update it to
    # something unrelated, with a different tag.
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, target_id, proposed_text, metadata, status)
        VALUES (?, 'update', 'RN-JAVA-003', ?, ?, 'pending')
        """,
        (
            "prop-0002",
            "Always validate configuration properties at startup using @ConfigMapping.",
            json.dumps(
                {
                    "category": "configuration",
                    "severity": "high",
                    "tags": ["config-mapping", "startup-validation"],
                }
            ),
        ),
    )
    conn.commit()
    approve_proposal("prop-0002")

    from meridian.rag import embedder

    hits = vector_store.search_rules(
        embedder.generate_embedding("validate configuration properties startup"),
        ["global-java"],
        top_k=5,
    )
    hit = next(h for h in hits if h["id"] == "RN-JAVA-003")
    assert "config-mapping" in hit["metadata"]["tags"]
    assert "cdi" not in hit["metadata"]["tags"]
    assert "constructor" not in hit["text"].lower()


def test_query_rules_warns_about_pending_embeddings(tmp_kb, caplog):
    """Regression (Hallazgo 5b): an active un-embedded rule in scope during
    a semantic search must be logged, not silently omitted with no signal
    at all."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)  # RN-JAVA-001/002/003 now embedded

    # Simulate a rule that exists (e.g. approved) but was never embedded.
    conn.execute(
        "INSERT INTO rules (id, scope_id, code, text, category, severity) "
        "VALUES ('RN-JAVA-004', 'global-java', 'RN-JAVA-004', 'text', 'general', 'medium')"
    )
    conn.commit()

    with caplog.at_level(logging.WARNING):
        query_rules("global-java", query_text="logging")

    assert any("lack an embedding" in rec.message for rec in caplog.records)
    assert any("1 active row" in rec.message for rec in caplog.records)


def test_query_lessons_warns_about_pending_embeddings(tmp_kb, caplog):
    """Same as above, for query_lessons."""
    kb_path, conn = tmp_kb
    conn.execute(
        "INSERT INTO lessons (id, scope_id, code, what_happened, severity) "
        "VALUES ('LL-JAVA-001', 'global-java', 'LL-JAVA-001', 'something happened', 'medium')"
    )
    conn.commit()
    # Force the semantic path: chromadb_available() needs at least one
    # document somewhere, regardless of collection.
    from meridian.rag import embedder

    vector_store.upsert_rule(
        "RN-SENTINEL", "sentinel", embedder.generate_embedding("sentinel"),
        {"scope_id": "global", "category": "x", "severity": "low", "applies_to": "", "tags": "[]"},
    )

    with caplog.at_level(logging.WARNING):
        query_lessons("global-java", query_text="something")

    assert any("lack an embedding" in rec.message for rec in caplog.records)
    assert any("1 active row" in rec.message for rec in caplog.records)
