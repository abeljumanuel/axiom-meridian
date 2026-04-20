"""Knowledge consumption tools — query, context, timeline, audit log."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from meridian.config import get_db_path
from meridian.db.connection import get_connection
from meridian.rag import embedder, vector_store
from meridian.utils.scope_resolver import (
    filter_by_attributes,
    load_scope_attributes,
    resolve_scope_hierarchy,
)
from meridian.utils.serializers import serialize


def _read_positional_text(
    file_path: str | None,
    file_offset: int | None,
    byte_length: int | None,
    fallback_text: str | None = None,
) -> dict[str, Any]:
    """Read text via file_offset + byte_length with STALE_INDEX detection."""
    result: dict[str, Any] = {"text": fallback_text}
    if not file_path or file_offset is None or byte_length is None:
        return result
    path = Path(file_path)
    if not path.exists():
        result["text"] = None
        result["error"] = "STALE_INDEX"
        return result
    current_size = path.stat().st_size
    if file_offset + byte_length > current_size:
        result["text"] = None
        result["error"] = "STALE_INDEX"
        return result
    raw_bytes = path.read_bytes()
    chunk = raw_bytes[file_offset : file_offset + byte_length]
    result["text"] = chunk.decode("utf-8")
    return result


def _normalize_rag_rule(candidate: dict) -> dict[str, Any]:
    """Convert a ChromaDB candidate into the same shape as a SQL row."""
    meta = candidate.get("metadata", {})
    return {
        "id": candidate["id"],
        "code": candidate["id"],
        "scope_id": meta.get("scope_id", ""),
        "severity": meta.get("severity", ""),
        "category": meta.get("category", ""),
        "applies_to": meta.get("applies_to", ""),
        "tags": meta.get("tags", "[]"),
        "text": candidate.get("text", ""),
        "file_path": None,
        "file_offset": None,
        "byte_length": None,
    }


def _apply_metadata_filters(
    candidates: list[dict],
    category: str | None,
    severity: str | None,
    tags: str | list[str] | None,
) -> list[dict]:
    """Post-filter ChromaDB candidates by explicit metadata filters."""
    results = candidates
    if category is not None:
        results = [
            c
            for c in results
            if c.get("metadata", {}).get("category") == category
        ]
    if severity is not None:
        results = [
            c
            for c in results
            if c.get("metadata", {}).get("severity") == severity
        ]
    if tags is not None:
        tag_list = [tags] if isinstance(tags, str) else tags
        filtered: list[dict] = []
        for c in results:
            meta_tags = c.get("metadata", {}).get("tags", "[]")
            if isinstance(meta_tags, str):
                try:
                    parsed = json.loads(meta_tags)
                except json.JSONDecodeError:
                    parsed = [t.strip() for t in meta_tags.split(",") if t.strip()]
                meta_tags = parsed
            if any(t in meta_tags for t in tag_list):
                filtered.append(c)
        results = filtered
    return results


def query_rules(
    project_id: str,
    category: str | None = None,
    severity: str | None = None,
    tags: str | list[str] | None = None,
    query_text: str | None = None,
    format: str = "json",
    detail: str = "summary",
    conn: sqlite3.Connection | None = None,
) -> str:
    """Query active rules for a project using SQL or RAG filtering."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        scopes = resolve_scope_hierarchy(conn, project_id)
        attributes = load_scope_attributes(conn, project_id)

        if query_text and vector_store.chromadb_available():
            query_embedding = embedder.generate_embedding(query_text)
            candidates = vector_store.search_rules(
                query_embedding, scopes, top_k=20
            )
            candidates = _apply_metadata_filters(
                candidates, category, severity, tags
            )
            results = [_normalize_rag_rule(c) for c in candidates]

            candidate_ids = [r["id"] for r in results]
            filtered_ids = filter_by_attributes(conn, candidate_ids, attributes)
            filtered_set = set(filtered_ids)
            results = [r for r in results if r["id"] in filtered_set]
        else:
            placeholders = ",".join("?" for _ in scopes)
            sql = (
                f"SELECT * FROM rules WHERE scope_id IN ({placeholders}) "
                f"AND status = 'active'"
            )
            params: list[Any] = list(scopes)

            if category is not None:
                sql += " AND category = ?"
                params.append(category)
            if severity is not None:
                sql += " AND severity = ?"
                params.append(severity)
            if tags is not None:
                if isinstance(tags, str):
                    sql += " AND tags LIKE ?"
                    params.append(f"%{tags}%")
                elif isinstance(tags, list):
                    or_clauses = " OR ".join("tags LIKE ?" for _ in tags)
                    sql += f" AND ({or_clauses})"
                    params.extend(f"%{t}%" for t in tags)

            cursor = conn.execute(sql, params)
            columns = [d[0] for d in cursor.description]
            candidates = [dict(zip(columns, row)) for row in cursor.fetchall()]

            candidate_ids = [r["id"] for r in candidates]
            filtered_ids = filter_by_attributes(conn, candidate_ids, attributes)
            filtered_set = set(filtered_ids)

            results = [r for r in candidates if r["id"] in filtered_set]

        scope_order = {s: i for i, s in enumerate(scopes)}
        results.sort(key=lambda r: scope_order.get(r["scope_id"], 999))

        summary_fields = [
            "code", "scope_id", "severity", "category", "applies_to", "tags"
        ]
        full_fields = [*summary_fields, "text"]

        if detail == "summary":
            output = [{k: r[k] for k in summary_fields} for r in results]
            return serialize(
                output, format, summary_fields if format == "toon" else None
            )

        if detail == "full":
            output: list[dict[str, Any]] = []
            for r in results:
                row: dict[str, Any] = {k: r[k] for k in summary_fields}
                pos = _read_positional_text(
                    r.get("file_path"),
                    r.get("file_offset"),
                    r.get("byte_length"),
                    fallback_text=r.get("text"),
                )
                row.update(pos)
                output.append(row)
            return serialize(
                output, format, full_fields if format == "toon" else None
            )

        raise ValueError(
            f"Unknown detail: {detail}. Valid: 'summary', 'full'"
        )
    finally:
        if close_on_exit:
            conn.close()


def _normalize_rag_lesson(candidate: dict) -> dict[str, Any]:
    """Convert a ChromaDB lesson candidate into the same shape as a SQL row."""
    meta = candidate.get("metadata", {})
    return {
        "id": candidate["id"],
        "code": candidate["id"],
        "scope_id": meta.get("scope_id", ""),
        "severity": meta.get("severity", ""),
        "area_affected": meta.get("area_affected", ""),
        "tags": meta.get("tags", "[]"),
        "text": candidate.get("text", ""),
        "what_happened": candidate.get("text", ""),
        "file_path": None,
        "file_offset": None,
        "byte_length": None,
    }


def query_lessons(
    project_id: str,
    area: str | None = None,
    tags: str | list[str] | None = None,
    query_text: str | None = None,
    format: str = "json",
    detail: str = "summary",
    conn: sqlite3.Connection | None = None,
) -> str:
    """Query active lessons for a project using SQL or RAG filtering."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        scopes = resolve_scope_hierarchy(conn, project_id)

        if query_text and vector_store.chromadb_available():
            query_embedding = embedder.generate_embedding(query_text)
            candidates = vector_store.search_lessons(
                query_embedding, scopes, top_k=20
            )
            candidates = _apply_metadata_filters(candidates, None, None, tags)
            if area is not None:
                candidates = [
                    c
                    for c in candidates
                    if c.get("metadata", {}).get("area_affected") == area
                ]
            results = [_normalize_rag_lesson(c) for c in candidates]
        else:
            placeholders = ",".join("?" for _ in scopes)
            sql = (
                f"SELECT * FROM lessons WHERE scope_id IN ({placeholders}) "
                f"AND status = 'active'"
            )
            params: list[Any] = list(scopes)

            if area is not None:
                sql += " AND area_affected = ?"
                params.append(area)
            if tags is not None:
                if isinstance(tags, str):
                    sql += " AND tags LIKE ?"
                    params.append(f"%{tags}%")
                elif isinstance(tags, list):
                    or_clauses = " OR ".join("tags LIKE ?" for _ in tags)
                    sql += f" AND ({or_clauses})"
                    params.extend(f"%{t}%" for t in tags)

            cursor = conn.execute(sql, params)
            columns = [d[0] for d in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]

        scope_order = {s: i for i, s in enumerate(scopes)}
        results.sort(key=lambda r: scope_order.get(r["scope_id"], 999))

        summary_fields = [
            "code", "scope_id", "severity", "area_affected", "tags"
        ]
        full_fields = [*summary_fields, "text"]

        if detail == "summary":
            output = [{k: r[k] for k in summary_fields} for r in results]
            return serialize(
                output, format, summary_fields if format == "toon" else None
            )

        if detail == "full":
            output: list[dict[str, Any]] = []
            for r in results:
                row: dict[str, Any] = {k: r[k] for k in summary_fields}
                pos = _read_positional_text(
                    r.get("file_path"),
                    r.get("file_offset"),
                    r.get("byte_length"),
                    fallback_text=r.get("what_happened"),
                )
                row.update(pos)
                output.append(row)
            return serialize(
                output, format, full_fields if format == "toon" else None
            )

        raise ValueError(
            f"Unknown detail: {detail}. Valid: 'summary', 'full'"
        )
    finally:
        if close_on_exit:
            conn.close()


def get_rule_timeline(
    rule_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return chronological history of a rule without loading full text."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        cursor = conn.execute(
            "SELECT code, scope_id, severity, category FROM rules WHERE id = ?",
            (rule_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Rule {rule_id} not found")

        code, scope_id, severity, category = row

        cursor = conn.execute(
            "SELECT change_type, reason, triggered_by, changed_at "
            "FROM rule_history WHERE rule_id = ? ORDER BY changed_at",
            (rule_id,),
        )
        history_events = [
            dict(
                zip(
                    ["change_type", "reason", "triggered_by", "changed_at"],
                    r,
                )
            )
            for r in cursor.fetchall()
        ]

        cursor = conn.execute(
            """
            SELECT l.code, l.area_affected, l.severity
            FROM lessons l
            JOIN rule_lesson_links rll ON l.id = rll.lesson_id
            WHERE rll.rule_id = ?
            """,
            (rule_id,),
        )
        linked_lessons_summary = [
            dict(zip(["code", "area", "severity"], r))
            for r in cursor.fetchall()
        ]

        return {
            "rule_code": code,
            "scope": scope_id,
            "severity": severity,
            "category": category,
            "history_events": history_events,
            "linked_lessons_summary": linked_lessons_summary,
        }
    finally:
        if close_on_exit:
            conn.close()


def get_rule_context(
    rule_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return full rule text + history + linked lessons."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        cursor = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Rule {rule_id} not found")

        columns = [d[0] for d in cursor.description]
        rule = dict(zip(columns, row))

        pos = _read_positional_text(
            rule.get("file_path"),
            rule.get("file_offset"),
            rule.get("byte_length"),
            fallback_text=rule.get("text"),
        )
        rule.update(pos)

        cursor = conn.execute(
            "SELECT * FROM rule_history WHERE rule_id = ? ORDER BY changed_at",
            (rule_id,),
        )
        hist_columns = [d[0] for d in cursor.description]
        history = [
            dict(zip(hist_columns, r)) for r in cursor.fetchall()
        ]

        cursor = conn.execute(
            """
            SELECT l.* FROM lessons l
            JOIN rule_lesson_links rll ON l.id = rll.lesson_id
            WHERE rll.rule_id = ?
            """,
            (rule_id,),
        )
        lesson_columns = [d[0] for d in cursor.description]
        lessons: list[dict[str, Any]] = []
        for lesson_row in cursor.fetchall():
            lesson = dict(zip(lesson_columns, lesson_row))
            pos_lesson = _read_positional_text(
                lesson.get("file_path"),
                lesson.get("file_offset"),
                lesson.get("byte_length"),
                fallback_text=lesson.get("what_happened"),
            )
            lesson.update(pos_lesson)
            lessons.append(lesson)

        return {
            "rule": rule,
            "history": history,
            "linked_lessons": lessons,
        }
    finally:
        if close_on_exit:
            conn.close()


def get_project_scope_resolution(
    project_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return effective scopes for a project with attributes."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        scopes = resolve_scope_hierarchy(conn, project_id)

        scope_data: list[dict[str, Any]] = []
        for scope in scopes:
            attrs = load_scope_attributes(conn, scope)
            scope_data.append({"scope_id": scope, "attributes": attrs})

        resolved_scopes_json = json.dumps(scopes)
        conn.execute(
            """
            INSERT INTO project_scope_resolution (project_id, resolved_scopes)
            VALUES (?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                resolved_scopes = excluded.resolved_scopes,
                updated_at = datetime('now')
            """,
            (project_id, resolved_scopes_json),
        )
        conn.commit()

        return {
            "project_id": project_id,
            "scopes": scope_data,
        }
    finally:
        if close_on_exit:
            conn.close()


def get_rule_audit_log(
    project_id: str | None = None,
    scope_id: str | None = None,
    since: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return chronology of rule changes from rule_history."""
    close_on_exit = False
    if conn is None:
        conn = get_connection(get_db_path())
        close_on_exit = True
    try:
        query = (
            "SELECT rh.*, r.code as rule_code, r.scope_id, r.status as rule_status "
            "FROM rule_history rh "
            "JOIN rules r ON rh.rule_id = r.id "
            "WHERE 1=1"
        )
        params: list[Any] = []

        target_scope = project_id or scope_id
        if target_scope is not None:
            query += " AND r.scope_id = ?"
            params.append(target_scope)

        if since is not None:
            query += " AND rh.changed_at >= ?"
            params.append(since)

        query += " ORDER BY rh.changed_at"

        cursor = conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        events = [dict(zip(columns, row)) for row in cursor.fetchall()]

        deprecated_rules: list[dict[str, Any]] = []
        if target_scope is not None:
            cursor = conn.execute(
                """
                SELECT r.*, rh.reason as deprecation_reason
                FROM rules r
                JOIN rule_history rh ON r.id = rh.rule_id
                WHERE r.scope_id = ? AND r.status = 'deprecated'
                    AND rh.change_type = 'DEPRECATED'
                """,
                (target_scope,),
            )
            dep_columns = [d[0] for d in cursor.description]
            for dep_row in cursor.fetchall():
                dep_rule = dict(zip(dep_columns, dep_row))
                cursor2 = conn.execute(
                    """
                    SELECT reason FROM rule_history
                    WHERE rule_id = ? AND change_type = 'PROMOTED'
                    ORDER BY changed_at DESC LIMIT 1
                    """,
                    (dep_rule["id"],),
                )
                promoted = cursor2.fetchone()
                if promoted and promoted[0]:
                    dep_rule["superseded_by"] = promoted[0]
                deprecated_rules.append(dep_rule)

        return {
            "events": events,
            "deprecated_rules": deprecated_rules,
        }
    finally:
        if close_on_exit:
            conn.close()
