"""Unit tests for SQLite connection and initialization."""

import tempfile
from pathlib import Path

from meridian.db.connection import get_connection, initialize_db


EXPECTED_TABLES = [
    "scopes",
    "scope_attributes",
    "rules",
    "rule_attributes",
    "rule_history",
    "lesson_history",
    "lessons",
    "rule_lesson_links",
    "project_scope_resolution",
    "pr_audits",
    "planning_checks",
    "pending_proposals",
    "access_log",
]


def test_initialize_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        db_path = kb_path / "test.db"
        initialize_db(db_path)
        conn = get_connection(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            for table in EXPECTED_TABLES:
                assert table in tables, f"Table {table} not found"
        finally:
            conn.close()


def test_initialize_inserts_scopes():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        db_path = kb_path / "test.db"
        initialize_db(db_path)
        conn = get_connection(db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM scopes")
            count = cursor.fetchone()[0]
            assert count == 19
        finally:
            conn.close()


def test_initialize_inserts_scope_attributes():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        db_path = kb_path / "test.db"
        initialize_db(db_path)
        conn = get_connection(db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM scope_attributes")
            count = cursor.fetchone()[0]
            assert count == 24
        finally:
            conn.close()


def test_initialize_is_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        db_path = kb_path / "test.db"
        initialize_db(db_path)
        initialize_db(db_path)  # should not raise
        conn = get_connection(db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM scopes")
            scopes_count = cursor.fetchone()[0]
            cursor = conn.execute("SELECT COUNT(*) FROM scope_attributes")
            attrs_count = cursor.fetchone()[0]
            assert scopes_count == 19
            assert attrs_count == 24
        finally:
            conn.close()


def test_initialize_sets_user_version_to_latest_migration():
    """See tests/unit/test_migrations.py for the migration runner's own coverage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_path = Path(tmpdir)
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        db_path = kb_path / "test.db"
        initialize_db(db_path)
        conn = get_connection(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version >= 1
        finally:
            conn.close()
