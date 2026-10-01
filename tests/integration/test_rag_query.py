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
    promote_rule,
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

    assert result["embedded"] is True
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
    result = approve_proposal("prop-0002")
    assert result["embedded"] is True

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


def test_approve_deprecate_proposal_rule_full_flow(tmp_kb):
    """add-rule-lesson-deprecation: approving a DEPRECATE proposal for a
    rule sets status='deprecated', marks the .md block, records a
    DEPRECATED rule_history row with reason/superseded_by, clears
    embedding_id, and removes the rule from semantic search — without
    touching its scope_id (unlike promote_rule)."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)  # RN-JAVA-001/002/003 now embedded

    original_scope = conn.execute(
        "SELECT scope_id FROM rules WHERE code = 'RN-JAVA-003'"
    ).fetchone()[0]

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, target_id, proposed_text, metadata, reason, status)
        VALUES (?, 'deprecate', 'RN-JAVA-003', 'Test rule one', ?, ?, 'pending')
        """,
        (
            "prop-dep-001",
            json.dumps({"superseded_by": "RN-JAVA-001"}),
            "No longer applies after the v2 rewrite",
        ),
    )
    conn.commit()

    result = approve_proposal("prop-dep-001")
    assert result["target_id"] == "RN-JAVA-003"
    assert result["status"] == "deprecated"
    assert result["superseded_by"] == "RN-JAVA-001"
    assert result["embedding_removed"] is True

    row = conn.execute(
        "SELECT status, scope_id, embedding_id, file_path, file_offset, byte_length "
        "FROM rules WHERE code = 'RN-JAVA-003'"
    ).fetchone()
    assert row[0] == "deprecated"
    assert row[1] == original_scope  # unchanged, unlike promote_rule
    assert row[2] is None

    md_bytes = open(row[3], "rb").read()
    block = md_bytes[row[4] : row[4] + row[5]]
    assert b"**Status:** deprecated" in block

    hist = conn.execute(
        "SELECT change_type, reason, superseded_by FROM rule_history "
        "WHERE rule_id = 'RN-JAVA-003' AND change_type = 'DEPRECATED'"
    ).fetchone()
    assert hist[0] == "DEPRECATED"
    assert hist[1] == "No longer applies after the v2 rewrite"
    assert hist[2] == "RN-JAVA-001"

    from meridian.rag import embedder

    hits = vector_store.search_rules(
        embedder.generate_embedding("Test rule one"), ["global-java"], top_k=20
    )
    assert all(h["id"] != "RN-JAVA-003" for h in hits)


def test_approve_deprecate_proposal_lesson_full_flow(tmp_kb):
    """Same as above, for a lesson target — deprecate_rule's proposal type
    is generic over RN-/LL- prefixes."""
    kb_path, conn = tmp_kb
    lessons_md = kb_path / "lessons" / "global" / "example.md"
    lesson_block = (
        "## LL-JAVA-001\n**Qué pasó:** A deploy silently failed.\n"
    )
    lessons_md.write_text(lesson_block)
    byte_length = len(lesson_block.encode("utf-8"))

    conn.execute(
        """
        INSERT INTO lessons
        (id, scope_id, code, what_happened, severity, status, file_path, file_offset, byte_length)
        VALUES (?, 'global-java', ?, ?, 'medium', 'active', ?, 0, ?)
        """,
        ("LL-JAVA-001", "LL-JAVA-001", "A deploy silently failed.", str(lessons_md), byte_length),
    )
    conn.commit()
    generate_embeddings(conn)

    row = conn.execute(
        "SELECT embedding_id FROM lessons WHERE code = 'LL-JAVA-001'"
    ).fetchone()
    assert row[0] is not None  # sanity: embedded before deprecation

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, target_id, proposed_text, reason, status)
        VALUES (?, 'deprecate', 'LL-JAVA-001', 'A deploy silently failed.', ?, 'pending')
        """,
        ("prop-dep-002", "Root cause fixed; no longer relevant."),
    )
    conn.commit()

    result = approve_proposal("prop-dep-002")
    assert result["target_id"] == "LL-JAVA-001"
    assert result["status"] == "deprecated"
    assert result["embedding_removed"] is True

    row = conn.execute(
        "SELECT status, embedding_id FROM lessons WHERE code = 'LL-JAVA-001'"
    ).fetchone()
    assert row[0] == "deprecated"
    assert row[1] is None
    assert b"**Status:** deprecated" in lessons_md.read_bytes()

    hist = conn.execute(
        "SELECT change_type, reason, superseded_by FROM lesson_history "
        "WHERE lesson_id = 'LL-JAVA-001' AND change_type = 'DEPRECATED'"
    ).fetchone()
    assert hist[0] == "DEPRECATED"
    assert hist[1] == "Root cause fixed; no longer relevant."
    assert hist[2] is None

    from meridian.rag import embedder

    hits = vector_store.search_lessons(
        embedder.generate_embedding("A deploy silently failed."), ["global-java"], top_k=20
    )
    assert all(h["id"] != "LL-JAVA-001" for h in hits)


def test_promote_rule_removes_embedding_immediately(tmp_kb):
    """add-rule-lesson-deprecation: promote_rule must not leave a stale
    entry in the vector index until a later generate_embeddings pass —
    it shares the same embedding-removal helper deprecate_rule uses."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)

    result = promote_rule("RN-JAVA-001", "global-quarkus")
    assert result["embedding_removed"] is True

    row = conn.execute(
        "SELECT embedding_id FROM rules WHERE code = 'RN-JAVA-001'"
    ).fetchone()
    assert row[0] is None

    from meridian.rag import embedder

    hits = vector_store.search_rules(
        embedder.generate_embedding("immutable DTO records"),
        ["global-java", "global-quarkus"],
        top_k=20,
    )
    assert all(h["id"] != "RN-JAVA-001" for h in hits)


def test_generate_embeddings_backfills_pre_existing_deprecated_rows(tmp_kb):
    """Rows deprecated before add-rule-lesson-deprecation shipped (status
    set directly, embedding never cleaned up — simulating promote_rule's
    pre-fix behavior) get purged by a later generate_embeddings() call."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)  # RN-JAVA-001/002/003 now embedded

    row = conn.execute(
        "SELECT embedding_id FROM rules WHERE code = 'RN-JAVA-002'"
    ).fetchone()
    assert row[0] is not None  # sanity: embedded

    # Simulate a pre-fix deprecation: status flips without any embedding cleanup.
    conn.execute("UPDATE rules SET status = 'deprecated' WHERE code = 'RN-JAVA-002'")
    conn.commit()

    result = generate_embeddings(conn)
    assert result["purged"] == 1

    row = conn.execute(
        "SELECT embedding_id FROM rules WHERE code = 'RN-JAVA-002'"
    ).fetchone()
    assert row[0] is None

    from meridian.rag import embedder

    hits = vector_store.search_rules(
        embedder.generate_embedding("configuration properties startup"),
        ["global-java"],
        top_k=20,
    )
    assert all(h["id"] != "RN-JAVA-002" for h in hits)


def test_include_deprecated_true_does_not_revive_semantic_results(tmp_kb):
    """A rule deprecated through this capability is removed from the
    vector index (Tasks 5-7) — include_deprecated=True only affects the
    plain-SQL path; the semantic path has nothing to revive and this is
    documented, expected behavior, not a bug."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    generate_embeddings(conn)

    conn.execute(
        """
        INSERT INTO pending_proposals (id, type, target_id, proposed_text, reason, status)
        VALUES ('prop-dep-003', 'deprecate', 'RN-JAVA-001', 'Test rule one', 'No longer applies', 'pending')
        """
    )
    conn.commit()
    approve_proposal("prop-dep-003")

    # SQL path: include_deprecated=True does surface it.
    data = json.loads(query_rules("global-java", detail="summary", include_deprecated=True))
    assert "RN-JAVA-001" in {r["code"] for r in data}

    # Semantic path: still excluded, even with include_deprecated=True,
    # because it was removed from the vector store on deprecation.
    data = json.loads(
        query_rules(
            "global-java",
            query_text="immutable DTO records",
            include_deprecated=True,
        )
    )
    assert "RN-JAVA-001" not in {r["code"] for r in data}
