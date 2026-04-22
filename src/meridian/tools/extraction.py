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
    target_id: str | None = None,
    target_type: str | None = None,
    suggested_attributes: list[dict[str, str]] | None = None,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> str:
    """Validate and persist a pending proposal.

    1. Validates that suggested_scope_id exists in scopes (for rule/lesson types).
    2. For UPDATE type: validates target_id exists and references an existing rule/lesson.
    3. Sanitizes proposed_text via strip_private_tags (Layer 2 guarantee).
    4. Generates a sequential ID and inserts into pending_proposals.
    5. Returns the proposal ID.
    """
    type = type.lower() if type else None
    # Validate type
    if type not in ("rule", "lesson", "update"):
        raise ValueError(
            f"Invalid proposal type: {type}. "
            "Must be 'rule', 'lesson', or 'update'."
        )

    # Handle UPDATE proposal type
    if type == "update":
        if target_id is None:
            raise ValueError(
                "target_id is required for UPDATE proposals. "
                "Specify the ID of the rule or lesson to update."
            )

        # Infer target_type from ID prefix
        if target_type is None:
            if target_id.startswith("RN-"):
                target_type = "rule"
            elif target_id.startswith("LL-"):
                target_type = "lesson"
            else:
                raise ValueError(
                    f"Invalid target_id format: {target_id}. "
                    "Must start with 'RN-' for rules or 'LL-' for lessons."
                )

        # Validate target exists
        if target_type == "rule":
            cursor = conn.execute(
                "SELECT scope_id FROM rules WHERE id = ?", (target_id,)
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(
                    f"Target rule '{target_id}' does not exist. "
                    "Verify the rule_id before submitting the UPDATE proposal."
                )
            # Use target's scope_id, not suggested_scope_id
            suggested_scope_id = row[0]
        elif target_type == "lesson":
            cursor = conn.execute(
                "SELECT scope_id FROM lessons WHERE id = ?", (target_id,)
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(
                    f"Target lesson '{target_id}' does not exist. "
                    "Verify the lesson_id before submitting the UPDATE proposal."
                )
            # Use target's scope_id, not suggested_scope_id
            suggested_scope_id = row[0]
        else:
            raise ValueError(f"Invalid target_type: {target_type}")

    else:
        # Validate scope for rule/lesson types
        cursor = conn.execute(
            "SELECT 1 FROM scopes WHERE id = ?", (suggested_scope_id,)
        )
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
        (id, type, scope_id, target_id, proposed_text,
         suggested_attributes, source_type, source_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            type,
            suggested_scope_id,
            target_id,
            clean_text,
            json.dumps(suggested_attributes) if suggested_attributes else None,
            source_type,
            source_ref,
        ),
    )
    conn.commit()

    return prop_id
