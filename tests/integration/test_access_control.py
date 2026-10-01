"""Integration tests for access control and audit logging."""

from __future__ import annotations

import json
import shutil
import sqlite3
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


def test_create_pending_proposal_exposes_update_target(tmp_server_db, monkeypatch):
    """Regression: the MCP-exposed create_pending_proposal wrapper used to
    omit target_id/target_type, even though the underlying
    extraction.create_pending_proposal supports type="update" through them.
    No caller outside the codebase could ever reach that parameter, so every
    external type="update" call failed with "target_id is required for
    UPDATE proposals" — the update-proposal feature was unreachable via MCP.
    This exercises the actual server.py wrapper, not the internal function,
    since that's the layer the previous tests bypassed."""
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    tmp_server_db.execute(
        "INSERT INTO rules (id, scope_id, code, text, category, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("RN-GLOBAL-001", "global", "RN-GLOBAL-001", "Existing rule text.", "general", "medium"),
    )
    tmp_server_db.commit()

    proposal_id = server.create_pending_proposal(
        type="update",
        proposed_text="Updated rule text.",
        suggested_scope_id="global",
        target_id="RN-GLOBAL-001",
    )

    row = tmp_server_db.execute(
        "SELECT type, target_id, scope_id, proposed_text FROM pending_proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()
    assert row == ("update", "RN-GLOBAL-001", "global", "Updated rule text.")

    logs = _last_access_logs(tmp_server_db, 1)
    assert logs[0]["tool_name"] == "create_pending_proposal"
    assert logs[0]["result"] == "success"
    for log in logs:
        assert log["timestamp"] is not None
        assert log["result"] in ("success", "error")


def test_deprecate_rule_analyze_level_creates_visible_proposal(tmp_server_db, monkeypatch):
    """Exercises the actual server.py deprecate_rule wrapper end-to-end:
    an analyze-level credential can create the proposal, and it shows up
    through list_pending_proposals — not just via the internal
    extraction.create_pending_proposal function."""
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    tmp_server_db.execute(
        "INSERT INTO rules (id, scope_id, code, text, category, severity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("RN-GLOBAL-002", "global", "RN-GLOBAL-002", "Some rule text.", "general", "medium"),
    )
    tmp_server_db.commit()

    proposal_id = server.deprecate_rule(
        rule_id="RN-GLOBAL-002",
        reason="No longer applies",
    )

    pending = json.loads(server.list_pending_proposals())
    assert any(p["id"] == proposal_id and p["type"] == "deprecate" for p in pending)

    logs = _last_access_logs(tmp_server_db, 2)
    tool_names = {log["tool_name"] for log in logs}
    assert "deprecate_rule" in tool_names


def test_read_level_denies_deprecate_rule(tmp_server_db, monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    result = server.deprecate_rule(rule_id="RN-GLOBAL-002", reason="No longer applies")
    parsed = json.loads(result)
    assert parsed.get("error") == "ACCESS_DENIED"
    assert parsed.get("tool") == "deprecate_rule"

    logs = _last_access_logs(tmp_server_db, 1)
    assert logs[0]["tool_name"] == "deprecate_rule"
    assert logs[0]["result"] == "denied"


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


def test_access_log_records_actor_id(tmp_server_db, monkeypatch):
    """openspec/changes/add-actor-identity-tracking: every access_log row
    (success, denied, error) carries resolve_actor()'s value."""
    import getpass

    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")

    server.query_rules("project-project-example")  # success
    server.approve_proposal("prop-0001")  # denied (read level)

    logs = _last_access_logs(tmp_server_db, 2)
    for log in logs:
        assert log["actor_id"] == getpass.getuser()


def test_create_pending_proposal_records_actor_id(tmp_server_db, monkeypatch):
    import getpass

    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")

    proposal_id = server.create_pending_proposal(
        type="rule",
        proposed_text="Some proposed rule text.",
        suggested_scope_id="global",
    )

    row = tmp_server_db.execute(
        "SELECT actor_id FROM pending_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_resolve_actor_fallback_end_to_end(tmp_server_db, monkeypatch):
    """If getpass.getuser() can't resolve an OS user (design.md's flagged
    risk), a real tool call must still succeed — attribution falling back
    to a constant, not a new exception reaching the MCP client."""
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    monkeypatch.setattr(
        "meridian.utils.security.getpass.getuser",
        lambda: (_ for _ in ()).throw(OSError("no password entry")),
    )

    proposal_id = server.create_pending_proposal(
        type="rule",
        proposed_text="Some proposed rule text.",
        suggested_scope_id="global",
    )

    row = tmp_server_db.execute(
        "SELECT actor_id FROM pending_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    assert row[0] == "unknown-local-user"


def test_index_then_scope_resolution_no_lock_regression(tmp_path, monkeypatch):
    """Regression for the 2026-09-22 'database is locked' incident (ADR-006).

    _security_pattern's next_sequential_id() call used to leave an
    uncommitted write transaction open on the server's long-lived global
    connection (server.conn) while impl_callable() opened a second,
    independent connection (get_connection(get_db_path())) to write to the
    same WAL-mode database file — index_rules_from_markdown writes to
    rules/rule_history, get_project_scope_resolution writes to
    project_scope_resolution. Without the early `c.commit()` in
    _security_pattern and `busy_timeout` in get_connection, the second
    writer failed immediately with sqlite3.OperationalError: database is
    locked. Reproduces the exact reported sequence: a fresh knowledge base,
    MERIDIAN_ACCESS_LEVEL=write, index_rules_from_markdown on the real
    knowledge-base/global/java.md seed file with default_scope_id
    'global-java', followed by get_project_scope_resolution in the same
    session (same global connection, no restart in between).
    """
    kb_path = tmp_path / "kb"
    kb_path.mkdir()
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)
    java_md = kb_path / "knowledge-base" / "global" / "java.md"
    shutil.copy("knowledge-base/global/java.md", java_md)

    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "write")

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    old_conn = server.conn
    server.conn = get_connection(db_path)
    old_transport = server.current_transport
    server.current_transport = "stdio"
    try:
        try:
            index_result = json.loads(
                server.index_rules_from_markdown(str(java_md), "global-java")
            )
            scope_result = json.loads(
                server.get_project_scope_resolution("project-project-example")
            )
        except sqlite3.OperationalError as exc:
            pytest.fail(f"database lock regression reproduced: {exc}")

        assert index_result["errors"] == []
        assert index_result["created"] == 3
        assert scope_result["project_id"] == "project-project-example"
    finally:
        server.conn.close()
        server.conn = old_conn
        server.current_transport = old_transport
