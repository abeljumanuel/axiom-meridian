"""Unit tests for the migration runner (db/migrations.py).

Covers T01's acceptance criteria: no-op on a fresh DB, applying migration
001 on a pre-runner legacy DB, idempotent re-runs (no duplicate backups,
user_version unchanged), and rollback-with-backup on a failing migration.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.db.migrations import apply_pending_migrations


def _kb_dirs(kb_path: Path) -> None:
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)


def _write_migration(migrations_dir: Path, number: int, name: str, sql: str) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / f"{number:03d}_{name}.sql").write_text(sql, encoding="utf-8")


def test_fresh_database_ends_up_with_no_pending_migrations():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "test.db"
        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            applied = apply_pending_migrations(conn, db_path)
            assert applied == []  # nothing pending — already applied by initialize_db
        finally:
            conn.close()


def test_legacy_database_gets_migration_001_applied():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "legacy.db"

        # Simulate a database created before migration 001 / this runner
        # existed: `scopes` is present (initialize_db skips schema.sql), the
        # other core tables exist (as they would in any real pre-runner
        # database) but empty, and `lessons` lacks
        # source_type/source_ref/created_at/updated_at.
        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE scopes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
            "parent_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES "
            "('global-nestjs', 'global', 'Global NestJS', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE scope_attributes (scope_id TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (scope_id, key))"
        )
        legacy_conn.execute(
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, scope_id TEXT, code TEXT, "
            "tags TEXT, file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY, code TEXT, tags TEXT, "
            "file_path TEXT)"
        )
        legacy_conn.execute("CREATE TABLE access_log (id TEXT PRIMARY KEY)")
        legacy_conn.execute(
            "CREATE TABLE pending_proposals (id TEXT PRIMARY KEY, scope_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE rule_history (id TEXT PRIMARY KEY, rule_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE lesson_history (id TEXT PRIMARY KEY, lesson_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE pr_audits (id TEXT PRIMARY KEY, pr_ref TEXT, project_id TEXT)"
        )
        legacy_conn.execute("CREATE TABLE planning_checks (id TEXT PRIMARY KEY)")
        legacy_conn.commit()
        legacy_conn.close()

        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(lessons)")}
            for col in ("source_type", "source_ref", "created_at", "updated_at"):
                assert col in columns

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version >= 1

            backups = list(kb_path.glob("legacy.db.bak-*"))
            assert len(backups) == 1
        finally:
            conn.close()


def test_legacy_database_gets_nodejs_python_scopes_applied():
    """Migration 004: new Node.js/Python scopes get backfilled onto an
    existing database, and pre-existing global-nestjs gets re-parented
    under the new global-nodejs umbrella."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "legacy.db"

        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE scopes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
            "parent_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES "
            "('global-nestjs', 'global', 'Global NestJS', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE scope_attributes (scope_id TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (scope_id, key))"
        )
        legacy_conn.execute(
            "INSERT INTO scope_attributes VALUES "
            "('global-nestjs', 'framework', 'nestjs')"
        )
        legacy_conn.execute(
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, scope_id TEXT, code TEXT, "
            "tags TEXT, file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY, code TEXT, tags TEXT, "
            "file_path TEXT)"
        )
        legacy_conn.execute("CREATE TABLE access_log (id TEXT PRIMARY KEY)")
        legacy_conn.execute(
            "CREATE TABLE pending_proposals (id TEXT PRIMARY KEY, scope_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE rule_history (id TEXT PRIMARY KEY, rule_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE lesson_history (id TEXT PRIMARY KEY, lesson_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE pr_audits (id TEXT PRIMARY KEY, pr_ref TEXT, project_id TEXT)"
        )
        legacy_conn.execute("CREATE TABLE planning_checks (id TEXT PRIMARY KEY)")
        legacy_conn.commit()
        legacy_conn.close()

        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            new_scope_ids = {
                row[0]
                for row in conn.execute(
                    "SELECT id FROM scopes WHERE id IN "
                    "('global-nodejs', 'global-express', 'global-adonisjs', "
                    "'global-react', 'global-python', 'global-fastmcp', "
                    "'project-axiom-meridian')"
                )
            }
            assert new_scope_ids == {
                "global-nodejs",
                "global-express",
                "global-adonisjs",
                "global-react",
                "global-python",
                "global-fastmcp",
                "project-axiom-meridian",
            }

            nestjs_parent = conn.execute(
                "SELECT parent_id FROM scopes WHERE id = 'global-nestjs'"
            ).fetchone()[0]
            assert nestjs_parent == "global-nodejs"

            axiom_attrs = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT key, value FROM scope_attributes "
                    "WHERE scope_id = 'project-axiom-meridian'"
                )
            }
            assert axiom_attrs == {
                "framework": "fastmcp",
                "component_role": "mcp-server",
                "runtime_version": "python-3.11",
            }
        finally:
            conn.close()


def test_legacy_database_with_existing_lessons_rows_migrates_without_error():
    """Regression test: SQLite rejects ALTER TABLE ADD COLUMN with a
    non-constant default (e.g. DEFAULT (datetime('now'))) once the table
    has any rows — exactly the realistic "field database" case. Migration
    001 must add the columns without that default and backfill via UPDATE
    instead (see 001_lessons_columns.sql)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "legacy_populated.db"

        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE scopes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
            "parent_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES "
            "('global-nestjs', 'global', 'Global NestJS', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE scope_attributes (scope_id TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (scope_id, key))"
        )
        legacy_conn.execute(
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, scope_id TEXT, code TEXT, "
            "what_happened TEXT, tags TEXT, file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY, code TEXT, tags TEXT, "
            "file_path TEXT)"
        )
        legacy_conn.execute("CREATE TABLE access_log (id TEXT PRIMARY KEY)")
        legacy_conn.execute(
            "CREATE TABLE pending_proposals (id TEXT PRIMARY KEY, scope_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE rule_history (id TEXT PRIMARY KEY, rule_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE lesson_history (id TEXT PRIMARY KEY, lesson_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE pr_audits (id TEXT PRIMARY KEY, pr_ref TEXT, project_id TEXT)"
        )
        legacy_conn.execute("CREATE TABLE planning_checks (id TEXT PRIMARY KEY)")
        # The critical part of this fixture: at least one existing row.
        legacy_conn.execute(
            "INSERT INTO lessons (id, scope_id, code, what_happened) "
            "VALUES ('LL-GLOBAL-001', 'global', 'LL-GLOBAL-001', 'It happened.')"
        )
        legacy_conn.commit()
        legacy_conn.close()

        initialize_db(db_path)  # must not raise

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT source_type, source_ref, created_at, updated_at "
                "FROM lessons WHERE id = 'LL-GLOBAL-001'"
            ).fetchone()
            assert row[2] is not None  # created_at backfilled, not NULL
            assert row[3] is not None  # updated_at backfilled, not NULL
        finally:
            conn.close()


def test_rerunning_the_runner_is_idempotent_and_does_not_duplicate_backups():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "test.db"
        initialize_db(db_path)  # first run applies pending migrations + backs up

        conn = get_connection(db_path)
        try:
            version_before = conn.execute("PRAGMA user_version").fetchone()[0]
            backups_before = list(kb_path.glob("test.db.bak-*"))

            applied = apply_pending_migrations(conn, db_path)

            version_after = conn.execute("PRAGMA user_version").fetchone()[0]
            backups_after = list(kb_path.glob("test.db.bak-*"))

            assert applied == []
            assert version_after == version_before
            assert len(backups_after) == len(backups_before)
        finally:
            conn.close()


def test_failing_migration_rolls_back_and_leaves_a_backup():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "test.db"
        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            version_before = conn.execute("PRAGMA user_version").fetchone()[0]

            migrations_dir = kb_path / "fake_migrations"
            _write_migration(
                migrations_dir,
                version_before + 10,
                "broken",
                "THIS IS NOT VALID SQL;",
            )

            with pytest.raises(RuntimeError, match="failed and was rolled back"):
                apply_pending_migrations(conn, db_path, migrations_dir=migrations_dir)

            version_after = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version_after == version_before  # rolled back, not advanced

            backups = list(kb_path.glob("test.db.bak-*"))
            assert len(backups) == 1
        finally:
            conn.close()


def test_legacy_database_gets_deprecation_lifecycle_columns_applied():
    """Migration 005: superseded_by gets added to rule_history/lesson_history
    and idx_lessons_status gets created on a database that predates it,
    without disturbing existing history rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "legacy.db"

        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE scopes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
            "parent_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES "
            "('global-nestjs', 'global', 'Global NestJS', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE scope_attributes (scope_id TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (scope_id, key))"
        )
        legacy_conn.execute(
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, scope_id TEXT, code TEXT, "
            "tags TEXT, file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY, code TEXT, tags TEXT, "
            "file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute("CREATE TABLE access_log (id TEXT PRIMARY KEY)")
        legacy_conn.execute(
            "CREATE TABLE pending_proposals (id TEXT PRIMARY KEY, scope_id TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE rule_history (id TEXT PRIMARY KEY, rule_id TEXT, "
            "change_type TEXT, reason TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO rule_history (id, rule_id, change_type, reason) "
            "VALUES ('rh-0001', 'RN-GLOBAL-001', 'PROMOTED', "
            "'Promoted to scope global-java')"
        )
        legacy_conn.execute(
            "CREATE TABLE lesson_history (id TEXT PRIMARY KEY, lesson_id TEXT, "
            "change_type TEXT, reason TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE pr_audits (id TEXT PRIMARY KEY, pr_ref TEXT, project_id TEXT)"
        )
        legacy_conn.execute("CREATE TABLE planning_checks (id TEXT PRIMARY KEY)")
        legacy_conn.commit()
        legacy_conn.close()

        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            rule_hist_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(rule_history)")
            }
            lesson_hist_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(lesson_history)")
            }
            assert "superseded_by" in rule_hist_columns
            assert "superseded_by" in lesson_hist_columns

            # Pre-existing history row is untouched, superseded_by defaults
            # to NULL rather than anything inferred from its free-text reason.
            row = conn.execute(
                "SELECT reason, superseded_by FROM rule_history WHERE id = 'rh-0001'"
            ).fetchone()
            assert row[0] == "Promoted to scope global-java"
            assert row[1] is None

            indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(lessons)")
            }
            assert "idx_lessons_status" in indexes

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version >= 5
        finally:
            conn.close()


def test_fresh_database_has_deprecation_lifecycle_schema():
    """A fresh db init (schema.sql path) matches what migration 005 gives
    an existing database: superseded_by on both history tables and
    idx_lessons_status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "fresh.db"
        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            rule_hist_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(rule_history)")
            }
            lesson_hist_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(lesson_history)")
            }
            assert "superseded_by" in rule_hist_columns
            assert "superseded_by" in lesson_hist_columns

            indexes = {
                row[1] for row in conn.execute("PRAGMA index_list(lessons)")
            }
            assert "idx_lessons_status" in indexes
        finally:
            conn.close()


def test_legacy_database_gets_actor_identity_columns_applied():
    """Migration 006: actor_id gets added to pending_proposals, rule_history,
    lesson_history, and access_log on a database that predates it, leaving
    existing rows with actor_id = NULL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "legacy.db"

        legacy_conn = sqlite3.connect(str(db_path))
        legacy_conn.execute(
            "CREATE TABLE scopes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
            "parent_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO scopes VALUES "
            "('global-nestjs', 'global', 'Global NestJS', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE scope_attributes (scope_id TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (scope_id, key))"
        )
        legacy_conn.execute(
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, scope_id TEXT, code TEXT, "
            "tags TEXT, file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY, code TEXT, tags TEXT, "
            "file_path TEXT, status TEXT DEFAULT 'active')"
        )
        legacy_conn.execute(
            "CREATE TABLE access_log (id TEXT PRIMARY KEY, tool_name TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO access_log (id, tool_name) VALUES ('al-0001', 'query_rules')"
        )
        legacy_conn.execute(
            "CREATE TABLE pending_proposals (id TEXT PRIMARY KEY, scope_id TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO pending_proposals (id, scope_id) VALUES ('pp-0001', 'global')"
        )
        legacy_conn.execute(
            "CREATE TABLE rule_history (id TEXT PRIMARY KEY, rule_id TEXT, "
            "change_type TEXT, reason TEXT)"
        )
        legacy_conn.execute(
            "INSERT INTO rule_history (id, rule_id, change_type, reason) "
            "VALUES ('rh-0001', 'RN-GLOBAL-001', 'PROMOTED', "
            "'Promoted to scope global-java')"
        )
        legacy_conn.execute(
            "CREATE TABLE lesson_history (id TEXT PRIMARY KEY, lesson_id TEXT, "
            "change_type TEXT, reason TEXT)"
        )
        legacy_conn.execute(
            "CREATE TABLE pr_audits (id TEXT PRIMARY KEY, pr_ref TEXT, project_id TEXT)"
        )
        legacy_conn.execute("CREATE TABLE planning_checks (id TEXT PRIMARY KEY)")
        legacy_conn.commit()
        legacy_conn.close()

        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            for table in (
                "pending_proposals",
                "rule_history",
                "lesson_history",
                "access_log",
            ):
                columns = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                assert "actor_id" in columns

            # Pre-existing rows are untouched other than the new NULL column.
            assert conn.execute(
                "SELECT actor_id FROM access_log WHERE id = 'al-0001'"
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT actor_id FROM pending_proposals WHERE id = 'pp-0001'"
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT reason, actor_id FROM rule_history WHERE id = 'rh-0001'"
            ).fetchone() == ("Promoted to scope global-java", None)

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version >= 6
        finally:
            conn.close()


def test_fresh_database_has_actor_identity_schema():
    """A fresh db init (schema.sql path) matches what migration 006 gives an
    existing database: actor_id on all four attribution-relevant tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "fresh.db"
        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            for table in (
                "pending_proposals",
                "rule_history",
                "lesson_history",
                "access_log",
            ):
                columns = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                assert "actor_id" in columns
        finally:
            conn.close()


def test_partial_failure_keeps_earlier_successful_migrations_committed():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        _kb_dirs(kb_path)
        db_path = kb_path / "test.db"
        initialize_db(db_path)

        conn = get_connection(db_path)
        try:
            version_before = conn.execute("PRAGMA user_version").fetchone()[0]

            # Numbers chosen well above 1/2, which are special-cased in
            # meridian.db.migrations for the real 001/002 migrations.
            migrations_dir = kb_path / "fake_migrations"
            _write_migration(
                migrations_dir,
                version_before + 10,
                "good",
                "CREATE TABLE canary (id TEXT PRIMARY KEY);",
            )
            _write_migration(
                migrations_dir,
                version_before + 11,
                "broken",
                "THIS IS NOT VALID SQL;",
            )

            with pytest.raises(RuntimeError):
                apply_pending_migrations(conn, db_path, migrations_dir=migrations_dir)

            version_after = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version_after == version_before + 10  # the good one stuck

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "canary" in tables
        finally:
            conn.close()
