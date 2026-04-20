"""Integration tests for indexing and positional read."""

from __future__ import annotations

import json
import shutil

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_consumption import (
    get_rule_timeline,
    query_rules,
)
from meridian.tools.knowledge_management import (
    approve_proposal,
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

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def test_index_atomic_seed_file(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")

    result = index_rules_from_markdown(
        filepath, default_scope_id="global-java", mode="atomic"
    )

    assert result["indexed"] == 3
    assert result["created"] == 3
    assert result["updated"] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM rules")
    assert cursor.fetchone()[0] == 3

    cursor = conn.execute("SELECT COUNT(*) FROM rule_history")
    assert cursor.fetchone()[0] == 3


def test_index_reindex_no_change(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")

    result1 = index_rules_from_markdown(
        filepath, default_scope_id="global-java", mode="atomic"
    )
    assert result1["created"] == 3

    result2 = index_rules_from_markdown(
        filepath, default_scope_id="global-java", mode="atomic"
    )
    assert result2["updated"] == 0
    assert result2["created"] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM rules")
    assert cursor.fetchone()[0] == 3

    cursor = conn.execute("SELECT COUNT(*) FROM rule_history")
    assert cursor.fetchone()[0] == 3


def test_index_legacy_creates_proposals(tmp_kb):
    kb_path, conn = tmp_kb
    legacy_file = kb_path / "knowledge-base" / "global" / "legacy.md"
    legacy_file.write_text(
        """## Phase 1

### Rule 1: Always use logging
- **Category**: logging
- **Severity**: high

### Rule 2: Use constructor injection
- **Category**: di
- **Severity**: medium
"""
    )

    result = index_rules_from_markdown(
        str(legacy_file), default_scope_id="global-java", mode="legacy"
    )

    assert result["indexed"] == 2

    cursor = conn.execute("SELECT COUNT(*) FROM pending_proposals WHERE type = 'rule'")
    assert cursor.fetchone()[0] == 2

    cursor = conn.execute("SELECT COUNT(*) FROM rules")
    assert cursor.fetchone()[0] == 0


def test_approve_proposal_writes_md(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")  # empty seed file

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
            "Test rule for approval.",
            json.dumps(
                {
                    "category": "testing",
                    "severity": "low",
                    "applies_to": "**/*.java",
                    "tags": ["test"],
                    "source": "manual",
                }
            ),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    assert result["code"] == "RN-JAVA-001"
    assert result["scope_id"] == "global-java"

    # Verify the block exists at the end of the .md file
    raw_bytes = dest_file.read_bytes()
    block_text = raw_bytes[
        result["file_offset"] : result["file_offset"] + result["byte_length"]
    ].decode("utf-8")
    assert "## RN-JAVA-001" in block_text
    assert "**Regla:** Test rule for approval." in block_text

    # Verify DB record points to the correct offset
    cursor = conn.execute(
        "SELECT file_offset, byte_length FROM rules WHERE code = ?",
        (result["code"],),
    )
    row = cursor.fetchone()
    assert row[0] == result["file_offset"]
    assert row[1] == result["byte_length"]


def test_positional_read_after_approve(tmp_kb):
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
            "Positional read test rule.",
            json.dumps(
                {
                    "category": "testing",
                    "severity": "low",
                    "applies_to": "**/*.java",
                    "tags": ["test"],
                    "source": "manual",
                }
            ),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    raw_bytes = dest_file.read_bytes()
    chunk = raw_bytes[
        result["file_offset"] : result["file_offset"] + result["byte_length"]
    ]
    text = chunk.decode("utf-8")

    expected_block = (
        "## RN-JAVA-001\n"
        "**Scope:** global-java\n"
        "**Categoría:** testing\n"
        "**Severidad:** low\n"
        "**Aplica a:** **/*.java\n"
        "**Tags:** test\n"
        "**Fuente:** manual\n"
        "**Regla:** Positional read test rule."
    )
    assert text == expected_block

def test_query_rules_summary(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = query_rules("global-java", detail="summary")
    data = json.loads(result)

    assert len(data) == 3
    assert "code" in data[0]
    assert "text" not in data[0]


def test_query_rules_full(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = query_rules("global-java", detail="full")
    data = json.loads(result)

    assert len(data) == 3
    assert "text" in data[0]
    assert "Regla:" in data[0]["text"]


def test_query_rules_filter_severity(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = query_rules("global-java", severity="critical")
    data = json.loads(result)

    assert len(data) == 2
    codes = {r["code"] for r in data}
    assert codes == {"RN-JAVA-001", "RN-JAVA-002"}


def test_query_rules_filter_category(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = query_rules("global-java", category="logging")
    data = json.loads(result)

    assert len(data) == 1
    assert data[0]["code"] == "RN-JAVA-002"


def test_query_rules_scope_resolution(tmp_kb):
    kb_path, conn = tmp_kb
    java_file = kb_path / "knowledge-base" / "global" / "java.md"
    shutil.copy("knowledge-base/global/java.md", java_file)
    index_rules_from_markdown(
        str(java_file), default_scope_id="global-java", mode="atomic"
    )

    quarkus_file = kb_path / "knowledge-base" / "global" / "quarkus.md"
    quarkus_file.write_text(
        "## RN-QUARKUS-001\n"
        "**Scope:** global-quarkus\n"
        "**Categoriía:** http-client\n"
        "**Severidad:** high\n"
        "**Aplica a:** **/*.java\n"
        "**Tags:** resteasy, http\n"
        "**Fuente:** manual\n"
        "**Regla:** Use RestEasy client for HTTP calls.\n"
    )
    index_rules_from_markdown(
        str(quarkus_file), default_scope_id="global-quarkus", mode="atomic")


    global_file = kb_path / "knowledge-base" / "global" / "general.md"
    global_file.write_text(
        "## RN-GLOBAL-001\n"
        "**Scope:** global\n"
        "**Categoriía:** general\n"
        "**Severidad:** medium\n"
        "**Aplica a:** **/*\n"
        "**Tags:** general\n"
        "**Fuente:** manual\n"
        "**Regla:** Follow company guidelines.\n"
    )
    index_rules_from_markdown(
        str(global_file), default_scope_id="global", mode="atomic"
    )

    psp_file = kb_path / "knowledge-base" / "projects" / "psp-integrator.md"
    psp_file.write_text(
        "## RN-PSP-001\n"
        "**Scope:** project-psp-integrator\n"
        "**Categoriía:** payment\n"
        "**Severidad:** critical\n"
        "**Aplica a:** **/*.java\n"
        "**Tags:** psp, payment\n"
        "**Fuente:** manual\n"
        "**Regla:** Validate PSP response before processing.\n"
    )
    index_rules_from_markdown(
        str(psp_file), default_scope_id="project-psp-integrator", mode="atomic"
    )

    result = query_rules("project-psp-integrator", detail="summary")
    data = json.loads(result)

    codes = {r["code"] for r in data}
    assert "RN-JAVA-001" in codes
    assert "RN-QUARKUS-001" in codes
    assert "RN-GLOBAL-001" in codes
    assert "RN-PSP-001" in codes



def test_query_rules_toon_format(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    result = query_rules("global-java", format="toon", detail="summary")

    assert result.startswith("items[3]{")


def test_query_rules_stale_index(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    md_path = kb_path / "knowledge-base" / "global" / "java.md"
    md_path.write_text("## RN-JAVA-001\n**Regla:** Shortened.\n")

    result = query_rules("global-java", detail="full")
    data = json.loads(result)

    stale_items = [r for r in data if r.get("error") == "STALE_INDEX"]
    assert len(stale_items) >= 1


def test_get_rule_timeline(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    md_path = kb_path / "knowledge-base" / "global" / "java.md"
    original = md_path.read_text()
    modified = original.replace(
        "All code must be synchronous/imperative.",
        "All code must be synchronous and imperative only.",
    )
    md_path.write_text(modified)

    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    timeline = get_rule_timeline("RN-JAVA-001")
    assert timeline["rule_code"] == "RN-JAVA-001"
    assert len(timeline["history_events"]) == 2
    assert timeline["history_events"][0]["change_type"] == "CREATED"
    assert timeline["history_events"][1]["change_type"] == "UPDATED"
