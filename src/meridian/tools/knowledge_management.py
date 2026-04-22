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
        result = {
            "indexed": 0,
            "created": 0,
            "updated": 0,
            "by_scope": {},
            "errors": [],
            "warnings": [],
        }

        try:
            if mode == "atomic":
                blocks, warnings = atomic_parse(filepath)
                result["warnings"].extend(warnings)

                for block in blocks:
                    if not block.code.startswith("RN-"):
                        result["warnings"].append(
                            f"Skipping non-rule block {block.code}"
                        )
                        continue

                    scope_id = block.scope or default_scope_id

                    cursor = conn.execute(
                        "SELECT 1 FROM scopes WHERE id = ?", (scope_id,)
                    )
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
                        result["created"] += 1
                    else:
                        existing_id, existing_text = row
                        if existing_text != clean_text:
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
                                (
                                    hist_id,
                                    existing_id,
                                    "UPDATED",
                                    existing_text,
                                    clean_text,
                                ),
                            )
                            result["updated"] += 1
                        else:
                            # unchanged — skip
                            continue

                    result["indexed"] += 1
                    result["by_scope"][scope_id] = (
                        result["by_scope"].get(scope_id, 0) + 1
                    )

            elif mode == "legacy":
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
                    result["indexed"] += 1
                    result["by_scope"][scope_id] = (
                        result["by_scope"].get(scope_id, 0) + 1
                    )
            else:
                raise ValueError(f"Unknown mode: {mode}. Use 'atomic' or 'legacy'.")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return result
    finally:
        conn.close()


def index_lessons_from_markdown(
    filepath: str, default_scope_id: str, mode: str = "atomic"
) -> dict:
    """Index lessons from a markdown file into SQLite.

    Logic is equivalent to :func:`index_rules_from_markdown` but targets
    the ``lessons`` table.
    """
    conn = get_connection(get_db_path())
    try:
        result = {
            "indexed": 0,
            "created": 0,
            "updated": 0,
            "by_scope": {},
            "errors": [],
            "warnings": [],
        }

        if mode == "atomic":
            blocks, warnings = atomic_parse(filepath)
            result["warnings"].extend(warnings)

            path = Path(filepath)
            raw_bytes = path.read_bytes()

            for block in blocks:
                if not block.code.startswith("LL-"):
                    result["warnings"].append(
                        f"Skipping non-lesson block {block.code}"
                    )
                    continue

                scope_id = block.scope or default_scope_id

                cursor = conn.execute(
                    "SELECT 1 FROM scopes WHERE id = ?", (scope_id,)
                )
                if cursor.fetchone() is None:
                    result["errors"].append(
                        f"Scope '{scope_id}' not found for block {block.code}"
                    )
                    continue

                block_bytes = raw_bytes[
                    block.file_offset : block.file_offset + block.byte_length
                ]
                block_text = block_bytes.decode("utf-8")
                fields = _extract_lesson_fields(block_text)

                what_happened = strip_private_tags(
                    fields.get("Qué pasó", block.text)
                )

                cursor = conn.execute(
                    "SELECT id, what_happened FROM lessons WHERE code = ?",
                    (block.code,),
                )
                row = cursor.fetchone()

                if row is None:
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
                    result["created"] += 1
                else:
                    existing_id, existing_text = row
                    if existing_text != what_happened:
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
                            (
                                hist_id,
                                existing_id,
                                "DEPRECATED",
                                "Updated via re-index",
                            ),
                        )
                        result["updated"] += 1
                    else:
                        continue

                result["indexed"] += 1
                result["by_scope"][scope_id] = (
                    result["by_scope"].get(scope_id, 0) + 1
                )

        elif mode == "legacy":
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
                result["indexed"] += 1
                result["by_scope"][scope_id] = (
                    result["by_scope"].get(scope_id, 0) + 1
                )
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

        scope_id = proposal["scope_id"]
        prop_type = proposal["type"]
        proposed_text = strip_private_tags(proposal["proposed_text"])
        metadata = (
            json.loads(proposal["metadata"])
            if proposal.get("metadata")
            else {}
        )
        suggested_attributes = (
            json.loads(proposal["suggested_attributes"])
            if proposal.get("suggested_attributes")
            else []
        )

        # Handle UPDATE proposal type
        if prop_type == "update":
            target_id = proposal.get("target_id")
            if target_id is None:
                raise ValueError(
                    f"UPDATE proposal {proposal_id} has no target_id"
                )

            # Determine target table and type from target_id prefix
            if target_id.startswith("RN-"):
                target_table = "rules"
                hist_table = "rule_history"
                block_builder = _build_rule_atomic_block
                id_field = "rule_id"
            elif target_id.startswith("LL-"):
                target_table = "lessons"
                hist_table = "lesson_history"
                block_builder = _build_lesson_atomic_block
                id_field = "lesson_id"
            else:
                raise ValueError(
                    f"Invalid target_id format: {target_id}. "
                    "Must start with 'RN-' or 'LL-'."
                )

            # Fetch target using target_id
            cursor = conn.execute(f"SELECT * FROM {target_table} WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Target '{target_id}' not found in {target_table}")

            target_columns = [d[0] for d in cursor.description]
            target = dict(zip(target_columns, row))

            # Get file path and offset from target
            scope_id = target["scope_id"]
            dest_path = Path(target["file_path"])
            old_offset = target["file_offset"]
            old_length = target["byte_length"]

            if not dest_path.exists():
                raise FileNotFoundError(
                    f"Destination file does not exist: {dest_path}"
                )

            # Read existing block bytes
            raw_bytes = dest_path.read_bytes()
            old_block_bytes = raw_bytes[old_offset : old_offset + old_length]
            old_block_text = old_block_bytes.decode("utf-8")

            # Build new block text
            block_text = block_builder(target_id, scope_id, proposed_text, metadata)
            new_block_bytes = block_text.encode("utf-8")
            new_length = len(new_block_bytes)

            # Atomic file replacement: byte-level slice
            new_bytes = raw_bytes[:old_offset] + new_block_bytes + raw_bytes[old_offset + old_length:]
            dest_path.write_bytes(new_bytes)

            # Start transaction for DB operations
            conn.execute("BEGIN TRANSACTION")

            try:
                # Update target row based on type
                if target_table == "rules":
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
                            old_offset,
                            new_length,
                            target_id,
                        ),
                    )
                else:  # lessons
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
                            old_offset,
                            new_length,
                            target_id,
                        ),
                    )

                # Record history with change_type="UPDATED"
                hist_id = next_sequential_id(conn, hist_table, "rh" if target_table == "rules" else "lh")
                conn.execute(
                    f"""
                    INSERT INTO {hist_table}
                    (id, {id_field}, change_type, previous_text, new_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (hist_id, target_id, "UPDATED", old_block_text, proposed_text),
                )

                # Update proposal status
                conn.execute(
                    "UPDATE pending_proposals SET status = 'approved' WHERE id = ?",
                    (proposal_id,),
                )

                conn.commit()

                return {
                    "proposal_id": proposal_id,
                    "code": target_id,
                    "scope_id": scope_id,
                    "file_path": str(dest_path),
                    "file_offset": old_offset,
                    "byte_length": new_length,
                }
            except Exception:
                conn.rollback()
                raise

        # Handle rule/lesson proposal types (original logic)
        else:
            # Generate code
            if prop_type == "rule":
                code = next_rule_code(conn, scope_id)
            elif prop_type == "lesson":
                code = next_lesson_code(conn, scope_id)
            else:
                raise ValueError(f"Unknown proposal type: {prop_type}")

            # Build atomic block
            if prop_type == "rule":
                block_text = _build_rule_atomic_block(
                    code, scope_id, proposed_text, metadata
                )
            else:
                block_text = _build_lesson_atomic_block(
                    code, scope_id, proposed_text, metadata
                )

            # Determine destination file
            dest_path = _scope_to_file_path(scope_id, doc_type=prop_type)
            if not dest_path.exists():
                raise FileNotFoundError(
                    f"Destination file does not exist: {dest_path}"
                )

            # Append block
            file_offset, byte_length = _append_atomic_block(dest_path, block_text)

            # Insert into rules / lessons
            if prop_type == "rule":
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
            else:
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

            # Update proposal status
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
    finally:
        conn.close()


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

        # Update original rule status
        conn.execute(
            """
            UPDATE rules
            SET status = 'deprecated', updated_at = datetime('now')
            WHERE id = ?
            """,
            (rule_id,),
        )

        # Best-effort mark in source .md
        file_path = rule.get("file_path")
        file_offset = rule.get("file_offset")
        byte_length = rule.get("byte_length")
        if file_path and file_offset is not None and byte_length is not None:
            _mark_deprecated_in_md(file_path, file_offset, byte_length)

        # Register PROMOTED in history
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
    processed = 0
    skipped = 0
    errors = 0

    # --- Rules ---
    rule_sql = (
        "SELECT id, scope_id, code, text, category, severity, applies_to, tags "
        "FROM rules WHERE status = 'active' AND embedding_id IS NULL"
    )
    rule_params: list[object] = []
    if scope_id is not None:
        rule_sql += " AND scope_id = ?"
        rule_params.append(scope_id)

    cursor = conn.execute(rule_sql, rule_params)
    rule_rows = cursor.fetchall()
    rule_columns = [d[0] for d in cursor.description]

    if rule_rows:
        texts = [row[rule_columns.index("text")] for row in rule_rows]
        try:
            embeddings = embedder.generate_embeddings_batch(texts)
        except Exception as exc:
            errors += len(rule_rows)
            logger.exception("Failed to generate embeddings for rules: %s", exc)
            embeddings = []

        for idx, row in enumerate(rule_rows):
            if idx >= len(embeddings):
                errors += 1
                continue
            row_dict = dict(zip(rule_columns, row))
            rule_id = row_dict["id"]
            try:
                vector_store.upsert_rule(
                    rule_id=rule_id,
                    text=row_dict["text"],
                    embedding=embeddings[idx],
                    metadata={
                        "scope_id": row_dict["scope_id"],
                        "category": row_dict["category"],
                        "severity": row_dict["severity"],
                        "applies_to": row_dict.get("applies_to") or "",
                        "tags": row_dict.get("tags") or "[]",
                    },
                )
                text_hash = hashlib.sha256(row_dict["text"].encode()).hexdigest()[:16]
                conn.execute(
                    "UPDATE rules SET embedding_id = ? WHERE id = ?",
                    (text_hash, rule_id),
                )
                processed += 1
            except Exception as exc:
                errors += 1
                logger.exception("Failed to upsert rule %s: %s", rule_id, exc)
    skipped += len(rule_rows) - processed - errors

    # --- Lessons ---
    lesson_sql = (
        "SELECT id, scope_id, code, what_happened, severity, area_affected, tags "
        "FROM lessons WHERE status = 'active' AND embedding_id IS NULL"
    )
    lesson_params: list[object] = []
    if scope_id is not None:
        lesson_sql += " AND scope_id = ?"
        lesson_params.append(scope_id)

    cursor = conn.execute(lesson_sql, lesson_params)
    lesson_rows = cursor.fetchall()
    lesson_columns = [d[0] for d in cursor.description]

    lesson_processed = 0
    lesson_errors = 0
    if lesson_rows:
        texts = [
            row[lesson_columns.index("what_happened")] for row in lesson_rows
        ]
        try:
            embeddings = embedder.generate_embeddings_batch(texts)
        except Exception as exc:
            lesson_errors += len(lesson_rows)
            logger.exception("Failed to generate embeddings for lessons: %s", exc)
            embeddings = []

        for idx, row in enumerate(lesson_rows):
            if idx >= len(embeddings):
                lesson_errors += 1
                continue
            row_dict = dict(zip(lesson_columns, row))
            lesson_id = row_dict["id"]
            try:
                vector_store.upsert_lesson(
                    lesson_id=lesson_id,
                    text=row_dict["what_happened"],
                    embedding=embeddings[idx],
                    metadata={
                        "scope_id": row_dict["scope_id"],
                        "severity": row_dict["severity"] or "medium",
                        "area_affected": row_dict["area_affected"] or "",
                        "tags": row_dict.get("tags") or "[]",
                    },
                )
                text_hash = hashlib.sha256(row_dict["what_happened"].encode()).hexdigest()[:16]
                conn.execute(
                    "UPDATE lessons SET embedding_id = ? WHERE id = ?",
                    (text_hash, lesson_id),
                )
                lesson_processed += 1
            except Exception as exc:
                lesson_errors += 1
                logger.exception("Failed to upsert lesson %s: %s", lesson_id, exc)

    processed += lesson_processed
    errors += lesson_errors
    skipped += len(lesson_rows) - lesson_processed - lesson_errors

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

    # Add **Status:** deprecated after the header line
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
