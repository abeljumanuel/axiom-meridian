"""Integration tests for get_rule_audit_log's deprecated_rules surfacing,
covering both deprecation origins (promote_rule and the deprecate proposal
type added by add-rule-lesson-deprecation)."""

from __future__ import annotations

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.extraction import create_pending_proposal
from meridian.tools.knowledge_consumption import get_rule_audit_log
from meridian.tools.knowledge_management import approve_proposal, promote_rule


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
    yield kb_path, conn
    conn.close()


def _seed_rule(conn, code: str, scope_id: str, file_path, text: str = "Some text.") -> None:
    block = f"## {code}\n**Regla:** {text}\n"
    file_path.write_text(block)
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, 'general', 'medium', ?, 0, ?)
        """,
        (code, scope_id, code, text, str(file_path), len(block.encode("utf-8"))),
    )
    conn.commit()


def test_rule_deprecated_via_promote_rule_appears_in_audit_log(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "promoted.md"
    _seed_rule(conn, "RN-JAVA-010", "global-java", dest_file)

    promote_rule("RN-JAVA-010", "global-quarkus")

    result = get_rule_audit_log(scope_id="global-java")
    dep = next(r for r in result["deprecated_rules"] if r["code"] == "RN-JAVA-010")
    assert dep["deprecation_reason"] == "Promoted to scope global-quarkus"
    # promote_rule never sets a structured superseded_by (Decision 4):
    # the destination scope lives only in the free-text reason above.
    assert dep["superseded_by"] is None


def test_rule_deprecated_via_deprecate_rule_appears_with_structured_superseded_by(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "deprecated.md"
    _seed_rule(conn, "RN-JAVA-011", "global-java", dest_file, text="Old approach.")
    replacement_file = kb_path / "knowledge-base" / "global" / "replacement.md"
    _seed_rule(conn, "RN-JAVA-012", "global-java", replacement_file, text="New approach.")

    prop_id = create_pending_proposal(
        conn,
        "deprecate",
        "Old approach.",
        "global-java",
        target_id="RN-JAVA-011",
        reason="Superseded by the new approach",
        metadata={"superseded_by": "RN-JAVA-012"},
    )
    approve_proposal(prop_id)

    result = get_rule_audit_log(scope_id="global-java")
    dep = next(r for r in result["deprecated_rules"] if r["code"] == "RN-JAVA-011")
    assert dep["deprecation_reason"] == "Superseded by the new approach"
    assert dep["superseded_by"] == "RN-JAVA-012"
