"""Integration tests for knowledge template tools (full-stack through server)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from meridian import server
from meridian.db.connection import get_connection, initialize_db


@pytest.fixture
def tmp_server_db(tmp_path, monkeypatch):
    """Create a temporary knowledge base and initialise the global server conn."""
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

    old_conn = server.conn
    server.conn = get_connection(db_path)
    old_transport = server.current_transport
    server.current_transport = "stdio"

    yield server.conn

    server.conn.close()
    server.conn = old_conn
    server.current_transport = old_transport


def _last_access_log(conn: Any, tool_name: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT * FROM access_log WHERE tool_name = ? ORDER BY timestamp DESC LIMIT 1",
        (tool_name,),
    )
    columns = [d[0] for d in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# get_rule_template
# ---------------------------------------------------------------------------


def test_get_rule_template_no_args_returns_base_keys(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_rule_template()
    parsed = json.loads(result)
    assert "template" in parsed
    assert "fields" in parsed
    assert "usage" in parsed


def test_get_rule_template_no_args_no_scope_suggestions(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_rule_template()
    parsed = json.loads(result)
    assert "scope_suggestions" not in parsed


def test_get_rule_template_valid_project_id_scope_suggestions_list(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_rule_template(project_id="project-project-example")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) > 0
    assert parsed["scope_suggestions"][0]["recommended"] is True


def test_get_rule_template_invalid_project_id_no_exception(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    # Must not raise — returns structured error in scope_suggestions
    result = server.get_rule_template(project_id="ghost-xyz")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) == 1
    assert "error" in parsed["scope_suggestions"][0]
    assert len(parsed["scope_suggestions"][0]["error"]) > 0


def test_get_rule_template_audit_log_success(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    server.get_rule_template()
    log = _last_access_log(tmp_server_db, "get_rule_template")
    assert log is not None
    assert log["result"] == "success"
    assert log["access_level"] == "read"


# ---------------------------------------------------------------------------
# get_lesson_template
# ---------------------------------------------------------------------------


def test_get_lesson_template_no_args_returns_base_keys(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_lesson_template()
    parsed = json.loads(result)
    assert "template" in parsed
    assert "fields" in parsed
    assert "usage" in parsed


def test_get_lesson_template_no_args_no_scope_suggestions(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_lesson_template()
    parsed = json.loads(result)
    assert "scope_suggestions" not in parsed


def test_get_lesson_template_valid_project_id_scope_suggestions_list(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_lesson_template(project_id="project-project-example")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) > 0
    assert parsed["scope_suggestions"][0]["recommended"] is True


def test_get_lesson_template_invalid_project_id_no_exception(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_lesson_template(project_id="ghost-xyz")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) == 1
    assert "error" in parsed["scope_suggestions"][0]
    assert len(parsed["scope_suggestions"][0]["error"]) > 0


def test_get_lesson_template_audit_log_success(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    server.get_lesson_template()
    log = _last_access_log(tmp_server_db, "get_lesson_template")
    assert log is not None
    assert log["result"] == "success"
    assert log["access_level"] == "read"


# ---------------------------------------------------------------------------
# get_transcription_template
# ---------------------------------------------------------------------------


def test_get_transcription_template_no_args_returns_base_keys(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_transcription_template()
    parsed = json.loads(result)
    assert "template" in parsed
    assert "fields" in parsed
    assert "usage" in parsed


def test_get_transcription_template_no_args_no_scope_suggestions(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_transcription_template()
    parsed = json.loads(result)
    assert "scope_suggestions" not in parsed


def test_get_transcription_template_template_contains_both_formats(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_transcription_template()
    parsed = json.loads(result)
    assert "## RN-XXX-NNN" in parsed["template"]
    assert "## LL-XXX-NNN" in parsed["template"]


def test_get_transcription_template_valid_project_id_scope_suggestions_list(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_transcription_template(project_id="project-project-example")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) > 0


def test_get_transcription_template_invalid_project_id_no_exception(
    tmp_server_db, monkeypatch
) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.get_transcription_template(project_id="ghost-xyz")
    parsed = json.loads(result)
    assert isinstance(parsed["scope_suggestions"], list)
    assert len(parsed["scope_suggestions"]) == 1
    assert "error" in parsed["scope_suggestions"][0]


def test_get_transcription_template_audit_log_success(tmp_server_db, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    server.get_transcription_template()
    log = _last_access_log(tmp_server_db, "get_transcription_template")
    assert log is not None
    assert log["result"] == "success"
    assert log["access_level"] == "read"


# ---------------------------------------------------------------------------
# Backwards compat: extract_rules_from_transcript still uses RULE_TEMPLATE
# ---------------------------------------------------------------------------


def test_extract_rules_from_transcript_template_backward_compat(tmp_server_db, monkeypatch) -> None:
    from meridian.tools.knowledge_templates import RULE_TEMPLATE

    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    result = server.extract_rules_from_transcript(
        text="We discussed a new rule about timeouts.",
        project_id="project-project-example",
    )
    parsed = json.loads(result)
    assert parsed["template"] == RULE_TEMPLATE
