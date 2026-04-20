"""Integration tests for audit flows and extraction tools."""

from __future__ import annotations

import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.audit_flows import (
    analyze_pr_feedback,
    audit_pr,
    check_feature_against_rules,
)
from meridian.tools.extraction import (
    create_pending_proposal,
    extract_rules_from_transcript,
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

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def _seed_rules(conn: sqlite3.Connection) -> None:
    """Insert sample rules so queries return non-empty results."""
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, status, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-001",
            "global-java",
            "RN-JAVA-001",
            "Test rule one",
            "architecture",
            "critical",
            "active",
            json.dumps(["test"]),
        ),
    )
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, status, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-002",
            "global-java",
            "RN-JAVA-002",
            "Test rule two",
            "logging",
            "high",
            "active",
            json.dumps(["test"]),
        ),
    )
    conn.commit()


def test_audit_pr_persists_record(tmp_kb):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    pr_diff = "diff --git a/src/Foo.java b/src/Foo.java\n+line\n"
    result = audit_pr(conn, pr_diff, "global-java")

    assert "audit_id" in result
    assert result["pr_diff"] == pr_diff
    assert len(result["rules"]) == 2
    assert isinstance(result["lessons"], list)

    cursor = conn.execute(
        "SELECT rules_evaluated, rule_version_snapshot "
        "FROM pr_audits WHERE id = ?",
        (result["audit_id"],),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 2
    snapshot = json.loads(row[1])
    assert len(snapshot) > 0
    assert "RN-JAVA-001" in snapshot


def test_analyze_pr_feedback_links_audit(tmp_kb):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    audit_id = "audit-0001"
    conn.execute(
        """
        INSERT INTO pr_audits
        (id, project_id, pr_ref, diff_hash, rules_evaluated, rule_version_snapshot)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            "global-java",
            "PR-42",
            "hash123",
            2,
            json.dumps({"RN-JAVA-001": {"severity": "critical"}}),
        ),
    )
    conn.commit()

    result = analyze_pr_feedback(conn, "Feedback text", "PR-42", "global-java")

    assert result["feedback_text"] == "Feedback text"
    assert result["pr_audit_record"]["id"] == audit_id
    assert len(result["rules_that_applied"]) == 1


def test_check_feature_persists(tmp_kb):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    result = check_feature_against_rules(conn, "Add payment gateway", "global-java")

    assert "check_id" in result
    assert result["feature_description"] == "Add payment gateway"
    assert len(result["rules"]) == 2

    cursor = conn.execute(
        "SELECT COUNT(*) FROM planning_checks WHERE id = ?",
        (result["check_id"],),
    )
    assert cursor.fetchone()[0] == 1


def test_extract_rules_sanitizes_private(tmp_kb):
    kb_path, conn = tmp_kb
    text = "Discussed endpoint: <private>secret-api-key</private> and timeout"
    result = extract_rules_from_transcript(conn, text, "global-java")

    assert "[REDACTED]" in result["clean_text"]
    assert "secret-api-key" not in result["clean_text"]


def test_create_proposal_validates_scope(tmp_kb):
    kb_path, conn = tmp_kb

    with pytest.raises(ValueError):
        create_pending_proposal(conn, "rule", "Some text", "nonexistent-scope")


def test_create_proposal_strips_private(tmp_kb):
    kb_path, conn = tmp_kb

    prop_id = create_pending_proposal(
        conn,
        "rule",
        "Text with <private>secret</private> inside",
        "global-java",
    )

    cursor = conn.execute(
        "SELECT proposed_text FROM pending_proposals WHERE id = ?",
        (prop_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert "[REDACTED]" in row[0]
    assert "secret" not in row[0]
