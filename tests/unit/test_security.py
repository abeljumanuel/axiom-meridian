"""Unit tests for security utilities."""

import getpass
import json

import pytest

from meridian.utils.security import (
    TOOL_ACCESS_LEVELS,
    AccessDeniedError,
    check_access,
    extract_safe_params,
    generate_session_token,
    get_access_level,
    get_mode,
    resolve_actor,
    validate_session_token,
)


# --- get_access_level ---


def test_get_access_level_default(monkeypatch):
    monkeypatch.delenv("MERIDIAN_ACCESS_LEVEL", raising=False)
    assert get_access_level() == "analyze"


def test_get_access_level_read(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    assert get_access_level() == "read"


def test_get_access_level_invalid(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "admin")
    with pytest.raises(ValueError, match="Invalid MERIDIAN_ACCESS_LEVEL"):
        get_access_level()


# --- check_access ---


def test_check_access_read_allows_query(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    check_access("query_rules")


def test_check_access_read_denies_approve(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "read")
    with pytest.raises(AccessDeniedError):
        check_access("approve_proposal")


def test_check_access_write_allows_all(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "write")
    check_access("approve_proposal")


def test_check_access_analyze_allows_audit(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    check_access("audit_pr")


def test_check_access_analyze_denies_write(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "analyze")
    with pytest.raises(AccessDeniedError):
        check_access("generate_embeddings")


def test_check_access_hierarchy_inclusion(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", "write")
    check_access("query_rules")
    check_access("audit_pr")
    check_access("approve_proposal")


# --- extract_safe_params ---


def test_extract_safe_params_strips_sensitive():
    kwargs = {"pr_diff": "sensitive", "project_id": "proj-123"}
    result = extract_safe_params(kwargs)
    parsed = json.loads(result)
    assert "pr_diff" not in parsed
    assert parsed["project_id"] == "proj-123"


def test_extract_safe_params_truncates_long():
    kwargs = {"description": "x" * 500}
    result = extract_safe_params(kwargs)
    parsed = json.loads(result)
    assert parsed["description"].endswith("...[truncated]")
    assert len(parsed["description"]) == 200 + len("...[truncated]")


# --- session token ---


def test_generate_session_token_unique():
    t1 = generate_session_token()
    t2 = generate_session_token()
    assert t1 != t2


def test_validate_session_token_correct():
    token = generate_session_token()
    assert validate_session_token(token, token) is True


def test_validate_session_token_wrong():
    assert validate_session_token("wrong", "expected") is False


def test_validate_session_token_none():
    assert validate_session_token(None, "expected") is False


# --- AccessDeniedError ---


def test_access_denied_error_message():
    err = AccessDeniedError("approve_proposal", "write", "read")
    msg = str(err)
    assert "approve_proposal" in msg
    assert "write" in msg
    assert "read" in msg


# --- get_mode ---


def test_get_mode_default(monkeypatch):
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    assert get_mode() == "local"


def test_get_mode_explicit_local(monkeypatch):
    monkeypatch.setenv("MERIDIAN_MODE", "local")
    assert get_mode() == "local"


def test_get_mode_shared(monkeypatch):
    monkeypatch.setenv("MERIDIAN_MODE", "shared")
    assert get_mode() == "shared"


def test_get_mode_invalid(monkeypatch):
    monkeypatch.setenv("MERIDIAN_MODE", "networked")
    with pytest.raises(ValueError, match="Invalid MERIDIAN_MODE"):
        get_mode()


# --- resolve_actor ---


def test_resolve_actor_default_mode_returns_os_user(monkeypatch):
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    assert resolve_actor() == getpass.getuser()


def test_resolve_actor_explicit_local_mode_matches_unset(monkeypatch):
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    unset_value = resolve_actor()
    monkeypatch.setenv("MERIDIAN_MODE", "local")
    assert resolve_actor() == unset_value


def test_resolve_actor_falls_back_when_getuser_raises(monkeypatch):
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    monkeypatch.setattr(
        "meridian.utils.security.getpass.getuser",
        lambda: (_ for _ in ()).throw(OSError("no password entry")),
    )
    assert resolve_actor() == "unknown-local-user"


def test_resolve_actor_shared_mode_not_implemented(monkeypatch):
    monkeypatch.setenv("MERIDIAN_MODE", "shared")
    with pytest.raises(NotImplementedError, match="MERIDIAN_MODE|shared"):
        resolve_actor()


# --- resolve_actor/get_mode are decoupled from check_access (local-user non-regression) ---


def test_check_access_unaffected_by_mode(monkeypatch):
    """check_access's allow/deny result must not depend on MERIDIAN_MODE or
    the resolved actor — attribution and authorization are fully decoupled
    (openspec/changes/add-actor-identity-tracking)."""
    for access_level in ("read", "analyze", "write"):
        monkeypatch.setenv("MERIDIAN_ACCESS_LEVEL", access_level)
        for tool_name in TOOL_ACCESS_LEVELS:
            monkeypatch.delenv("MERIDIAN_MODE", raising=False)
            result_unset = _try_check_access(tool_name)

            monkeypatch.setenv("MERIDIAN_MODE", "local")
            result_local = _try_check_access(tool_name)

            assert result_unset == result_local


def _try_check_access(tool_name: str) -> bool:
    """True if allowed, False if AccessDeniedError was raised."""
    try:
        check_access(tool_name)
        return True
    except AccessDeniedError:
        return False
