"""Migration runner: discovers NNN_*.sql files under db/migrations/, applies
those newer than the database's PRAGMA user_version, and backs up the
database file first so a failed migration can be recovered from manually.

See plan-rendimiento.md T01 / archy-rendimiento.md §7-Riesgo 2.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_MIGRATION_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def _discover_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    migrations = []
    for path in migrations_dir.glob("*.sql"):
        match = _MIGRATION_NAME_RE.match(path.name)
        if match is None:
            continue
        migrations.append((int(match.group(1)), path))
    return sorted(migrations, key=lambda item: item[0])


def _migration_statements(sql_text: str) -> list[str]:
    """Strip comment-only lines and split a migration file into statements."""
    lines = [
        line for line in sql_text.splitlines() if not line.strip().startswith("--")
    ]
    cleaned = "\n".join(lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _apply_migration(conn: sqlite3.Connection, number: int, path: Path) -> None:
    if number == 1:
        # Predates this runner: databases created after schema.sql already
        # defined these columns don't need the ALTER TABLE statements run.
        existing = _table_columns(conn, "lessons")
        required = {"source_type", "source_ref", "created_at", "updated_at"}
        if required <= existing:
            return

    for statement in _migration_statements(path.read_text(encoding="utf-8")):
        conn.execute(statement)

    if number == 2:
        from meridian.utils.id_generator import seed_id_counters

        seed_id_counters(conn)

    if number == 3:
        from meridian.utils.read_index import backfill_read_index

        backfill_read_index(conn)
        _verify_migration_003(conn)


def _verify_migration_003(conn: sqlite3.Connection) -> None:
    """Post-backfill check (plan-rendimiento.md T04 acceptance criteria):
    rule_tags/lesson_tags row counts match the parsed JSON tag arrays, and
    indexed_files has exactly one row per distinct existing file_path."""
    from meridian.utils.read_index import normalize_tag_list

    for table, tags_table in (("rules", "rule_tags"), ("lessons", "lesson_tags")):
        cursor = conn.execute(f"SELECT tags FROM {table}")  # noqa: S608
        expected = 0
        for (raw_tags,) in cursor.fetchall():
            expected += len(normalize_tag_list(raw_tags))

        actual = conn.execute(f"SELECT COUNT(*) FROM {tags_table}").fetchone()[0]  # noqa: S608
        if actual != expected:
            raise RuntimeError(
                f"Migration 003 verification failed: {tags_table} has "
                f"{actual} rows, expected {expected} from {table}.tags"
            )

    file_paths: set[str] = set()
    for table in ("rules", "lessons"):
        cursor = conn.execute(
            f"SELECT DISTINCT file_path FROM {table} WHERE file_path IS NOT NULL"  # noqa: S608
        )
        file_paths.update(row[0] for row in cursor.fetchall())
    existing_on_disk = sum(1 for p in file_paths if Path(p).exists())

    indexed_count = conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0]
    if indexed_count != existing_on_disk:
        raise RuntimeError(
            f"Migration 003 verification failed: indexed_files has "
            f"{indexed_count} rows, expected {existing_on_disk} existing files"
        )


def apply_pending_migrations(
    conn: sqlite3.Connection,
    db_path: Path,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[int]:
    """Apply every migration numbered above the database's user_version.

    Each migration runs in its own transaction. If one fails, it is rolled
    back, no later migration runs, and the exception message points at the
    pre-migration backup created before any changes were applied. Returns
    the list of migration numbers applied (empty if none were pending).
    """
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    pending = [
        (number, path)
        for number, path in _discover_migrations(migrations_dir)
        if number > current_version
    ]
    if not pending:
        return []

    backup_path = db_path.with_name(
        f"{db_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    )
    shutil.copy2(db_path, backup_path)

    applied: list[int] = []
    for number, path in pending:
        conn.execute("BEGIN")
        try:
            _apply_migration(conn, number, path)
            conn.execute(f"PRAGMA user_version = {number}")
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(
                f"Migration {number:03d} ({path.name}) failed and was rolled "
                f"back. Database backup available at: {backup_path}"
            ) from exc
        conn.commit()
        applied.append(number)

    return applied
