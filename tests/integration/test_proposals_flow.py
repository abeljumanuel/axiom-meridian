"""Integration tests for proposal lifecycle (edit, reject, approve with attributes)."""

from __future__ import annotations

import hashlib
import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_management import (
    approve_proposal,
    edit_proposal,
    promote_rule,
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


def test_approve_proposal_keeps_indexed_files_and_tags_in_sync(tmp_kb):
    """T05 acceptance: after approve_proposal, indexed_files.content_hash
    matches the real .md on disk, and rule_tags mirrors the metadata tags."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, metadata, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            "rule",
            "global-java",
            "Rule with tags.",
            json.dumps({"tags": ["go", "fiber"]}),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    row = conn.execute(
        "SELECT content_hash FROM indexed_files WHERE file_path = ?",
        (str(dest_file),),
    ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(dest_file.read_bytes()).hexdigest()

    tags = {
        r[0]
        for r in conn.execute(
            "SELECT tag FROM rule_tags WHERE rule_id = ?", (result["code"],)
        )
    }
    assert tags == {"go", "fiber"}


def test_promote_rule_refreshes_indexed_files_for_affected_file(tmp_kb):
    """T05 acceptance: after promote_rule (_mark_deprecated_in_md),
    indexed_files for the affected .md reflects the deprecation edit."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "projects" / "example.md"
    dest_file.write_text("## RN-EXAMPLE-001\nSome rule text.\n")

    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "RN-EXAMPLE-001",
            "project-project-example",
            "RN-EXAMPLE-001",
            "Some rule text.",
            "general",
            "medium",
            str(dest_file),
            0,
            len("## RN-EXAMPLE-001\nSome rule text.\n".encode("utf-8")) - 1,
        ),
    )
    conn.commit()

    promote_rule("RN-EXAMPLE-001", "global-quarkus")

    row = conn.execute(
        "SELECT content_hash FROM indexed_files WHERE file_path = ?",
        (str(dest_file),),
    ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(dest_file.read_bytes()).hexdigest()
    assert b"**Status:** deprecated" in dest_file.read_bytes()
