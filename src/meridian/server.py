"""FastMCP server — tool registration, security, stdio + HTTP/SSE transports."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

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
    c.commit()
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
def index_rules_from_markdown(
    filepath: Annotated[str, Field(description="Path to the source .md file containing rule blocks.")],
    default_scope_id: Annotated[
        str,
        Field(
            description="Scope assigned to blocks that don't declare their own "
            "**Scope:** field (e.g. 'global-java', 'project-<id>')."
        ),
    ],
    mode: Annotated[
        str,
        Field(
            description="'atomic': parse canonical ## RN-XXX-NNN blocks (the {TECH} "
            "segment is optional — plain ## RN-NNN is also accepted) and upsert "
            "them directly into rules/rule_history. 'legacy': parse old ### blocks "
            "into pending_proposals only, never writing to rules directly."
        ),
    ] = "atomic",
) -> str:
    """Index rules from a markdown file directly into SQLite.

    `mode="atomic"` upserts canonical blocks by code (existing rules are
    updated in place, new ones created). `mode="legacy"` stages each old-style
    block as a pending_proposals entry instead of writing to `rules` directly.

    Access level: write.
    Returns: JSON with indexed/created/updated counts, a per-scope breakdown,
    and any parser warnings or errors.
    """
    tool_name = "index_rules_from_markdown"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "mode": mode}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.index_rules_from_markdown(filepath, default_scope_id, mode)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def index_lessons_from_markdown(
    filepath: Annotated[str, Field(description="Path to the source .md file containing lesson blocks.")],
    default_scope_id: Annotated[
        str,
        Field(
            description="Scope assigned to blocks that don't declare their own "
            "**Scope:** field (e.g. 'global-java', 'project-<id>')."
        ),
    ],
    mode: Annotated[
        str,
        Field(
            description="'atomic': parse canonical ## LL-XXX-NNN blocks (the {TECH} "
            "segment is optional — plain ## LL-NNN is also accepted) and upsert "
            "them directly into lessons/lesson_history. 'legacy': parse old ### "
            "blocks into pending_proposals only, never writing to lessons directly."
        ),
    ] = "atomic",
) -> str:
    """Index lessons from a markdown file directly into SQLite.

    Same logic as `index_rules_from_markdown` but targets the `lessons` table.

    Access level: write.
    Returns: JSON with indexed/created/updated counts, a per-scope breakdown,
    and any parser warnings or errors.
    """
    tool_name = "index_lessons_from_markdown"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "mode": mode}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.index_lessons_from_markdown(filepath, default_scope_id, mode)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def convert_to_atomic_format(
    filepath: Annotated[str, Field(description="Path to the legacy (### -style) markdown file to convert.")],
    default_scope_id: Annotated[
        str,
        Field(
            description="Fallback scope used when scope inference from the block's "
            "text doesn't match a known technology keyword."
        ),
    ],
    doc_type: Annotated[str, Field(description="'rules' or 'lessons' — which legacy parser and destination to use.")],
) -> str:
    """Convert a legacy markdown file into atomic-format pending_proposals,
    one per legacy block, with best-effort scope inference from each block's
    text. Never writes .md files directly — always stages for human review
    via `approve_proposal`.

    Access level: write.
    Returns: JSON with the number of proposals created and their id/type/
    scope_id/suggested_file.
    """
    tool_name = "convert_to_atomic_format"
    params = {"filepath": filepath, "default_scope_id": default_scope_id, "doc_type": doc_type}
    project_id = _project_id_from_scope(default_scope_id)

    def _impl() -> dict:
        return knowledge_management.convert_to_atomic_format(filepath, default_scope_id, doc_type)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def list_pending_proposals(
    project_id: Annotated[
        str | None, Field(description="Filter by project/scope id (with or without the 'project-' prefix).")
    ] = None,
    type: Annotated[str | None, Field(description="Filter by proposal type: 'rule', 'lesson', or 'update'.")] = None,
    status: Annotated[
        str | None, Field(description="Filter by status: 'pending', 'approved', or 'rejected'.")
    ] = None,
) -> str:
    """List pending proposals for human review, optionally filtered by
    project, type, or status.

    Access level: read.
    Returns: JSON array of matching pending_proposals rows.
    """
    tool_name = "list_pending_proposals"
    params = {"project_id": project_id, "type": type, "status": status}

    def _impl() -> list[dict]:
        return knowledge_management.list_pending_proposals(project_id, type, status)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def approve_proposal(
    proposal_id: Annotated[str, Field(description="The pending_proposals id to approve.")],
) -> str:
    """Approve a pending proposal. For type='rule'/'lesson' this assigns a
    new RN-/LL- code, appends the atomic block to the scope's .md file, and
    inserts the corresponding row; for type='update' it splices the target's
    existing block in place instead. This is the single choke point that
    writes proposal content into both the .md file and SQLite together.

    Access level: write.
    Returns: JSON with the resulting code, scope_id, and file location
    (file_path/file_offset/byte_length).
    """
    tool_name = "approve_proposal"
    params = {"proposal_id": proposal_id}
    # project_id unknown until we read the proposal; log without it
    project_id: str | None = None

    def _impl() -> dict:
        return knowledge_management.approve_proposal(proposal_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def edit_proposal(
    proposal_id: Annotated[str, Field(description="The pending_proposals id to edit.")],
    new_text: Annotated[str, Field(description="Replacement proposed_text (private tags are stripped before storage).")],
    metadata: Annotated[
        str | None, Field(description="JSON object merged into the proposal's existing metadata.")
    ] = None,
) -> str:
    """Update the proposed_text and/or metadata of a still-pending proposal;
    its status stays 'pending'.

    Access level: write.
    Returns: JSON with the proposal_id and its status.
    """
    tool_name = "edit_proposal"
    params = {"proposal_id": proposal_id, "new_text": new_text, "metadata": metadata}
    project_id = None

    def _impl() -> dict:
        meta_dict = json.loads(metadata) if metadata else None
        return knowledge_management.edit_proposal(proposal_id, new_text, meta_dict)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def reject_proposal(
    proposal_id: Annotated[str, Field(description="The pending_proposals id to reject.")],
    reason: Annotated[str | None, Field(description="Optional human-readable rejection reason.")] = None,
) -> str:
    """Reject a pending proposal. No side effects besides updating the record.

    Access level: write.
    Returns: JSON with the proposal_id and its status.
    """
    tool_name = "reject_proposal"
    params = {"proposal_id": proposal_id, "reason": reason}
    project_id = None

    def _impl() -> dict:
        return knowledge_management.reject_proposal(proposal_id, reason)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def promote_rule(
    rule_id: Annotated[str, Field(description="The RN-* id of the rule to promote.")],
    new_scope_id: Annotated[str, Field(description="Destination scope to promote the rule into.")],
) -> str:
    """Promote a rule to a more general scope: marks the original as
    deprecated (in both SQLite and its source .md file) and records a
    PROMOTED rule_history entry. Does not create the rule in the new scope —
    that requires a separate proposal.

    Access level: write.
    Returns: JSON with the rule_id, new_scope_id, and resulting status.
    """
    tool_name = "promote_rule"
    params = {"rule_id": rule_id, "new_scope_id": new_scope_id}
    project_id = _project_id_from_scope(new_scope_id)

    def _impl() -> dict:
        return knowledge_management.promote_rule(rule_id, new_scope_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def create_project(
    project_id: Annotated[str, Field(description="New project identifier (the tool creates scope 'project-<id>').")],
    name: Annotated[str | None, Field(description="Human-readable project name; defaults to project_id.")] = None,
    parent_scope: Annotated[
        str, Field(description="Existing scope this project inherits from in the scope hierarchy.")
    ] = "global",
) -> str:
    """Create a new project scope and its knowledge base directories: a
    'project-<id>' scope under parent_scope, plus knowledge-base/projects/
    and lessons/projects/ directories with a placeholder rules .md file.

    Access level: write.
    Returns: JSON with the new scope_id, name, parent_scope, and created
    file_path.
    """
    tool_name = "create_project"
    params = {"project_id": project_id, "name": name, "parent_scope": parent_scope}
    project_id_from_scope = project_id

    def _impl() -> dict:
        return knowledge_management.create_project(
            _get_conn(),
            project_id,
            name=name,
            parent_scope=parent_scope,
        )

    return _security_pattern(tool_name, params, project_id_from_scope, _impl)


@mcp.tool()
def generate_embeddings(
    scope_id: Annotated[
        str | None, Field(description="Restrict to one scope; omit to process every scope.")
    ] = None,
) -> str:
    """Generate or update ChromaDB embeddings for active rules/lessons whose
    embedding_id is still NULL — an incremental backfill, not a full re-embed.

    Access level: write.
    Returns: JSON with processed/skipped/errors counts and duration_seconds.
    """
    tool_name = "generate_embeddings"
    params = {"scope_id": scope_id}
    project_id = _project_id_from_scope(scope_id)

    def _impl() -> dict:
        return knowledge_management.generate_embeddings(_get_conn(), scope_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def generate_project_skills(
    project_id: Annotated[str, Field(description="Project scope to generate skill files for.")],
    project_path: Annotated[
        str | None,
        Field(description="Filesystem path to the target project; falls back to MERIDIAN_PROJECT_PATH if omitted."),
    ] = None,
) -> str:
    """Generate a Claude Code skill for a project from its resolved rules:
    writes .claude/skills/meridian/<project_id>/SKILL.md and
    references/rules.md under project_path, and updates its AGENTS.md.

    Access level: write.
    Returns: JSON mapping "skill_md"/"rules_md"/"agents_md" to their written
    file paths.
    """
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
    project_id: Annotated[str, Field(description="Project id (with or without the 'project-' prefix).")],
    category: Annotated[
        str | None, Field(description="Filter by rule category, e.g. 'quality', 'security', 'architecture'.")
    ] = None,
    severity: Annotated[str | None, Field(description="Filter by severity: 'low' | 'medium' | 'high' | 'critical'.")] = None,
    tags: Annotated[
        str | None, Field(description="Comma-separated tags; matched by exact tag equality, not substring.")
    ] = None,
    query_text: Annotated[
        str | None,
        Field(
            description="Free-text query. When set and ChromaDB has embeddings, "
            "enables semantic (RAG) search instead of plain SQL filtering."
        ),
    ] = None,
    format: Annotated[str, Field(description="Output format: 'json' or 'toon' (compact tabular).")] = "json",
    detail: Annotated[
        str,
        Field(
            description="'summary': metadata only. 'full': also includes rule text "
            "(may return STALE_INDEX per row if its source file changed since indexing)."
        ),
    ] = "summary",
) -> str:
    """Query active rules visible to a project across its full scope
    hierarchy (most-specific scope first), via plain SQL filtering or —
    when query_text is set and embeddings exist — semantic search.

    Access level: read.
    Returns: a JSON or TOON array of matching rules.
    """
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
    project_id: Annotated[str, Field(description="Project id (with or without the 'project-' prefix).")],
    area: Annotated[
        str | None, Field(description="Filter by area_affected, e.g. 'deployment', 'performance', 'security'.")
    ] = None,
    tags: Annotated[
        str | None, Field(description="Comma-separated tags; matched by exact tag equality, not substring.")
    ] = None,
    query_text: Annotated[
        str | None,
        Field(
            description="Free-text query. When set and ChromaDB has embeddings, "
            "enables semantic (RAG) search instead of plain SQL filtering."
        ),
    ] = None,
    format: Annotated[str, Field(description="Output format: 'json' or 'toon' (compact tabular).")] = "json",
    detail: Annotated[
        str,
        Field(
            description="'summary': metadata only. 'full': also includes what_happened "
            "text (may return STALE_INDEX per row if its source file changed since indexing)."
        ),
    ] = "summary",
) -> str:
    """Query active lessons visible to a project across its full scope
    hierarchy (most-specific scope first), via plain SQL filtering or —
    when query_text is set and embeddings exist — semantic search.

    Access level: read.
    Returns: a JSON or TOON array of matching lessons.
    """
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
def get_rule_context(rule_id: Annotated[str, Field(description="The RN-* id of the rule.")]) -> str:
    """Return a rule's full text, its complete rule_history, and any lessons
    linked to it.

    Access level: read.
    Returns: JSON with `rule`, `history`, and `linked_lessons`.
    """
    tool_name = "get_rule_context"
    params = {"rule_id": rule_id}
    project_id = None

    def _impl() -> dict:
        return knowledge_consumption.get_rule_context(rule_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_rule_timeline(rule_id: Annotated[str, Field(description="The RN-* id of the rule.")]) -> str:
    """Return a rule's chronological history and linked-lesson summary
    without loading full text — lighter than get_rule_context.

    Access level: read.
    Returns: JSON with rule_code, scope, severity, category, history_events,
    and linked_lessons_summary.
    """
    tool_name = "get_rule_timeline"
    params = {"rule_id": rule_id}
    project_id = None

    def _impl() -> dict:
        return knowledge_consumption.get_rule_timeline(rule_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_project_scope_resolution(
    project_id: Annotated[str, Field(description="Project id (with or without the 'project-' prefix).")],
) -> str:
    """Resolve and cache a project's effective scope chain (most-specific
    first) with each scope's dynamic attributes (ADR-002).

    Access level: read.
    Returns: JSON with project_id and the resolved `scopes` list (each with
    its attributes).
    """
    tool_name = "get_project_scope_resolution"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_consumption.get_project_scope_resolution(project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_rule_audit_log(
    project_id: Annotated[str | None, Field(description="Project id to scope the log to (checked before scope_id).")] = None,
    scope_id: Annotated[str | None, Field(description="Raw scope id to scope the log to, if project_id is omitted.")] = None,
    since: Annotated[
        str | None, Field(description="ISO-8601 timestamp; only include events at or after this time.")
    ] = None,
) -> str:
    """Return the chronology of rule_history changes for a project or scope,
    plus any rules currently deprecated in that scope.

    Access level: read.
    Returns: JSON with `events` and `deprecated_rules`.
    """
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
def audit_pr(
    pr_diff: Annotated[str, Field(description="The PR's unified diff text.")],
    project_id: Annotated[str, Field(description="Project id whose active rules/lessons to audit against.")],
) -> str:
    """Audit a PR diff against a project's active rules and lessons
    (detail="full"): persists an audit record (SHA-256 diff hash + a
    snapshot of the rule versions evaluated) and returns the diff plus
    rules/lessons for the calling LLM to classify.

    Access level: analyze.
    Returns: JSON with audit_id, pr_diff, rules, lessons, and an
    instruction_for_client.
    """
    tool_name = "audit_pr"
    params = {"pr_diff": pr_diff, "project_id": project_id}

    def _impl() -> dict:
        return audit_flows.audit_pr(_get_conn(), pr_diff, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def analyze_pr_feedback(
    feedback_text: Annotated[str, Field(description="Free-text PR review feedback to classify.")],
    pr_ref: Annotated[str, Field(description="Reference (e.g. PR number/URL) used to find the matching audit_pr call.")],
    project_id: Annotated[str, Field(description="Project id the original audit_pr call used.")],
) -> str:
    """Link PR review feedback to the most recent audit_pr record for the
    same pr_ref/project_id, returning the rules that applied at that time
    for the calling LLM to classify each feedback point.

    Access level: analyze.
    Returns: JSON with feedback_text, rules_that_applied, pr_audit_record,
    and an instruction_for_client.
    """
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
def check_feature_against_rules(
    feature_description: Annotated[str, Field(description="Free-text description of the feature being planned.")],
    project_id: Annotated[str, Field(description="Project id whose active rules/lessons to check against.")],
) -> str:
    """Check a planned feature description against a project's active rules
    and lessons (detail="full"); persists a planning_checks record and
    returns the context for the calling LLM to flag conflicts.

    Access level: analyze.
    Returns: JSON with feature_description, rules, lessons, check_id, and an
    instruction_for_client.
    """
    tool_name = "check_feature_against_rules"
    params = {"feature_description": feature_description, "project_id": project_id}

    def _impl() -> dict:
        return audit_flows.check_feature_against_rules(_get_conn(), feature_description, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Extraction tools
# ---------------------------------------------------------------------------


@mcp.tool()
def extract_rules_from_transcript(
    text: Annotated[str, Field(description="Raw transcript text; private tags are stripped automatically.")],
    project_id: Annotated[str, Field(description="Project id used to resolve scopes and existing rules.")],
) -> str:
    """Return everything the calling LLM needs to extract candidate rules
    from a transcript: the clean text, the project's scope chain with
    attributes, existing rules for duplicate detection, and the canonical
    rule template. Does not itself create any proposal — call
    create_pending_proposal per candidate.

    Access level: analyze.
    Returns: JSON with clean_text, scopes, existing_rules, template, and an
    instruction_for_client.
    """
    tool_name = "extract_rules_from_transcript"
    params = {"text": text, "project_id": project_id}

    def _impl() -> dict:
        return extraction.extract_rules_from_transcript(_get_conn(), text, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def extract_lessons_from_transcript(
    text: Annotated[str, Field(description="Raw transcript text; private tags are stripped automatically.")],
    project_id: Annotated[str, Field(description="Project id used to resolve scopes and existing lessons.")],
) -> str:
    """Return everything the calling LLM needs to extract candidate lessons
    from a transcript: the clean text, the project's scope chain with
    attributes, existing lessons for duplicate detection, and the canonical
    lesson template. Does not itself create any proposal — call
    create_pending_proposal per candidate.

    Access level: analyze.
    Returns: JSON with clean_text, scopes, existing_lessons, template, and an
    instruction_for_client.
    """
    tool_name = "extract_lessons_from_transcript"
    params = {"text": text, "project_id": project_id}

    def _impl() -> dict:
        return extraction.extract_lessons_from_transcript(_get_conn(), text, project_id)

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def create_pending_proposal(
    type: Annotated[str, Field(description="Proposal type: 'rule', 'lesson', or 'update'.")],
    proposed_text: Annotated[
        str, Field(description="The proposed rule/lesson text (private tags are stripped before storage).")
    ],
    suggested_scope_id: Annotated[
        str,
        Field(
            description="Scope to attach the proposal to if approved. Ignored for "
            "type='update', which inherits the target's own scope."
        ),
    ],
    target_id: Annotated[
        str | None, Field(description="For type='update': the existing RN-*/LL-* id this proposal will replace.")
    ] = None,
    target_type: Annotated[
        str | None,
        Field(description="For type='update': 'rule' or 'lesson'; inferred from target_id's prefix if omitted."),
    ] = None,
    suggested_attributes: Annotated[
        str | None,
        Field(description='JSON array of {"key": ..., "value": ...} dynamic attributes (ADR-002) to attach if approved.'),
    ] = None,
    source_type: Annotated[str | None, Field(description="Provenance type, e.g. 'transcript' or 'manual'.")] = None,
    source_ref: Annotated[str | None, Field(description="Provenance reference, e.g. a meeting id or PR link.")] = None,
) -> str:
    """Validate and persist a pending proposal of type 'rule', 'lesson', or
    'update' (private tags stripped from proposed_text). For type='update',
    target_id must reference an existing RN-*/LL-* id and the proposal
    inherits that target's scope_id. Does not write to rules/lessons or any
    .md file — approve_proposal does that after human review.

    Access level: analyze.
    Returns: the new proposal's id, as a plain string.
    """
    tool_name = "create_pending_proposal"
    params = {
        "type": type,
        "proposed_text": proposed_text,
        "suggested_scope_id": suggested_scope_id,
        "target_id": target_id,
        "target_type": target_type,
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
            target_id=target_id,
            target_type=target_type,
            suggested_attributes=attrs,
            source_type=source_type,
            source_ref=source_ref,
        )

    return _security_pattern(tool_name, params, project_id, _impl)


# ---------------------------------------------------------------------------
# Knowledge Templates tools (read-only)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_rule_template(
    project_id: Annotated[
        str | None, Field(description="If given, also returns recommended scope_suggestions for this project.")
    ] = None,
) -> str:
    """Return the canonical `## RN-XXX-NNN` atomic block template, its field
    descriptions, and usage instructions.

    Access level: read.
    Returns: JSON with template, fields, usage, and (if project_id given)
    scope_suggestions.
    """
    tool_name = "get_rule_template"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_templates.build_rule_template_response(project_id, _get_conn())

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_lesson_template(
    project_id: Annotated[
        str | None, Field(description="If given, also returns recommended scope_suggestions for this project.")
    ] = None,
) -> str:
    """Return the canonical `## LL-XXX-NNN` atomic block template, its field
    descriptions, and usage instructions.

    Access level: read.
    Returns: JSON with template, fields, usage, and (if project_id given)
    scope_suggestions.
    """
    tool_name = "get_lesson_template"
    params = {"project_id": project_id}

    def _impl() -> dict:
        return knowledge_templates.build_lesson_template_response(project_id, _get_conn())

    return _security_pattern(tool_name, params, project_id, _impl)


@mcp.tool()
def get_transcription_template(
    project_id: Annotated[
        str | None, Field(description="If given, also returns recommended scope_suggestions for this project.")
    ] = None,
) -> str:
    """Return the combined rule+lesson template guide and workflow
    instructions for turning a transcript into pending proposals.

    Access level: read.
    Returns: JSON with template, fields, usage, and (if project_id given)
    scope_suggestions.
    """
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
