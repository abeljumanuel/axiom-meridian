"""FastMCP server — tool registration, security, stdio + HTTP/SSE transports."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from meridian.config import get_db_path
from meridian.db.connection import get_connection, initialize_db
from meridian.tools import (
    audit_flows,
    extraction,
    knowledge_consumption,
    knowledge_management,
    knowledge_templates,
)
from meridian.utils.id_generator import next_sequential_id
from meridian.utils.security import (
    TOOL_ACCESS_LEVELS,
    AccessDeniedError,
    check_access,
    extract_safe_params,
    generate_session_token,
    log_tool_access,
)
from meridian.utils.skill_generator import generate_project_skills as _generate_project_skills_impl

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

mcp = FastMCP("meridian")
conn: sqlite3.Connection | None = None
current_transport: str = "stdio"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """Return the module-level DB connection (must be initialised)."""
    if conn is None:
        raise RuntimeError("Database connection not initialised. Call init_db() first.")
    return conn


def _dump(result: Any) -> str:
    """Serialise a result to a JSON string, or return directly if already a string."""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _project_id_from_scope(scope_id: str | None) -> str | None:
    """Normalise a scope_id to a project_id for logging."""
    if scope_id is None:
        return None
    if scope_id.startswith("project-"):
        return scope_id[len("project-") :]
    return scope_id


# ---------------------------------------------------------------------------
# DB lifecycle
# ---------------------------------------------------------------------------


def init_db() -> sqlite3.Connection:
    """Initialise the global DB connection and schema."""
    global conn
    db_path = get_db_path()
    initialize_db(db_path)
    conn = get_connection(db_path)
    return conn


# ---------------------------------------------------------------------------
# Security wrapper pattern (explicit — no metaclass / magic decorator)
# ---------------------------------------------------------------------------


def _security_pattern(
    tool_name: str,
    params_dict: dict[str, Any],
    project_id: str | None,
    impl_callable: Any,
) -> str:
    """Explicit security + audit pattern used by every tool handler."""
    c = _get_conn()
    log_id = next_sequential_id(c, "access_log", "al")
    params = extract_safe_params(params_dict)
    try:
        check_access(tool_name)
        result = impl_callable()
        log_tool_access(
            c,
            log_id,
            tool_name,
            TOOL_ACCESS_LEVELS[tool_name],
            project_id,
            params,
            "success",
            current_transport,
        )
        return _dump(result)
    except AccessDeniedError as e:
        log_tool_access(
            c,
            log_id,
            tool_name,
            TOOL_ACCESS_LEVELS[tool_name],
            project_id,
            params,
            "denied",
            current_transport,
        )
        return _dump(
            {
                "error": "ACCESS_DENIED",
                "tool": e.tool_name,
                "required_level": e.required,
                "current_level": e.current,
                "message": str(e),
            }
        )
    except Exception:
        log_tool_access(
            c,
            log_id,
            tool_name,
            TOOL_ACCESS_LEVELS[tool_name],
            project_id,
            params,
            "error",
            current_transport,
        )
        raise


# ---------------------------------------------------------------------------
# Knowledge Management tools
# ---------------------------------------------------------------------------


@mcp.tool()
def index_rules_from_markdown(filepath: str, default_scope_id: str, mode: str = "atomic") -> str:
    tool_name = "index_rules_from_markdown"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "mode": mode}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.index_rules_from_markdown(filepath, default_scope_id, mode)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def index_lessons_from_markdown(filepath: str, default_scope_id: str, mode: str = "atomic") -> str:
    tool_name = "index_lessons_from_markdown"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "mode": mode}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.index_lessons_from_markdown(filepath, default_scope_id, mode)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def convert_to_atomic_format(filepath: str, default_scope_id: str, doc_type: str) -> str:
    tool_name = "convert_to_atomic_format"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "doc_type": doc_type}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.convert_to_atomic_format(filepath, default_scope_id, doc_type)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def list_pending_proposals(
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
) -> str:
    tool_name = "list_pending_proposals"
    params = {"project_id": project_id, "type": type, "status": status}

    def _impl() -> list[dict]:
        return knowledge_management.list_pending_proposals(project_id, type, status)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def approve_proposal(proposal_id: str) -> str:
    tool_name = "approve_proposal"
    params = {"proposal_id": proposal_id}
    # project_id unknown until we read the proposal; log without it
    project_id: str | None = None

    def _impl() -> dict:
        return knowledge_management.approve_proposal(proposal_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def edit_proposal(proposal_id: str, new_text: str, metadata: str | None = None) -> str:
    tool_name = "edit_proposal"
    params = {"proposal_id": proposal_id, "new_text": new_text, "metadata": metadata}
    project_id = None

    def _impl() -> dict:
        meta_dict = json.loads(metadata) if metadata else None
        return knowledge_management.edit_proposal(proposal_id, new_text, meta_dict)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def reject_proposal(proposal_id: str, reason: str | None = None) -> str:
    tool_name = "reject_proposal"
    params = {"proposal_id": proposal_id, "reason": reason}
    project_id = None

    def _impl() -> dict:
        return knowledge_management.reject_proposal(proposal_id, reason)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def promote_rule(rule_id: str, new_scope_id: str) -> str:
    tool_name = "promote_rule"
    params = {"rule_id": rule_id, "new_scope_id": new_scope_id}
    project_id = _project_id_from_scope(new_scope_id)

    def _impl() -> dict:
        return knowledge_management.promote_rule(rule_id, new_scope_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def generate_embeddings(scope_id: str | None = None) -> str:
    tool_name = "generate_embeddings"
    params = {"scope_id": scope_id}
    project_id = _project_id_from_scope(scope_id)

    def _impl() -> dict:
        return knowledge_management.generate_embeddings(_get_conn(), scope_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def generate_project_skills(project_id: str, project_path: str | None = None) -> str:
    tool_name = "generate_project_skills"
    params = {"project_id": project_id, "project_path": project_path}

    def _impl() -> dict[str, str]:
        path_str = project_path or os.environ.get("MERIDIAN_PROJECT_PATH")
        if not path_str:
            raise RuntimeError("project_path is required when MERIDIAN_PROJECT_PATH is not set.")
        result = _generate_project_skills_impl(_get_conn(), project_id, Path(path_str))
        return {k: str(v) for k, v in result.items()}

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Knowledge Consumption tools
# ---------------------------------------------------------------------------


@mcp.tool()
def query_rules(
    project_id: str,
    category: str | None = None,
    severity: str | None = None,
    tags: str | None = None,
    query_text: str | None = None,
    format: str = "json",
    detail: str = "summary",
) -> str:
    tool_name = "query_rules"
    params = {
        "project_id": project_id,
        "category": category,
        "severity": severity,
        "tags": tags,
        "query_text": query_text,
        "format": format,
        "detail": detail,
    }

    def _impl() -> str:
        return knowledge_consumption.query_rules(
            project_id,
            category=category,
            severity=severity,
            tags=tags,
            query_text=query_text,
            format=format,
            detail=detail,
            conn=_get_conn(),
        )

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def query_lessons(
    project_id: str,
    area: str | None = None,
    tags: str | None = None,
    query_text: str | None = None,
    format: str = "json",
    detail: str = "summary",
) -> str:
    tool_name = "query_lessons"
    params = {
        "project_id": project_id,
        "area": area,
        "tags": tags,
        "query_text": query_text,
        "format": format,
        "detail": detail,
    }

    def _impl() -> str:
        return knowledge_consumption.query_lessons(
            project_id,
            area=area,
            tags=tags,
            query_text=query_text,
            format=format,
            detail=detail,
        )

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_rule_context(rule_id: str) -> str:
    tool_name = "get_rule_context"
    params = {"rule_id": rule_id}
    project_id = None

    def _impl() -> dict:
        return knowledge_consumption.get_rule_context(rule_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_rule_timeline(rule_id: str) -> str:
    tool_name = "get_rule_timeline"
    params = {"rule_id": rule_id}
    project_id = None

    def _impl() -> dict:
        return knowledge_consumption.get_rule_timeline(rule_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_project_scope_resolution(project_id: str) -> str:
    tool_name = "get_project_scope_resolution"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_consumption.get_project_scope_resolution(project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_rule_audit_log(
    project_id: str | None = None,
    scope_id: str | None = None,
    since: str | None = None,
) -> str:
    tool_name = "get_rule_audit_log"
    params = {"project_id": project_id, "scope_id": scope_id, "since": since}
    log_project_id = project_id or scope_id

    def _impl() -> dict:
        return knowledge_consumption.get_rule_audit_log(project_id, scope_id, since)

    return _security_pattern(tool_name, params, log_project_id, _impl)


# ---------------------------------------------------------------------------
# Audit Flows tools
# ---------------------------------------------------------------------------


@mcp.tool()
def audit_pr(pr_diff: str, project_id: str) -> str:
    tool_name = "audit_pr"
    params = {"pr_diff": pr_diff, "project_id": project_id}

    def _impl() -> dict:
        return audit_flows.audit_pr(_get_conn(), pr_diff, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def analyze_pr_feedback(feedback_text: str, pr_ref: str, project_id: str) -> str:
    tool_name = "analyze_pr_feedback"
    params = {
        "feedback_text": feedback_text,
        "pr_ref": pr_ref,
        "project_id": project_id,
    }

    def _impl() -> dict:
        return audit_flows.analyze_pr_feedback(_get_conn(), feedback_text, pr_ref, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def check_feature_against_rules(feature_description: str, project_id: str) -> str:
    tool_name = "check_feature_against_rules"
    params = {"feature_description": feature_description, "project_id": project_id}

    def _impl() -> dict:
        return audit_flows.check_feature_against_rules(_get_conn(), feature_description, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Extraction tools
# ---------------------------------------------------------------------------


@mcp.tool()
def extract_rules_from_transcript(text: str, project_id: str) -> str:
    tool_name = "extract_rules_from_transcript"
    params = {"text": text, "project_id": project_id}

    def _impl() -> dict:
        return extraction.extract_rules_from_transcript(_get_conn(), text, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def extract_lessons_from_transcript(text: str, project_id: str) -> str:
    tool_name = "extract_lessons_from_transcript"
    params = {"text": text, "project_id": project_id}

    def _impl() -> dict:
        return extraction.extract_lessons_from_transcript(_get_conn(), text, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def create_pending_proposal(
    type: str,
    proposed_text: str,
    suggested_scope_id: str,
    suggested_attributes: str | None = None,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> str:
    tool_name = "create_pending_proposal"
    params = {
        "type": type,
        "proposed_text": proposed_text,
        "suggested_scope_id": suggested_scope_id,
        "suggested_attributes": suggested_attributes,
        "source_type": source_type,
        "source_ref": source_ref,
    }
    project_id = _project_id_from_scope(suggested_scope_id)

    def _impl() -> str:
        attrs = json.loads(suggested_attributes) if suggested_attributes else None
        return extraction.create_pending_proposal(
            _get_conn(),
            type,
            proposed_text,
            suggested_scope_id,
            suggested_attributes=attrs,
            source_type=source_type,
            source_ref=source_ref,
        )

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Knowledge Templates tools (read-only)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_rule_template(project_id: str | None = None) -> str:
    tool_name = "get_rule_template"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_templates.build_rule_template_response(project_id, _get_conn())

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_lesson_template(project_id: str | None = None) -> str:
    tool_name = "get_lesson_template"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_templates.build_lesson_template_response(project_id, _get_conn())

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_transcription_template(project_id: str | None = None) -> str:
    tool_name = "get_transcription_template"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_templates.build_transcription_template_response(project_id, _get_conn())

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


def run_stdio() -> None:
    global current_transport
    current_transport = "stdio"
    init_db()
    mcp.run(transport="stdio")


def run_http(port: int = 8080) -> None:
    global current_transport
    current_transport = "http"
    init_db()

    session_token = generate_session_token()
    print(f"Meridian HTTP/SSE server started on 127.0.0.1:{port}")
    print(f"Session token: {session_token}")
    print(f"Include header: Authorization: Bearer {session_token}")

    mcp.run(transport="sse", host="127.0.0.1", port=port)
