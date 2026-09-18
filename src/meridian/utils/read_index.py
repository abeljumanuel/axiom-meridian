"""Read-index maintenance: indexed_files freshness tracking, rule_tags /
lesson_tags normalization, and the single write helper that keeps a
knowledge .md file and its indexed_files row from ever drifting apart.

See archy-rendimiento.md (Opción C) and plan-rendimiento.md T04-T06.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def normalize_tag_list(tags: object) -> list[str]:
    """Normalize a tags value (list, JSON string, or comma string) to a
    sorted, de-duplicated list of non-empty stripped tags."""
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = tags.split(",")
    if not isinstance(tags, list):
        return []
    return sorted({str(t).strip() for t in tags if str(t).strip()})


def refresh_indexed_file(conn: sqlite3.Connection, path: Path) -> None:
    """(Re)compute the mtime/content_hash fingerprint of `path` already on
    disk and upsert it into indexed_files. Used after indexing a file we
    didn't just write ourselves (index_rules_from_markdown /
    index_lessons_from_markdown)."""
    stat = path.stat()
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    conn.execute(
        """
        INSERT INTO indexed_files (file_path, mtime, content_hash)
        VALUES (?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            mtime = excluded.mtime,
            content_hash = excluded.content_hash,
            updated_at = datetime('now')
        """,
        (str(path), stat.st_mtime, content_hash),
    )


def write_block(conn: sqlite3.Connection, dest_path: Path, new_content: bytes) -> None:
    """The single place a knowledge .md file's bytes are written to disk.

    Writes `new_content` to `dest_path` and updates its indexed_files row
    (hash of the bytes just written, no extra read) in the same call, so
    indexed_files can never drift from what a Meridian-driven write produced
    (archy-rendimiento.md §7-Riesgo 1). Every writer of a knowledge .md file
    — append, in-place update, deprecation marking — must go through this.
    """
    dest_path.write_bytes(new_content)
    stat = dest_path.stat()
    content_hash = hashlib.sha256(new_content).hexdigest()
    conn.execute(
        """
        INSERT INTO indexed_files (file_path, mtime, content_hash)
        VALUES (?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            mtime = excluded.mtime,
            content_hash = excluded.content_hash,
            updated_at = datetime('now')
        """,
        (str(dest_path), stat.st_mtime, content_hash),
    )


def sync_tags(
    conn: sqlite3.Connection, table: str, id_column: str, entity_id: str, tags: object
) -> None:
    """Replace the normalized tag set for one rule/lesson in rule_tags/lesson_tags.

    `table` must be "rule_tags" or "lesson_tags" (never user input) and
    `id_column` "rule_id" or "lesson_id" — both are fixed call-site literals,
    not attacker-controlled, so building the statement with an f-string is
    safe here (same pattern as the rest of this codebase's dynamic-table
    helpers, e.g. next_sequential_id).
    """
    conn.execute(f"DELETE FROM {table} WHERE {id_column} = ?", (entity_id,))  # noqa: S608
    for tag in normalize_tag_list(tags):
        conn.execute(
            f"INSERT INTO {table} ({id_column}, tag) VALUES (?, ?)",  # noqa: S608
            (entity_id, tag),
        )


def check_files_fresh(conn: sqlite3.Connection, file_paths: list[str]) -> dict[str, bool]:
    """One freshness check per DISTINCT file, not one read per row.

    mtime is the fast path: if it still matches indexed_files.mtime, the
    file is considered fresh without reading its content. If it differs,
    sha256 of the current content is the arbiter. A file missing from
    indexed_files, or no longer present on disk, is never fresh.

    Known limitation: an external edit that both changes content and resets
    mtime back to the exact indexed value (e.g. via os.utime) is not caught
    by the fast path — this mirrors any mtime-based freshness check (make,
    bundler caches, ...). Documented in ADR-005 rather than silently
    hashing on every call, which would defeat the point of the fast path.
    """
    result: dict[str, bool] = {}
    distinct_paths = {p for p in file_paths if p}
    if not distinct_paths:
        return result

    placeholders = ", ".join("?" for _ in distinct_paths)
    cursor = conn.execute(
        "SELECT file_path, mtime, content_hash FROM indexed_files "
        f"WHERE file_path IN ({placeholders})",  # noqa: S608
        list(distinct_paths),
    )
    indexed = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

    for file_path in distinct_paths:
        path = Path(file_path)
        entry = indexed.get(file_path)
        if entry is None:
            result[file_path] = False
            continue

        try:
            stat = path.stat()  # single syscall covers existence + mtime
        except OSError:
            result[file_path] = False
            continue

        expected_mtime, expected_hash = entry
        if stat.st_mtime == expected_mtime:
            result[file_path] = True
            continue

        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        result[file_path] = actual_hash == expected_hash

    return result


def backfill_read_index(conn: sqlite3.Connection) -> dict[str, int]:
    """One-time backfill for migration 003: populate rule_tags/lesson_tags
    from the existing `tags` JSON columns, and indexed_files from the
    file_path values already referenced by rules/lessons.

    Idempotent (INSERT OR IGNORE / upsert throughout) and a no-op on an
    empty database. Returns counts for the migration's post-checks.
    """
    tag_rows_inserted = 0
    for table, id_column, tags_table in (
        ("rules", "rule_id", "rule_tags"),
        ("lessons", "lesson_id", "lesson_tags"),
    ):
        cursor = conn.execute(f"SELECT id, tags FROM {table}")  # noqa: S608
        for entity_id, raw_tags in cursor.fetchall():
            tags = normalize_tag_list(raw_tags)
            for tag in tags:
                conn.execute(
                    f"INSERT OR IGNORE INTO {tags_table} ({id_column}, tag) "  # noqa: S608
                    "VALUES (?, ?)",
                    (entity_id, tag),
                )
                tag_rows_inserted += 1

    file_paths: set[str] = set()
    for table in ("rules", "lessons"):
        cursor = conn.execute(
            f"SELECT DISTINCT file_path FROM {table} WHERE file_path IS NOT NULL"  # noqa: S608
        )
        file_paths.update(row[0] for row in cursor.fetchall())

    files_indexed = 0
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            # Referenced but missing: consultas devolverán STALE_INDEX para
            # este archivo, igual que hoy con path.exists() (§4-C).
            continue
        refresh_indexed_file(conn, path)
        files_indexed += 1

    return {
        "tag_rows_inserted": tag_rows_inserted,
        "files_indexed": files_indexed,
        "files_referenced": len(file_paths),
    }
