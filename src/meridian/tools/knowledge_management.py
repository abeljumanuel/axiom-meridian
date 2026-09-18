"""Knowledge management tools — index, convert, approve, edit, reject, promote."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path

import time

from meridian.config import get_db_path, get_knowledge_base_path
from meridian.db.connection import get_connection
from meridian.parsers.atomic_parser import parse as atomic_parse
from meridian.parsers.legacy_parser import parse as legacy_parse
from meridian.rag import embedder, vector_store
from meridian.utils.id_generator import (
    next_lesson_code,
    next_rule_code,
    next_sequential_id,
)
from meridian.utils.privacy import strip_private_tags

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope_to_file_path(scope_id: str, doc_type: str = "rule") -> Path:
    """Map a scope_id to its canonical .md file path."""
    kb = get_knowledge_base_path()
    base_dir = "knowledge-base" if doc_type == "rule" else "lessons"

    if doc_type == "lesson" and not (kb / base_dir).is_dir():
        base_dir = "knowledge-base"

    if scope_id == "global":
        return kb / base_dir / "global" / "general.md"
    if scope_id.startswith("global-"):
        rest = scope_id[len("global-") :]
        return kb / base_dir / "global" / f"{rest}.md"
    if scope_id.startswith("project-"):
        rest = scope_id[len("project-") :]
        return kb / base_dir / "projects" / f"{rest}.md"
    raise ValueError(f"Cannot determine file path for scope_id: {scope_id}")


def _normalize_tags(tags: object) -> list[str]:
    """Normalise tags to a list of strings."""
    if tags is None:
        return []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags]
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _build_rule_atomic_block(
    code: str, scope_id: str, proposed_text: str, metadata: dict | None
) -> str:
    """Build a canonical atomic rule block."""
    meta = metadata or {}
    category = meta.get("category", "general")
    severity = meta.get("severity", "medium")
    applies_to = meta.get("applies_to", "**/*")
    tags = _normalize_tags(meta.get("tags"))
    source = meta.get("source", "manual")
    tags_str = ", ".join(tags)

    lines = [
        f"## {code}",
        f"**Scope:** {scope_id}",
        f"**Categoría:** {category}",
        f"**Severidad:** {severity}",
        f"**Aplica a:** {applies_to}",
        f"**Tags:** {tags_str}",
        f"**Fuente:** {source}",
        f"**Regla:** {proposed_text}",
    ]
    return "\n".join(lines)


def _build_lesson_atomic_block(
    code: str, scope_id: str, proposed_text: str, metadata: dict | None
) -> str:
    """Build a canonical atomic lesson block."""
    meta = metadata or {}
    project = meta.get("project", "")
    date_occurred = meta.get("date_occurred", "")
    severity = meta.get("severity", "medium")
    area_affected = meta.get("area_affected", "")
    tags = _normalize_tags(meta.get("tags"))
    impact = meta.get("impact", "")
    root_cause = meta.get("root_cause", "")
    resolution = meta.get("resolution", "")
    originated_rule_id = meta.get("originated_rule_id", "")
    tags_str = ", ".join(tags)

    lines = [
        f"## {code}",
        f"**Scope:** {scope_id}",
        f"**Proyecto:** {project}",
        f"**Fecha:** {date_occurred}",
        f"**Severidad del impacto:** {severity}",
        f"**Área afectada:** {area_affected}",
        f"**Tags:** {tags_str}",
        f"**Qué pasó:** {proposed_text}",
        f"**Impacto:** {impact}",
        f"**Causa raíz:** {root_cause}",
        f"**Resolución:** {resolution}",
        f"**Originó regla:** {originated_rule_id}",
    ]
    return "\n".join(lines)


def _append_atomic_block(dest_path: Path, block_text: str) -> tuple[int, int]:
    """Append *block_text* to *dest_path* with ``\\n\\n`` separator.

    Returns ``(file_offset, byte_length)`` of the newly written block.
    """
    current_bytes = dest_path.read_bytes()
    block_bytes = block_text.encode("utf-8")

    if len(current_bytes) > 0:
        separator = b"\n\n"
    else:
        separator = b""

    file_offset = len(current_bytes) + len(separator)

    with dest_path.open("ab") as f:
        f.write(separator + block_bytes)

    byte_length = len(block_bytes)
    return file_offset, byte_length


def _extract_lesson_fields(block_text: str) -> dict[str, str]:
    """Extract all ``**Field:** value`` pairs from a lesson block (multiline aware)."""
    fields: dict[str, str] = {}
    lines = block_text.split("\n")
    current_field: str | None = None
    current_lines: list[str] = []

    for line in lines[1:]:  # skip header
        match = re.match(r"\*\*([^*]+):\*\*\s*(.*)", line)
        if match:
            if current_field is not None:
                fields[current_field] = "\n".join(current_lines).rstrip()
            current_field = match.group(1).strip()
            current_lines = [match.group(2).strip()]
        elif current_field is not None:
            current_lines.append(line)

    if current_field is not None:
        fields[current_field] = "\n".join(current_lines).rstrip()

    return fields


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def _new_index_result() -> dict:
    """Fresh accumulator shared by the rule/lesson markdown indexers."""
    return {
        "indexed": 0,
        "created": 0,
        "updated": 0,
        "by_scope": {},
        "errors": [],
        "warnings": [],
    }


def _record_indexed(result: dict, scope_id: str) -> None:
    """Bump the indexed count and per-scope tally after a block is written."""
    result["indexed"] += 1
    result["by_scope"][scope_id] = result["by_scope"].get(scope_id, 0) + 1


def _insert_indexed_rule(conn: sqlite3.Connection, block, scope_id: str, clean_text: str) -> None:
    """Insert a rule discovered by atomic indexing, plus its CREATED history entry."""
    rule_id = block.code
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity,
         applies_to, tags, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            scope_id,
            block.code,
            clean_text,
            block.category or "general",
            block.severity or "medium",
            block.applies_to,
            json.dumps(block.tags),
            block.file_path,
            block.file_offset,
            block.byte_length,
        ),
    )
    hist_id = next_sequential_id(conn, "rule_history", "rh")
    conn.execute(
        """
        INSERT INTO rule_history
        (id, rule_id, change_type, new_text)
        VALUES (?, ?, ?, ?)
        """,
        (hist_id, rule_id, "CREATED", clean_text),
    )


def _update_indexed_rule(
    conn: sqlite3.Connection,
    block,
    scope_id: str,
    existing_id: str,
    existing_text: str,
    clean_text: str,
) -> None:
    """Overwrite a rule whose atomic block changed, plus its UPDATED history entry."""
    conn.execute(
        """
        UPDATE rules
        SET text = ?, scope_id = ?, category = ?, severity = ?,
            applies_to = ?, tags = ?, file_path = ?, file_offset = ?,
            byte_length = ?, updated_at = datetime('now'), embedding_id = NULL
        WHERE id = ?
        """,
        (
            clean_text,
            scope_id,
            block.category or "general",
            block.severity or "medium",
            block.applies_to,
            json.dumps(block.tags),
            block.file_path,
            block.file_offset,
            block.byte_length,
            existing_id,
        ),
    )
    hist_id = next_sequential_id(conn, "rule_history", "rh")
    conn.execute(
        """
        INSERT INTO rule_history
        (id, rule_id, change_type, previous_text, new_text)
        VALUES (?, ?, ?, ?, ?)
        """,
        (hist_id, existing_id, "UPDATED", existing_text, clean_text),
    )


def _index_rules_atomic(
    conn: sqlite3.Connection, filepath: str, default_scope_id: str, result: dict
) -> None:
    """Parse canonical ``## RN-XXX-NNN`` blocks and upsert them into rules/rule_history."""
    blocks, warnings = atomic_parse(filepath)
    result["warnings"].extend(warnings)

    for block in blocks:
        if not block.code.startswith("RN-"):
            result["warnings"].append(f"Skipping non-rule block {block.code}")
            continue

        scope_id = block.scope or default_scope_id
        cursor = conn.execute("SELECT 1 FROM scopes WHERE id = ?", (scope_id,))
        if cursor.fetchone() is None:
            result["errors"].append(
                f"Scope '{scope_id}' not found for block {block.code}"
            )
            continue

        clean_text = strip_private_tags(block.text)
        cursor = conn.execute(
            "SELECT id, text FROM rules WHERE code = ?", (block.code,)
        )
        row = cursor.fetchone()

        if row is None:
            _insert_indexed_rule(conn, block, scope_id, clean_text)
            result["created"] += 1
        else:
            existing_id, existing_text = row
            if existing_text == clean_text:
                continue
            _update_indexed_rule(conn, block, scope_id, existing_id, existing_text, clean_text)
            result["updated"] += 1

        _record_indexed(result, scope_id)


def _index_rules_legacy(
    conn: sqlite3.Connection, filepath: str, default_scope_id: str, result: dict
) -> None:
    """Parse legacy ``###`` blocks and stage each as a pending_proposals entry."""
    legacy_blocks = legacy_parse(filepath, doc_type="rules")

    for block in legacy_blocks:
        scope_id = default_scope_id
        proposed_text = strip_private_tags(block.raw_text)
        metadata = {
            "category": block.fields.get("Category", "general"),
            "severity": block.fields.get("Severity", "medium"),
            "scope_id": scope_id,
        }

        prop_id = next_sequential_id(conn, "pending_proposals", "prop")
        conn.execute(
            """
            INSERT INTO pending_proposals
            (id, type, scope_id, proposed_text, metadata, source_type, legacy_original)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prop_id,
                "rule",
                scope_id,
                proposed_text,
                json.dumps(metadata),
                "legacy",
                block.raw_text,
            ),
        )
        _record_indexed(result, scope_id)


def index_rules_from_markdown(
    filepath: str, default_scope_id: str, mode: str = "atomic"
) -> dict:
    """Index rules from a markdown file into SQLite.

    *mode="atomic"* parses canonical ``## RN-XXX-NNN`` blocks and writes
    directly to ``rules`` and ``rule_history``.

    *mode="legacy"* parses legacy ``###`` blocks and creates
    ``pending_proposals`` entries (never writes to ``rules``).
    """
    conn = get_connection(get_db_path())
    try:
        result = _new_index_result()
        try:
            if mode == "atomic":
                _index_rules_atomic(conn, filepath, default_scope_id, result)
            elif mode == "legacy":
                _index_rules_legacy(conn, filepath, default_scope_id, result)
            else:
                raise ValueError(f"Unknown mode: {mode}. Use 'atomic' or 'legacy'.")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return result
    finally:
        conn.close()


def _insert_indexed_lesson(
    conn: sqlite3.Connection, block, scope_id: str, fields: dict, what_happened: str
) -> None:
    """Insert a lesson discovered by atomic indexing, plus its CREATED history entry."""
    lesson_id = block.code
    conn.execute(
        """
        INSERT INTO lessons
        (id, scope_id, code, project, date_occurred, severity,
         area_affected, what_happened, impact, root_cause,
         resolution, tags, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lesson_id,
            scope_id,
            block.code,
            fields.get("Proyecto"),
            fields.get("Fecha"),
            fields.get("Severidad del impacto", "medium"),
            fields.get("Área afectada"),
            what_happened,
            fields.get("Impacto"),
            fields.get("Causa raíz"),
            fields.get("Resolución"),
            json.dumps(block.tags),
            block.file_path,
            block.file_offset,
            block.byte_length,
        ),
    )
    hist_id = next_sequential_id(conn, "lesson_history", "lh")
    conn.execute(
        """
        INSERT INTO lesson_history
        (id, lesson_id, change_type)
        VALUES (?, ?, ?)
        """,
        (hist_id, lesson_id, "CREATED"),
    )


def _update_indexed_lesson(
    conn: sqlite3.Connection,
    block,
    scope_id: str,
    fields: dict,
    existing_id: str,
    what_happened: str,
) -> None:
    """Overwrite a lesson whose atomic block changed, plus its history entry."""
    conn.execute(
        """
        UPDATE lessons
        SET what_happened = ?, scope_id = ?, project = ?,
            date_occurred = ?, severity = ?, area_affected = ?,
            impact = ?, root_cause = ?, resolution = ?,
            tags = ?, file_path = ?, file_offset = ?,
            byte_length = ?, embedding_id = NULL
        WHERE id = ?
        """,
        (
            what_happened,
            scope_id,
            fields.get("Proyecto"),
            fields.get("Fecha"),
            fields.get("Severidad del impacto", "medium"),
            fields.get("Área afectada"),
            fields.get("Impacto"),
            fields.get("Causa raíz"),
            fields.get("Resolución"),
            json.dumps(block.tags),
            block.file_path,
            block.file_offset,
            block.byte_length,
            existing_id,
        ),
    )
    hist_id = next_sequential_id(conn, "lesson_history", "lh")
    conn.execute(
        """
        INSERT INTO lesson_history
        (id, lesson_id, change_type, reason)
        VALUES (?, ?, ?, ?)
        """,
        (hist_id, existing_id, "DEPRECATED", "Updated via re-index"),
    )


def _index_lessons_atomic(
    conn: sqlite3.Connection, filepath: str, default_scope_id: str, result: dict
) -> None:
    """Parse canonical ``## LL-XXX-NNN`` blocks and upsert them into lessons/lesson_history."""
    blocks, warnings = atomic_parse(filepath)
    result["warnings"].extend(warnings)

    raw_bytes = Path(filepath).read_bytes()

    for block in blocks:
        if not block.code.startswith("LL-"):
            result["warnings"].append(f"Skipping non-lesson block {block.code}")
            continue

        scope_id = block.scope or default_scope_id
        cursor = conn.execute("SELECT 1 FROM scopes WHERE id = ?", (scope_id,))
        if cursor.fetchone() is None:
            result["errors"].append(
                f"Scope '{scope_id}' not found for block {block.code}"
            )
            continue

        block_bytes = raw_bytes[block.file_offset : block.file_offset + block.byte_length]
        block_text = block_bytes.decode("utf-8")
        fields = _extract_lesson_fields(block_text)
        what_happened = strip_private_tags(fields.get("Qué pasó", block.text))

        cursor = conn.execute(
            "SELECT id, what_happened FROM lessons WHERE code = ?",
            (block.code,),
        )
        row = cursor.fetchone()

        if row is None:
            _insert_indexed_lesson(conn, block, scope_id, fields, what_happened)
            result["created"] += 1
        else:
            existing_id, existing_text = row
            if existing_text == what_happened:
                continue
            _update_indexed_lesson(conn, block, scope_id, fields, existing_id, what_happened)
            result["updated"] += 1

        _record_indexed(result, scope_id)


def _index_lessons_legacy(
    conn: sqlite3.Connection, filepath: str, default_scope_id: str, result: dict
) -> None:
    """Parse legacy ``###`` blocks and stage each as a pending_proposals entry."""
    legacy_blocks = legacy_parse(filepath, doc_type="lessons")

    for block in legacy_blocks:
        scope_id = default_scope_id
        proposed_text = strip_private_tags(block.raw_text)
        metadata = {
            "severity": block.fields.get("Severity", "medium"),
            "scope_id": scope_id,
        }

        prop_id = next_sequential_id(conn, "pending_proposals", "prop")
        conn.execute(
            """
            INSERT INTO pending_proposals
            (id, type, scope_id, proposed_text, metadata, source_type, legacy_original)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prop_id,
                "lesson",
                scope_id,
                proposed_text,
                json.dumps(metadata),
                "legacy",
                block.raw_text,
            ),
        )
        _record_indexed(result, scope_id)


def index_lessons_from_markdown(
    filepath: str, default_scope_id: str, mode: str = "atomic"
) -> dict:
    """Index lessons from a markdown file into SQLite.

    Logic is equivalent to :func:`index_rules_from_markdown` but targets
    the ``lessons`` table.
    """
    conn = get_connection(get_db_path())
    try:
        result = _new_index_result()
        if mode == "atomic":
            _index_lessons_atomic(conn, filepath, default_scope_id, result)
        elif mode == "legacy":
            _index_lessons_legacy(conn, filepath, default_scope_id, result)
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'atomic' or 'legacy'.")

        conn.commit()
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Proposal lifecycle
# ---------------------------------------------------------------------------


def approve_proposal(proposal_id: str) -> dict:
    """Approve a pending proposal and write the atomic block to its .md file."""
    conn = get_connection(get_db_path())
    try:
        proposal = _load_pending_proposal(conn, proposal_id)
        proposed_text = strip_private_tags(proposal["proposed_text"])
        metadata = (
            json.loads(proposal["metadata"]) if proposal.get("metadata") else {}
        )

        if proposal["type"] == "update":
            return _approve_update_proposal(conn, proposal_id, proposal, proposed_text, metadata)
        return _approve_create_proposal(conn, proposal_id, proposal, proposed_text, metadata)
    finally:
        conn.close()


def _load_pending_proposal(conn: sqlite3.Connection, proposal_id: str) -> dict:
    """Fetch a proposal by id, raising if it doesn't exist or isn't pending."""
    cursor = conn.execute(
        "SELECT * FROM pending_proposals WHERE id = ?", (proposal_id,)
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Proposal {proposal_id} not found")

    columns = [d[0] for d in cursor.description]
    proposal = dict(zip(columns, row))
    if proposal["status"] != "pending":
        raise ValueError(
            f"Proposal {proposal_id} is not pending (status: {proposal['status']})"
        )
    return proposal


def _resolve_update_target(
    conn: sqlite3.Connection, target_id: str
) -> tuple[str, str, callable, str, dict]:
    """Resolve an UPDATE proposal's target_id (RN-/LL- prefix) to its table,
    history table, atomic-block builder, and current row."""
    if target_id.startswith("RN-"):
        target_table, hist_table, block_builder, id_field = (
            "rules",
            "rule_history",
            _build_rule_atomic_block,
            "rule_id",
        )
    elif target_id.startswith("LL-"):
        target_table, hist_table, block_builder, id_field = (
            "lessons",
            "lesson_history",
            _build_lesson_atomic_block,
            "lesson_id",
        )
    else:
        raise ValueError(
            f"Invalid target_id format: {target_id}. "
            "Must start with 'RN-' or 'LL-'."
        )

    cursor = conn.execute(f"SELECT * FROM {target_table} WHERE id = ?", (target_id,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Target '{target_id}' not found in {target_table}")
    target_columns = [d[0] for d in cursor.description]
    target = dict(zip(target_columns, row))
    return target_table, hist_table, block_builder, id_field, target


def _splice_atomic_block(
    dest_path: Path, old_offset: int, old_length: int, new_block_text: str
) -> tuple[str, int]:
    """Replace the byte range [old_offset, old_offset+old_length) in dest_path
    with new_block_text, preserving everything else in the file untouched.

    Returns the replaced block's original text and the new block's byte length.
    """
    raw_bytes = dest_path.read_bytes()
    old_block_text = raw_bytes[old_offset : old_offset + old_length].decode("utf-8")
    new_block_bytes = new_block_text.encode("utf-8")
    new_bytes = raw_bytes[:old_offset] + new_block_bytes + raw_bytes[old_offset + old_length :]
    dest_path.write_bytes(new_bytes)
    return old_block_text, len(new_block_bytes)


def _update_rule_row(
    conn: sqlite3.Connection,
    target_id: str,
    target: dict,
    proposed_text: str,
    metadata: dict,
    new_offset: int,
    new_length: int,
) -> None:
    """Overwrite an existing rule row with an approved UPDATE proposal's content."""
    conn.execute(
        """
        UPDATE rules
        SET text = ?, category = ?, severity = ?,
            applies_to = ?, tags = ?, file_offset = ?,
            byte_length = ?, updated_at = datetime('now'),
            embedding_id = NULL
        WHERE id = ?
        """,
        (
            proposed_text,
            metadata.get("category", target.get("category", "general")),
            metadata.get("severity", target.get("severity", "medium")),
            metadata.get("applies_to", target.get("applies_to", "**/*")),
            json.dumps(_normalize_tags(metadata.get("tags", []))),
            new_offset,
            new_length,
            target_id,
        ),
    )


def _update_lesson_row(
    conn: sqlite3.Connection,
    target_id: str,
    target: dict,
    scope_id: str,
    proposed_text: str,
    metadata: dict,
    new_offset: int,
    new_length: int,
) -> None:
    """Overwrite an existing lesson row with an approved UPDATE proposal's content."""
    conn.execute(
        """
        UPDATE lessons
        SET what_happened = ?, scope_id = ?, project = ?,
            date_occurred = ?, severity = ?, area_affected = ?,
            impact = ?, root_cause = ?, resolution = ?,
            tags = ?, file_offset = ?, byte_length = ?,
            embedding_id = NULL
        WHERE id = ?
        """,
        (
            proposed_text,
            scope_id,
            metadata.get("project", target.get("project")),
            metadata.get("date_occurred", target.get("date_occurred")),
            metadata.get("severity", target.get("severity", "medium")),
            metadata.get("area_affected", target.get("area_affected")),
            metadata.get("impact", target.get("impact")),
            metadata.get("root_cause", target.get("root_cause")),
            metadata.get("resolution", target.get("resolution")),
            json.dumps(_normalize_tags(metadata.get("tags", []))),
            new_offset,
            new_length,
            target_id,
        ),
    )


def _approve_update_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    proposal: dict,
    proposed_text: str,
    metadata: dict,
) -> dict:
    """Approve an UPDATE proposal: splice its target's atomic block in place
    and record an UPDATED history entry."""
    target_id = proposal.get("target_id")
    if target_id is None:
        raise ValueError(f"UPDATE proposal {proposal_id} has no target_id")

    target_table, hist_table, block_builder, id_field, target = _resolve_update_target(
        conn, target_id
    )

    scope_id = target["scope_id"]
    dest_path = Path(target["file_path"])
    old_offset = target["file_offset"]
    old_length = target["byte_length"]
    if not dest_path.exists():
        raise FileNotFoundError(f"Destination file does not exist: {dest_path}")

    block_text = block_builder(target_id, scope_id, proposed_text, metadata)
    old_block_text, new_length = _splice_atomic_block(
        dest_path, old_offset, old_length, block_text
    )

    conn.execute("BEGIN TRANSACTION")
    try:
        if target_table == "rules":
            _update_rule_row(conn, target_id, target, proposed_text, metadata, old_offset, new_length)
        else:
            _update_lesson_row(
                conn, target_id, target, scope_id, proposed_text, metadata, old_offset, new_length
            )

        hist_id = next_sequential_id(conn, hist_table, "rh" if target_table == "rules" else "lh")
        conn.execute(
            f"""
            INSERT INTO {hist_table}
            (id, {id_field}, change_type, previous_text, new_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hist_id, target_id, "UPDATED", old_block_text, proposed_text),
        )
        conn.execute(
            "UPDATE pending_proposals SET status = 'approved' WHERE id = ?",
            (proposal_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "proposal_id": proposal_id,
        "code": target_id,
        "scope_id": scope_id,
        "file_path": str(dest_path),
        "file_offset": old_offset,
        "byte_length": new_length,
    }


def _insert_new_rule(
    conn: sqlite3.Connection,
    code: str,
    scope_id: str,
    proposed_text: str,
    metadata: dict,
    proposal: dict,
    dest_path: Path,
    file_offset: int,
    byte_length: int,
    suggested_attributes: list[dict],
) -> None:
    """Insert a newly-approved rule, its CREATED history entry, and any
    suggested dynamic attributes (ADR-002)."""
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, applies_to,
         tags, source_type, source_ref, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code,
            scope_id,
            code,
            proposed_text,
            metadata.get("category", "general"),
            metadata.get("severity", "medium"),
            metadata.get("applies_to", "**/*"),
            json.dumps(_normalize_tags(metadata.get("tags"))),
            proposal.get("source_type"),
            proposal.get("source_ref"),
            str(dest_path),
            file_offset,
            byte_length,
        ),
    )

    hist_id = next_sequential_id(conn, "rule_history", "rh")
    conn.execute(
        """
        INSERT INTO rule_history
        (id, rule_id, change_type, new_text)
        VALUES (?, ?, ?, ?)
        """,
        (hist_id, code, "CREATED", proposed_text),
    )

    for attr in suggested_attributes:
        conn.execute(
            """
            INSERT INTO rule_attributes (rule_id, key, value)
            VALUES (?, ?, ?)
            """,
            (code, attr["key"], attr["value"]),
        )


def _insert_new_lesson(
    conn: sqlite3.Connection,
    code: str,
    scope_id: str,
    proposed_text: str,
    metadata: dict,
    proposal: dict,
    dest_path: Path,
    file_offset: int,
    byte_length: int,
) -> None:
    """Insert a newly-approved lesson and its CREATED history entry."""
    conn.execute(
        """
        INSERT INTO lessons
        (id, scope_id, code, project, date_occurred, severity,
         area_affected, what_happened, impact, root_cause, resolution,
         tags, source_type, source_ref, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code,
            scope_id,
            code,
            metadata.get("project"),
            metadata.get("date_occurred"),
            metadata.get("severity", "medium"),
            metadata.get("area_affected"),
            proposed_text,
            metadata.get("impact"),
            metadata.get("root_cause"),
            metadata.get("resolution"),
            json.dumps(_normalize_tags(metadata.get("tags"))),
            proposal.get("source_type"),
            proposal.get("source_ref"),
            str(dest_path),
            file_offset,
            byte_length,
        ),
    )

    hist_id = next_sequential_id(conn, "lesson_history", "lh")
    conn.execute(
        """
        INSERT INTO lesson_history (id, lesson_id, change_type)
        VALUES (?, ?, ?)
        """,
        (hist_id, code, "CREATED"),
    )


def _approve_create_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    proposal: dict,
    proposed_text: str,
    metadata: dict,
) -> dict:
    """Approve a rule/lesson proposal: assign it a new code, append its atomic
    block to the scope's markdown file, and insert the corresponding row."""
    scope_id = proposal["scope_id"]
    prop_type = proposal["type"]
    suggested_attributes = (
        json.loads(proposal["suggested_attributes"])
        if proposal.get("suggested_attributes")
        else []
    )

    if prop_type == "rule":
        code = next_rule_code(conn, scope_id)
        block_text = _build_rule_atomic_block(code, scope_id, proposed_text, metadata)
    elif prop_type == "lesson":
        code = next_lesson_code(conn, scope_id)
        block_text = _build_lesson_atomic_block(code, scope_id, proposed_text, metadata)
    else:
        raise ValueError(f"Unknown proposal type: {prop_type}")

    dest_path = _scope_to_file_path(scope_id, doc_type=prop_type)
    if not dest_path.exists():
        raise FileNotFoundError(f"Destination file does not exist: {dest_path}")

    file_offset, byte_length = _append_atomic_block(dest_path, block_text)

    if prop_type == "rule":
        _insert_new_rule(
            conn, code, scope_id, proposed_text, metadata, proposal,
            dest_path, file_offset, byte_length, suggested_attributes,
        )
    else:
        _insert_new_lesson(
            conn, code, scope_id, proposed_text, metadata, proposal,
            dest_path, file_offset, byte_length,
        )

    conn.execute(
        "UPDATE pending_proposals SET status = 'approved' WHERE id = ?",
        (proposal_id,),
    )
    conn.commit()

    return {
        "proposal_id": proposal_id,
        "code": code,
        "scope_id": scope_id,
        "file_path": str(dest_path),
        "file_offset": file_offset,
        "byte_length": byte_length,
    }


def edit_proposal(
    proposal_id: str, new_text: str, metadata: dict | None = None
) -> dict:
    """Update the proposed text and optionally metadata of a pending proposal.

    The status remains ``pending``.
    """
    conn = get_connection(get_db_path())
    try:
        cursor = conn.execute(
            "SELECT proposed_text, metadata FROM pending_proposals WHERE id = ?",
            (proposal_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        current_text, current_metadata_json = row
        clean_text = strip_private_tags(new_text)

        if metadata is not None:
            current_metadata = (
                json.loads(current_metadata_json)
                if current_metadata_json
                else {}
            )
            current_metadata.update(metadata)
            new_metadata_json = json.dumps(current_metadata)
        else:
            new_metadata_json = current_metadata_json

        conn.execute(
            """
            UPDATE pending_proposals
            SET proposed_text = ?, metadata = ?, status = 'pending'
            WHERE id = ?
            """,
            (clean_text, new_metadata_json, proposal_id),
        )
        conn.commit()

        return {"proposal_id": proposal_id, "status": "pending"}
    finally:
        conn.close()


def reject_proposal(proposal_id: str, reason: str | None = None) -> dict:
    """Reject a proposal. No side effects besides updating the record."""
    conn = get_connection(get_db_path())
    try:
        cursor = conn.execute(
            "SELECT id FROM pending_proposals WHERE id = ?", (proposal_id,)
        )
        if cursor.fetchone() is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        conn.execute(
            """
            UPDATE pending_proposals
            SET status = 'rejected', reason = ?
            WHERE id = ?
            """,
            (reason, proposal_id),
        )
        conn.commit()

        return {"proposal_id": proposal_id, "status": "rejected"}
    finally:
        conn.close()


def list_pending_proposals(
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List pending proposals with optional filtering."""
    conn = get_connection(get_db_path())
    try:
        query = "SELECT * FROM pending_proposals WHERE 1=1"
        params: list[object] = []

        if project_id is not None:
            if not project_id.startswith(("global-", "project-")):
                scope_filter = f"project-{project_id}"
            else:
                scope_filter = project_id
            query += " AND scope_id = ?"
            params.append(scope_filter)

        if type is not None:
            query += " AND type = ?"
            params.append(type)

        if status is not None:
            query += " AND status = ?"
            params.append(status)

        cursor = conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration & promotion
# ---------------------------------------------------------------------------


def convert_to_atomic_format(
    filepath: str, default_scope_id: str, doc_type: str
) -> dict:
    """Convert a legacy markdown file to atomic-format pending_proposals.

    Never writes .md files directly.
    """
    conn = get_connection(get_db_path())
    try:
        legacy_blocks = legacy_parse(filepath, doc_type=doc_type)
        proposals: list[dict] = []

        for block in legacy_blocks:
            # Scope inference (basic keyword matching)
            inferred_scope = default_scope_id
            scope_suggested = False
            raw_lower = block.raw_text.lower()

            if "quarkus" in raw_lower:
                inferred_scope = "global-quarkus"
            elif "java" in raw_lower:
                inferred_scope = "global-java"
            elif "nestjs" in raw_lower:
                inferred_scope = "global-nestjs"
            elif "spring-boot" in raw_lower:
                inferred_scope = "global-spring-boot"
            elif "go-fiber" in raw_lower:
                inferred_scope = "global-go-fiber"
            elif "go-gin" in raw_lower:
                inferred_scope = "global-go-gin"
            elif "go" in raw_lower:
                inferred_scope = "global-go"
            elif "flutter" in raw_lower:
                inferred_scope = "global-flutter"
            else:
                scope_suggested = True

            proposed_text = strip_private_tags(block.raw_text)

            if doc_type == "rules":
                metadata = {
                    "category": block.fields.get("Category", "general"),
                    "severity": block.fields.get("Severity", "medium"),
                    "scope_id": inferred_scope,
                    "scope_suggested": scope_suggested,
                }
                prop_type = "rule"
            else:
                metadata = {
                    "severity": block.fields.get("Severity", "medium"),
                    "scope_id": inferred_scope,
                    "scope_suggested": scope_suggested,
                }
                prop_type = "lesson"

            # Suggest destination file
            try:
                suggested_file = str(
                    _scope_to_file_path(inferred_scope, doc_type=prop_type)
                )
            except ValueError:
                suggested_file = None

            metadata["suggested_file_path"] = suggested_file

            prop_id = next_sequential_id(conn, "pending_proposals", "prop")
            conn.execute(
                """
                INSERT INTO pending_proposals
                (id, type, scope_id, proposed_text, metadata, source_type, legacy_original)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prop_id,
                    prop_type,
                    inferred_scope,
                    proposed_text,
                    json.dumps(metadata),
                    "legacy",
                    block.raw_text,
                ),
            )

            proposals.append(
                {
                    "id": prop_id,
                    "type": prop_type,
                    "scope_id": inferred_scope,
                    "suggested_file": suggested_file,
                }
            )

        conn.commit()
        return {
            "proposals_created": len(proposals),
            "proposals": proposals,
        }
    finally:
        conn.close()


def promote_rule(rule_id: str, new_scope_id: str) -> dict:
    """Promote a rule to a more general scope.

    Registers ``PROMOTED`` in ``rule_history`` and marks the original entry
    as ``deprecated`` in the source .md file.
    """
    conn = get_connection(get_db_path())
    try:
        cursor = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Rule {rule_id} not found")

        columns = [d[0] for d in cursor.description]
        rule = dict(zip(columns, row))

        cursor = conn.execute("SELECT id FROM scopes WHERE id = ?", (new_scope_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"Scope {new_scope_id} not found")

        conn.execute(
            """
            UPDATE rules
            SET status = 'deprecated', updated_at = datetime('now')
            WHERE id = ?
            """,
            (rule_id,),
        )

        file_path = rule.get("file_path")
        file_offset = rule.get("file_offset")
        byte_length = rule.get("byte_length")
        if file_path and file_offset is not None and byte_length is not None:
            _mark_deprecated_in_md(file_path, file_offset, byte_length)

        hist_id = next_sequential_id(conn, "rule_history", "rh")
        conn.execute(
            """
            INSERT INTO rule_history
            (id, rule_id, change_type, reason)
            VALUES (?, ?, ?, ?)
            """,
            (hist_id, rule_id, "PROMOTED", f"Promoted to scope {new_scope_id}"),
        )

        conn.commit()

        return {
            "rule_id": rule_id,
            "new_scope_id": new_scope_id,
            "status": "deprecated",
        }
    finally:
        conn.close()


def _rule_embedding_metadata(row: dict) -> dict:
    """Vector-store metadata for a rule embedding (drives scope/attribute filtering)."""
    return {
        "scope_id": row["scope_id"],
        "category": row["category"],
        "severity": row["severity"],
        "applies_to": row.get("applies_to") or "",
        "tags": row.get("tags") or "[]",
    }


def _lesson_embedding_metadata(row: dict) -> dict:
    """Vector-store metadata for a lesson embedding (drives scope/attribute filtering)."""
    return {
        "scope_id": row["scope_id"],
        "severity": row["severity"] or "medium",
        "area_affected": row["area_affected"] or "",
        "tags": row.get("tags") or "[]",
    }


def _generate_embeddings_for_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    kind: str,
    text_column: str,
    select_columns: str,
    scope_id: str | None,
    build_metadata,
    upsert_fn,
) -> tuple[int, int, int]:
    """Embed and upsert every active, un-embedded row of *table* into the vector
    store. Returns (processed, errors, total_rows); the caller derives its own
    'skipped' count from those so rules and lessons share one accounting rule.
    """
    sql = (
        f"SELECT id, scope_id, {select_columns} FROM {table} "
        "WHERE status = 'active' AND embedding_id IS NULL"
    )
    params: list[object] = []
    if scope_id is not None:
        sql += " AND scope_id = ?"
        params.append(scope_id)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    columns = [d[0] for d in cursor.description]

    processed = 0
    errors = 0
    if not rows:
        return processed, errors, len(rows)

    texts = [row[columns.index(text_column)] for row in rows]
    try:
        embeddings = embedder.generate_embeddings_batch(texts)
    except Exception as exc:
        errors += len(rows)
        logger.exception("Failed to generate embeddings for %s: %s", table, exc)
        embeddings = []

    for idx, row in enumerate(rows):
        if idx >= len(embeddings):
            errors += 1
            continue
        row_dict = dict(zip(columns, row))
        entity_id = row_dict["id"]
        try:
            upsert_fn(entity_id, row_dict[text_column], embeddings[idx], build_metadata(row_dict))
            text_hash = hashlib.sha256(row_dict[text_column].encode()).hexdigest()[:16]
            conn.execute(
                f"UPDATE {table} SET embedding_id = ? WHERE id = ?",
                (text_hash, entity_id),
            )
            processed += 1
        except Exception as exc:
            errors += 1
            logger.exception("Failed to upsert %s %s: %s", kind, entity_id, exc)

    return processed, errors, len(rows)


def generate_embeddings(
    conn: sqlite3.Connection, scope_id: str | None = None
) -> dict:
    """Generate or update embeddings for active rules and lessons.

    - Without scope_id → processes all active rules and lessons.
    - With scope_id → processes only the specified scope (incremental).
    - Only processes entries with embedding_id IS NULL.
    - Updates embedding_id in SQLite after each entry is persisted.
    - Persists to ChromaDB with scope metadata for hybrid filtering.

    Returns: {"processed": int, "skipped": int, "errors": int,
              "duration_seconds": float}
    """
    start = time.perf_counter()

    rules_processed, rules_errors, rules_total = _generate_embeddings_for_table(
        conn,
        table="rules",
        kind="rule",
        text_column="text",
        select_columns="code, text, category, severity, applies_to, tags",
        scope_id=scope_id,
        build_metadata=_rule_embedding_metadata,
        upsert_fn=vector_store.upsert_rule,
    )
    lessons_processed, lessons_errors, lessons_total = _generate_embeddings_for_table(
        conn,
        table="lessons",
        kind="lesson",
        text_column="what_happened",
        select_columns="code, what_happened, severity, area_affected, tags",
        scope_id=scope_id,
        build_metadata=_lesson_embedding_metadata,
        upsert_fn=vector_store.upsert_lesson,
    )

    processed = rules_processed + lessons_processed
    errors = rules_errors + lessons_errors
    skipped = (
        (rules_total - rules_processed - rules_errors)
        + (lessons_total - lessons_processed - lessons_errors)
    )

    conn.commit()
    duration = time.perf_counter() - start
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "duration_seconds": round(duration, 3),
    }


def _mark_deprecated_in_md(file_path: str, file_offset: int, byte_length: int) -> None:
    """Best-effort deprecation marker in the source .md file."""
    path = Path(file_path)
    if not path.exists():
        return

    raw_bytes = path.read_bytes()
    block_bytes = raw_bytes[file_offset : file_offset + byte_length]
    block_text = block_bytes.decode("utf-8")

    lines = block_text.split("\n")
    if len(lines) > 0:
        new_lines = [lines[0], "**Status:** deprecated"] + lines[1:]
        new_block = "\n".join(new_lines)
        new_block_bytes = new_block.encode("utf-8")

        new_raw = (
            raw_bytes[:file_offset]
            + new_block_bytes
            + raw_bytes[file_offset + byte_length :]
        )
        path.write_bytes(new_raw)


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------


def create_project(
    conn: sqlite3.Connection,
    project_id: str,
    name: str | None = None,
    parent_scope: str = "global",
) -> dict:
    """Create a new project scope and its knowledge base directories.

    1. Validates parent_scope exists in scopes.
    2. Inserts new scope into scopes table.
    3. Creates KB directories: knowledge-base/projects/{project_id}, lessons/projects/{project_id}.
    4. Creates placeholder .md file.
    5. Returns the new scope_id.
    """
    project_scope_id = f"project-{project_id}"

    cursor = conn.execute("SELECT 1 FROM scopes WHERE id = ?", (parent_scope,))
    if cursor.fetchone() is None:
        valid = [r[0] for r in conn.execute("SELECT id FROM scopes ORDER BY id").fetchall()]
        raise ValueError(f"Parent scope '{parent_scope}' not found. Valid scopes: {valid}")

    cursor = conn.execute("SELECT 1 FROM scopes WHERE id = ?", (project_scope_id,))
    if cursor.fetchone() is not None:
        raise ValueError(f"Project scope '{project_scope_id}' already exists")

    kb = get_knowledge_base_path()
    project_dir_kb = kb / "knowledge-base" / "projects"
    project_dir_lessons = kb / "lessons" / "projects"

    project_dir_kb.mkdir(parents=True, exist_ok=True)
    project_dir_lessons.mkdir(parents=True, exist_ok=True)

    md_path = project_dir_kb / f"{project_id}.md"
    if not md_path.exists():
        md_path.write_text(f"# {name or project_id}\n\n")

    conn.execute(
        "INSERT INTO scopes (id, type, name, parent_id) VALUES (?, ?, ?, ?)",
        (project_scope_id, "project", name or project_id, parent_scope),
    )
    conn.commit()

    return {
        "scope_id": project_scope_id,
        "name": name or project_id,
        "parent_scope": parent_scope,
        "file_path": str(md_path),
    }
