"""Contract tests — verify every registered MCP tool matches PRD section 5 signatures."""

from __future__ import annotations

import inspect
import typing
from typing import Any

import pytest

from meridian import server
from meridian.utils.security import TOOL_ACCESS_LEVELS

# Expected signatures per PRD v1.3 section 5
EXPECTED: dict[str, dict[str, Any]] = {
    # Knowledge Management
    "index_rules_from_markdown": {
        "filepath": (str, inspect.Parameter.empty),
        "default_scope_id": (str, inspect.Parameter.empty),
        "mode": (str, "atomic"),
    },
    "index_lessons_from_markdown": {
        "filepath": (str, inspect.Parameter.empty),
        "default_scope_id": (str, inspect.Parameter.empty),
        "mode": (str, "atomic"),
    },
    "convert_to_atomic_format": {
        "filepath": (str, inspect.Parameter.empty),
        "default_scope_id": (str, inspect.Parameter.empty),
        "doc_type": (str, inspect.Parameter.empty),
    },
    "list_pending_proposals": {
        "project_id": (str | None, None),
        "type": (str | None, None),
        "status": (str | None, None),
    },
    "approve_proposal": {
        "proposal_id": (str, inspect.Parameter.empty),
    },
    "edit_proposal": {
        "proposal_id": (str, inspect.Parameter.empty),
        "new_text": (str, inspect.Parameter.empty),
        "metadata": (str | None, None),
    },
    "reject_proposal": {
        "proposal_id": (str, inspect.Parameter.empty),
        "reason": (str | None, None),
    },
    "create_project": {
        "project_id": (str, inspect.Parameter.empty),
        "name": (str | None, None),
        "parent_scope": (str, "global"),
    },
    "promote_rule": {
        "rule_id": (str, inspect.Parameter.empty),
        "new_scope_id": (str, inspect.Parameter.empty),
    },
    "generate_embeddings": {
        "scope_id": (str | None, None),
    },
    "generate_project_skills": {
        "project_id": (str, inspect.Parameter.empty),
        "project_path": (str | None, None),
    },
    # Knowledge Consumption
    "query_rules": {
        "project_id": (str, inspect.Parameter.empty),
        "category": (str | None, None),
        "severity": (str | None, None),
        "tags": (str | None, None),
        "query_text": (str | None, None),
        "format": (str, "json"),
        "detail": (str, "summary"),
    },
    "query_lessons": {
        "project_id": (str, inspect.Parameter.empty),
        "area": (str | None, None),
        "tags": (str | None, None),
        "query_text": (str | None, None),
        "format": (str, "json"),
        "detail": (str, "summary"),
    },
    "get_rule_context": {
        "rule_id": (str, inspect.Parameter.empty),
    },
    "get_rule_timeline": {
        "rule_id": (str, inspect.Parameter.empty),
    },
    "get_project_scope_resolution": {
        "project_id": (str, inspect.Parameter.empty),
    },
    "get_server_info": {},
    "get_rule_audit_log": {
        "project_id": (str | None, None),
        "scope_id": (str | None, None),
        "since": (str | None, None),
    },
    # Audit Flows
    "audit_pr": {
        "pr_diff": (str, inspect.Parameter.empty),
        "project_id": (str, inspect.Parameter.empty),
    },
    "analyze_pr_feedback": {
        "feedback_text": (str, inspect.Parameter.empty),
        "pr_ref": (str, inspect.Parameter.empty),
        "project_id": (str, inspect.Parameter.empty),
    },
    "check_feature_against_rules": {
        "feature_description": (str, inspect.Parameter.empty),
        "project_id": (str, inspect.Parameter.empty),
    },
    # Extraction
    "extract_rules_from_transcript": {
        "text": (str, inspect.Parameter.empty),
        "project_id": (str, inspect.Parameter.empty),
    },
    "extract_lessons_from_transcript": {
        "text": (str, inspect.Parameter.empty),
        "project_id": (str, inspect.Parameter.empty),
    },
    "create_pending_proposal": {
        "type": (str, inspect.Parameter.empty),
        "proposed_text": (str, inspect.Parameter.empty),
        "suggested_scope_id": (str, inspect.Parameter.empty),
        "target_id": (str | None, None),
        "target_type": (str | None, None),
        "suggested_attributes": (str | None, None),
        "source_type": (str | None, None),
        "source_ref": (str | None, None),
    },
    # Knowledge Templates
    "get_rule_template": {
        "project_id": (str | None, None),
    },
    "get_lesson_template": {
        "project_id": (str | None, None),
    },
    "get_transcription_template": {
        "project_id": (str | None, None),
    },
}


def _param_type_matches(actual_annotation: Any, expected_type: Any) -> bool:
    """Compare parameter annotations, handling typing.Union vs `|` syntax."""
    # Normalise both to their string representation for comparison
    # This handles PEP 563 string annotations as well as runtime type objects
    actual_str = str(actual_annotation).replace("typing.", "")
    expected_str = str(expected_type).replace("typing.", "")
    return actual_str == expected_str


def _default_matches(actual_default: Any, expected_default: Any) -> bool:
    """Compare default values, treating inspect.Parameter.empty specially."""
    if expected_default is inspect.Parameter.empty:
        return actual_default is inspect.Parameter.empty
    return actual_default == expected_default


@pytest.mark.parametrize("tool_name", list(EXPECTED.keys()))
def test_tool_exists(tool_name: str) -> None:
    assert hasattr(server, tool_name), f"Tool {tool_name} not found in server module"


@pytest.mark.parametrize("tool_name,expected", EXPECTED.items())
def test_tool_signature(tool_name: str, expected: dict[str, Any]) -> None:
    func = getattr(server, tool_name)
    sig = inspect.signature(func)
    hints = typing.get_type_hints(func)

    # Exclude 'self' or 'cls' if present (not expected in module-level functions)
    params = list(sig.parameters.values())
    param_names = {p.name for p in params}
    expected_names = set(expected.keys())

    assert param_names == expected_names, (
        f"{tool_name}: parameter names mismatch. Expected {expected_names}, got {param_names}"
    )

    for p in params:
        exp_type, exp_default = expected[p.name]
        actual_type = hints.get(p.name, p.annotation)
        assert _param_type_matches(actual_type, exp_type), (
            f"{tool_name}.{p.name}: type mismatch. Expected {exp_type}, got {actual_type}"
        )
        assert _default_matches(p.default, exp_default), (
            f"{tool_name}.{p.name}: default mismatch. Expected {exp_default!r}, got {p.default!r}"
        )


def test_all_tools_registered() -> None:
    """Every expected tool must be decorated with @mcp.tool()."""
    import asyncio

    async def _list() -> list[str]:
        tools = await server.mcp.list_tools()
        return [t.name for t in tools]

    registered = asyncio.run(_list())
    for name in EXPECTED:
        assert name in registered, f"Tool {name} is not registered with FastMCP"


def test_every_registered_tool_has_an_access_level() -> None:
    """Regression for the create_project gap (RN-GLOBAL-033): a tool absent
    from TOOL_ACCESS_LEVELS is silently allowed at any access level —
    check_access() treats an unmapped name as forward-compatible, not denied
    (utils/security.py). Every tool covered by the signature contract must
    also appear in the access-level map, or it runs ungated."""
    missing = set(EXPECTED) - set(TOOL_ACCESS_LEVELS)
    assert not missing, f"Tools with no TOOL_ACCESS_LEVELS entry (run ungated): {missing}"


def test_no_extra_tools_registered() -> None:
    """Only expected tools should be registered (no stale / debug tools)."""
    import asyncio

    async def _list() -> list[str]:
        tools = await server.mcp.list_tools()
        return [t.name for t in tools]

    registered = set(asyncio.run(_list()))
    expected_set = set(EXPECTED.keys())
    assert registered == expected_set, (
        f"Registered tools mismatch. "
        f"Extra: {registered - expected_set}, "
        f"Missing: {expected_set - registered}"
    )


def test_every_tool_and_parameter_is_documented() -> None:
    """Regression for the 2026-09-22 Inspector finding: 25 of 26 tools had
    description=None because @mcp.tool() reads the docstring of the
    decorated wrapper in server.py, not of the implementation it delegates
    to in tools/*.py — wrappers had no docstring of their own, and their
    parameters had no Field(description=...) either, so a human using MCP
    Inspector saw only a name, a type, and a required/optional flag per
    parameter. This must never regress silently for a newly added tool or
    parameter."""
    import asyncio

    async def _list():
        return await server.mcp.list_tools()

    tools = asyncio.run(_list())
    assert tools, "No tools registered — check server.py imports"

    undocumented_tools = [t.name for t in tools if not (t.description or "").strip()]
    assert not undocumented_tools, f"Tools with no description: {undocumented_tools}"

    undocumented_params: dict[str, list[str]] = {}
    for t in tools:
        properties = (t.parameters or {}).get("properties", {})
        missing = [name for name, schema in properties.items() if not schema.get("description")]
        if missing:
            undocumented_params[t.name] = missing
    assert not undocumented_params, f"Tool parameters with no description: {undocumented_params}"
