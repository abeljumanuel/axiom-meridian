"""Extraction tools — transcript analysis and pending proposal creation."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from meridian.tools.knowledge_consumption import query_lessons, query_rules
from meridian.tools.knowledge_templates import (
    LESSON_TEMPLATE as _LESSON_TEMPLATE,
    RULE_TEMPLATE as _RULE_TEMPLATE,
)
from meridian.utils.id_generator import next_sequential_id
from meridian.utils.privacy import strip_private_tags
from meridian.utils.scope_resolver import load_scope_attributes, resolve_scope_hierarchy


def extract_rules_from_transcript(
    conn: sqlite3.Connection, text: str, project_id: str
) -> dict[str, Any]:
    """Return structured context for the client LLM to extract rules from a transcript.

    - Clean text (private tags stripped)
    - Available scopes with attributes
    - Existing rules for duplicate detection
    - Canonical atomic format template
    """
    clean_text = strip_private_tags(text)

    scopes = resolve_scope_hierarchy(conn, project_id)
    scope_data: list[dict[str, Any]] = []
    for scope in scopes:
        attrs = load_scope_attributes(conn, scope)
        scope_data.append({"scope_id": scope, "attributes": attrs})

    existing_rules = json.loads(query_rules(project_id, detail="summary"))

    return {
        "clean_text": clean_text,
        "scopes": scope_data,
        "existing_rules": existing_rules,
        "template": _RULE_TEMPLATE,
        "instruction_for_client": (
            "Analyze the transcript and identify candidate rules. "
            "For each candidate, call create_pending_proposal with type='rule'."
        ),
    }


def extract_lessons_from_transcript(
    conn: sqlite3.Connection, text: str, project_id: str
) -> dict[str, Any]:
    """Return structured context for the client LLM to extract lessons from a transcript.

    - Clean text (private tags stripped)
    - Available scopes with attributes
    - Existing lessons for duplicate detection
    - Canonical atomic format template
    """
    clean_text = strip_private_tags(text)

    scopes = resolve_scope_hierarchy(conn, project_id)
    scope_data: list[dict[str, Any]] = []
    for scope in scopes:
        attrs = load_scope_attributes(conn, scope)
        scope_data.append({"scope_id": scope, "attributes": attrs})

    existing_lessons = json.loads(query_lessons(project_id, detail="summary"))

    return {
        "clean_text": clean_text,
        "scopes": scope_data,
        "existing_lessons": existing_lessons,
        "template": _LESSON_TEMPLATE,
        "instruction_for_client": (
            "Analyze the transcript and identify candidate lessons learned. "
            "For each candidate, call create_pending_proposal with type='lesson'."
        ),
    }


def create_pending_proposal(
    conn: sqlite3.Connection,
    type: str,
    proposed_text: str,
    suggested_scope_id: str,
    suggested_attributes: list[dict[str, str]] | None = None,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> str:
    """Validate and persist a pending proposal.

    1. Validates that suggested_scope_id exists in scopes.
    2. Sanitizes proposed_text via strip_private_tags (Layer 2 guarantee).
    3. Generates a sequential ID and inserts into pending_proposals.
    4. Returns the proposal ID.
    """
    cursor = conn.execute("SELECT 1 FROM scopes WHERE id = ?", (suggested_scope_id,))
    if cursor.fetchone() is None:
        raise ValueError(
            f"Scope '{suggested_scope_id}' does not exist. "
            "Verify the scope_id before submitting the proposal."
        )

    clean_text = strip_private_tags(proposed_text)
    prop_id = next_sequential_id(conn, "pending_proposals", "prop")

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text,
         suggested_attributes, source_type, source_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            type,
            suggested_scope_id,
            clean_text,
            json.dumps(suggested_attributes) if suggested_attributes else None,
            source_type,
            source_ref,
        ),
    )
    conn.commit()

    return prop_id
