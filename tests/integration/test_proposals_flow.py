"""Integration tests for proposal lifecycle (edit, reject, approve with attributes)."""

from __future__ import annotations

import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_management import (
    approve_proposal,
    edit_proposal,
    reject_proposal,
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


def test_edit_proposal(tmp_kb):
    kb_path, conn = tmp_kb

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (prop_id, "rule", "global-java", "Original text.", "pending"),
    )
    conn.commit()

    result = edit_proposal(prop_id, "Updated text.")

    assert result["proposal_id"] == prop_id
    assert result["status"] == "pending"

    cursor = conn.execute(
        "SELECT proposed_text, status FROM pending_proposals WHERE id = ?",
        (prop_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "Updated text."
    assert row[1] == "pending"


def test_reject_proposal(tmp_kb):
    kb_path, conn = tmp_kb

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (prop_id, "rule", "global-java", "Some text.", "pending"),
    )
    conn.commit()

    result = reject_proposal(prop_id, reason="Not applicable")

    assert result["proposal_id"] == prop_id
    assert result["status"] == "rejected"

    cursor = conn.execute(
        "SELECT status, reason FROM pending_proposals WHERE id = ?",
        (prop_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "rejected"
    assert row[1] == "Not applicable"


def test_approve_with_attributes(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, metadata, suggested_attributes, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            "rule",
            "global-java",
            "Rule with attributes.",
            json.dumps(
                {
                    "category": "testing",
                    "severity": "low",
                    "applies_to": "**/*.java",
                    "tags": ["test"],
                    "source": "manual",
                }
            ),
            json.dumps(
                [
                    {"key": "framework", "value": "quarkus"},
                    {"key": "component_role", "value": "gateway"},
                ]
            ),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    cursor = conn.execute(
        "SELECT key, value FROM rule_attributes WHERE rule_id = ?",
        (result["code"],),
    )
    rows = cursor.fetchall()
    attrs = {row[0]: row[1] for row in rows}

    assert attrs["framework"] == "quarkus"
    assert attrs["component_role"] == "gateway"
