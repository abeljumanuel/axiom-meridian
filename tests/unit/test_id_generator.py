"""Unit tests for ID generators."""

import sqlite3
import tempfile
from pathlib import Path

from meridian.db.connection import get_connection, initialize_db
from meridian.utils.id_generator import (
    next_lesson_code,
    next_rule_code,
    next_sequential_id,
)


def _temp_db():
    tmpdir = tempfile.mkdtemp()
    kb_path = Path(tmpdir)
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)
    db_path = kb_path / "test.db"
    initialize_db(db_path)
    return get_connection(db_path)


def test_next_rule_code_first_rule():
    conn = _temp_db()
    try:
        result = next_rule_code(conn, "global-java")
        assert result == "RN-JAVA-001"
    finally:
        conn.close()


def test_next_rule_code_increments():
    conn = _temp_db()
    try:
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity) VALUES (?, ?, ?, ?, ?, ?)",
            ("r1", "global-java", "RN-JAVA-005", "text", "cat", "sev"),
        )
        conn.commit()
        result = next_rule_code(conn, "global-java")
        assert result == "RN-JAVA-006"
    finally:
        conn.close()


def test_next_lesson_code():
    conn = _temp_db()
    try:
        result = next_lesson_code(conn, "project-project-example")
        assert result == "LL-PSP-001"
    finally:
        conn.close()


def test_next_sequential_id():
    conn = _temp_db()
    try:
        result = next_sequential_id(conn, "pending_proposals", "prop")
        assert result == "prop-0001"
    finally:
        conn.close()


def test_scope_id_global():
    conn = _temp_db()
    try:
        result = next_rule_code(conn, "global")
        assert result == "RN-GLOBAL-001"
    finally:
        conn.close()
