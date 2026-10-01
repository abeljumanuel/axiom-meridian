"""Unit tests for knowledge_management._remove_embedding_after_deprecate."""

from __future__ import annotations

import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_management import _remove_embedding_after_deprecate


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


def _seed_rule(conn, code: str, embedding_id: str | None) -> None:
    conn.execute(
        """
        INSERT INTO rules (id, scope_id, code, text, category, severity, status, tags, embedding_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (code, "global-java", code, "Some text", "architecture", "medium", "deprecated", json.dumps([]), embedding_id),
    )
    conn.commit()


def test_clears_embedding_id_and_calls_delete_fn(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-001", embedding_id="abc123")

    calls = []
    result = _remove_embedding_after_deprecate(
        conn, table="rules", kind="rule", code="RN-JAVA-001", delete_fn=calls.append
    )

    assert result is True
    assert calls == ["RN-JAVA-001"]
    row = conn.execute("SELECT embedding_id FROM rules WHERE code = ?", ("RN-JAVA-001",)).fetchone()
    assert row[0] is None


def test_delete_fn_exception_is_logged_and_swallowed(tmp_kb):
    conn = tmp_kb
    _seed_rule(conn, "RN-JAVA-002", embedding_id="abc123")

    def _boom(_id):
        raise RuntimeError("vector store unavailable")

    result = _remove_embedding_after_deprecate(
        conn, table="rules", kind="rule", code="RN-JAVA-002", delete_fn=_boom
    )

    assert result is False
    # Failure leaves embedding_id as it was — not force-nulled on a failed attempt.
    row = conn.execute("SELECT embedding_id FROM rules WHERE code = ?", ("RN-JAVA-002",)).fetchone()
    assert row[0] == "abc123"


def test_returns_false_for_unknown_code(tmp_kb):
    conn = tmp_kb

    result = _remove_embedding_after_deprecate(
        conn, table="rules", kind="rule", code="RN-JAVA-999", delete_fn=lambda _id: None
    )

    assert result is False
