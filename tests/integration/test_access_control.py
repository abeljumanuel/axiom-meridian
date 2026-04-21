"""Integration tests for access control and audit logging."""

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

    # Initialise global server connection
    old_conn = server.conn
    server.conn = get_connection(db_path)
    old_transport = server.current_transport
    server.current_transport = "stdio"

    yield server.conn

    # Restore global state
    server.conn.close()
    server.conn = old_conn
    server.current_transport = old_transport


def _last_access_logs(conn: Any, n: int = 1) -> list[dict[str, Any]]:
    """Return the last *n* access_log rows ordered by timestamp desc."""
    cursor = conn.execute(
        "SELECT * FROM access_log ORDER BY timestamp DESC LIMIT ?", (n,)
    )
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def test_read_level_allows_query(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.query_rules("project-project-example")
    parsed = json.loads(result)
    assert isinstance(parsed, list)

    logs = _last_access_logs(tmp_server_db, 1)
    assert logs[0]["tool_name"] == "query_rules"
    assert logs[0]["result"] == "success"


def test_read_level_denies_approve(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.approve_proposal("prop-0001")
    parsed = json.loads(result)
    assert parsed.get("error") == "ACCESS_DENIED"
    assert parsed.get("tool") == "approve_proposal"

    logs = _last_access_logs(tmp_server_db, 1)
    assert logs[0]["tool_name"] == "approve_proposal"
    assert logs[0]["result"] == "denied"


def test_write_level_allows_all(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "write")
    # We cannot really approve a non-existent proposal, but access check must pass
    with pytest.raises(Exception):
        server.approve_proposal("prop-0001")

    logs = _last_access_logs(tmp_server_db, 1)
    assert logs[0]["tool_name"] == "approve_proposal"
    assert logs[0]["result"] == "error"  # ValueError, not denied


def test_access_log_records_all_invocations(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "write")
    # Invoke three different tools (some may error on missing data, that's fine)
    try:
        server.query_rules("project-project-example")
    except Exception:
        pass
    try:
        server.get_project_scope_resolution("project-project-example")
    except Exception:
        pass
    try:
        server.list_pending_proposals()
    except Exception:
        pass

    logs = _last_access_logs(tmp_server_db, 3)
    tool_names = {log["tool_name"] for log in logs}
    assert "query_rules" in tool_names
    assert "get_project_scope_resolution" in tool_names
    assert "list_pending_proposals" in tool_names
    for log in logs:
        assert log["timestamp"] is not None
        assert log["result"] in ("success", "error")


def test_access_log_excludes_sensitive_params(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    result = server.audit_pr("large diff containing secrets", "project-project-example")
    parsed = json.loads(result)
    # Should succeed even though there are no rules
    assert "audit_id" in parsed or "error" in parsed

    logs = _last_access_logs(tmp_server_db, 1)
    params = json.loads(logs[0]["parameters"])
    assert "pr_diff" not in params
    assert params.get("project_id") == "project-project-example"


def test_default_level_is_analyze(tmp_server_db, monkeypatch):
    monkeypatch.delenv("MERIDIAN_ACCESS_LEVEL", raising=False)
    # analyze level allows audit_pr (analyze) but denies approve_proposal (write)
    result_audit = server.audit_pr("diff", "project-project-example")
    assert "ACCESS_DENIED" not in result_audit

    result_approve = server.approve_proposal("prop-0001")
    parsed = json.loads(result_approve)
    assert parsed.get("error") == "ACCESS_DENIED"
