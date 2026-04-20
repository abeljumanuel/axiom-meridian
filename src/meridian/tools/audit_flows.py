"""Audit flow tools — PR audits, feedback analysis, feature planning checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from meridian.tools.knowledge_consumption import query_lessons, query_rules
from meridian.utils.id_generator import next_sequential_id


def audit_pr(
    conn: sqlite3.Connection, pr_diff: str, project_id: str
) -> dict[str, Any]:
    """Audit a PR diff against active rules and lessons.

    1. Queries rules and lessons for the project (detail="full").
    2. Computes SHA-256 hash of the diff.
    3. Persists audit record with a rule_version_snapshot.
    4. Returns structured context for the client LLM to analyse.
    """
    rules_json = query_rules(project_id, detail="full")
    lessons_json = query_lessons(project_id, detail="full")

    rules: list[dict[str, Any]] = json.loads(rules_json)
    lessons: list[dict[str, Any]] = json.loads(lessons_json)

    diff_hash = hashlib.sha256(pr_diff.encode("utf-8")).hexdigest()

    rule_version_snapshot: dict[str, Any] = {}
    for rule in rules:
        code = rule.get("code") or rule.get("id")
        rule_version_snapshot[code] = {
            "scope_id": rule.get("scope_id"),
            "severity": rule.get("severity"),
            "category": rule.get("category"),
            "status": "active",
            "text": rule.get("text"),
        }

    rules_evaluated = len(rules)
    audit_id = next_sequential_id(conn, "pr_audits", "audit")

    conn.execute(
        """
        INSERT INTO pr_audits
        (id, project_id, pr_ref, diff_hash, rules_evaluated,
         violations_found, feedback_analyzed, rule_version_snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            project_id,
            None,
            diff_hash,
            rules_evaluated,
            None,
            None,
            json.dumps(rule_version_snapshot),
        ),
    )
    conn.commit()

    return {
        "audit_id": audit_id,
        "pr_diff": pr_diff,
        "rules": rules,
        "lessons": lessons,
        "instruction_for_client": (
            "Analyze the PR diff against the provided rules and lessons. "
            "Classify any violations, gaps, or conflicts found."
        ),
    }


def analyze_pr_feedback(
    conn: sqlite3.Connection,
    feedback_text: str,
    pr_ref: str,
    project_id: str,
) -> dict[str, Any]:
    """Link PR feedback to a previous audit record.

    1. Looks up the most recent pr_audit matching pr_ref and project_id.
    2. Returns the feedback together with the audit context.
    """
    cursor = conn.execute(
        """
        SELECT * FROM pr_audits
        WHERE pr_ref = ? AND project_id = ?
        ORDER BY audited_at DESC
        LIMIT 1
        """,
        (pr_ref, project_id),
    )
    columns = [d[0] for d in cursor.description]
    row = cursor.fetchone()
    if row is None:
        raise ValueError(
            f"No pr_audit found for pr_ref={pr_ref} and project_id={project_id}"
        )

    pr_audit_record: dict[str, Any] = dict(zip(columns, row))

    rules_that_applied: list[dict[str, Any]] = []
    snapshot_raw = pr_audit_record.get("rule_version_snapshot")
    if snapshot_raw:
        try:
            snapshot = json.loads(snapshot_raw)
            rules_that_applied = list(snapshot.values())
        except json.JSONDecodeError:
            rules_that_applied = []

    return {
        "feedback_text": feedback_text,
        "rules_that_applied": rules_that_applied,
        "pr_audit_record": pr_audit_record,
        "instruction_for_client": (
            "Classify each feedback point as: RULE_VIOLATION | RULE_GAP | "
            "RULE_CONFLICT | STYLE_ONLY. Use the rules and audit context provided."
        ),
    }


def check_feature_against_rules(
    conn: sqlite3.Connection, feature_description: str, project_id: str
) -> dict[str, Any]:
    """Check a feature description against active rules and lessons.

    1. Queries rules and lessons for the project (detail="full").
    2. Persists a planning_checks record.
    3. Returns structured context for the client LLM to analyse.
    """
    rules_json = query_rules(project_id, detail="full")
    lessons_json = query_lessons(project_id, detail="full")

    rules: list[dict[str, Any]] = json.loads(rules_json)
    lessons: list[dict[str, Any]] = json.loads(lessons_json)

    check_id = next_sequential_id(conn, "planning_checks", "check")
    rules_involved = [r.get("code") or r.get("id") for r in rules]

    conn.execute(
        """
        INSERT INTO planning_checks
        (id, project_id, feature_description, conflicts_found, rules_involved)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            check_id,
            project_id,
            feature_description,
            None,
            json.dumps(rules_involved) if rules_involved else None,
        ),
    )
    conn.commit()

    return {
        "feature_description": feature_description,
        "rules": rules,
        "lessons": lessons,
        "check_id": check_id,
        "instruction_for_client": (
            "Analyze the feature description against the provided rules and lessons. "
            "Classify any hard conflicts, soft conflicts, or considerations."
        ),
    }
