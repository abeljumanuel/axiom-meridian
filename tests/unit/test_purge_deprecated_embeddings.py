"""Unit tests for knowledge_management._purge_deprecated_embeddings_for_table."""

from __future__ import annotations

import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_management import _purge_deprecated_embeddings_for_table


@pytest.fixture
def tmp_kb(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb"
    kb_path.mkdir()
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def _seed_rule(conn, code: str, status: str, embedding_id: str | None, scope_id: str = "global-java") -> None:
    conn.execute(
        """
        INSERT INTO rules (id, scope_id, code, text, category, severity, status, tags, embedding_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (code, scope_id, code, "text", "architecture", "medium", status, json.dumps([]), embedding_id),
    )
    conn.commit()


def test_purges_deprecated_row_with_embedding(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-001", status="deprecated", embedding_id="hash123")

    purged_ids = []
    count = _purge_deprecated_embeddings_for_table(
        conn, table="rules", kind="rule", delete_fn=purged_ids.append, scope_id=None
    )

    assert count == 1
    assert purged_ids == ["RN-JAVA-001"]
    row = conn.execute("SELECT embedding_id FROM rules WHERE code = 'RN-JAVA-001'").fetchone()
    assert row[0] is None


def test_does_not_touch_already_clean_deprecated_row(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-002", status="deprecated", embedding_id=None)

    calls = []
    count = _purge_deprecated_embeddings_for_table(
        conn, table="rules", kind="rule", delete_fn=calls.append, scope_id=None
    )

    assert count == 0
    assert calls == []


def test_does_not_touch_active_rows(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-003", status="active", embedding_id="hash456")

    calls = []
    count = _purge_deprecated_embeddings_for_table(
        conn, table="rules", kind="rule", delete_fn=calls.append, scope_id=None
    )

    assert count == 0
    assert calls == []


def test_scope_id_filters_the_purge(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-004", status="deprecated", embedding_id="h1", scope_id="global-java")
    _seed_rule(conn, "RN-GO-001", status="deprecated", embedding_id="h2", scope_id="global-go")

    calls = []
    count = _purge_deprecated_embeddings_for_table(
        conn, table="rules", kind="rule", delete_fn=calls.append, scope_id="global-java"
    )

    assert count == 1
    assert calls == ["RN-JAVA-004"]
