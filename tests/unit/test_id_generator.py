"""Unit tests for ID generators.

Since T03 (plan-rendimiento.md), IDs are allocated from the id_counters
table rather than scanning MAX(id) LIKE 'prefix-%' on the target table, so
codes inserted directly (bypassing next_rule_code/next_lesson_code/
next_sequential_id) are no longer reflected automatically — that data must
go through seed_id_counters first, exactly as the 002 migration does for
databases with pre-existing data.
"""

import tempfile
from pathlib import Path

from meridian.db.connection import get_connection, initialize_db
from meridian.utils.id_generator import (
    next_lesson_code,
    next_rule_code,
    next_sequential_id,
    seed_id_counters,
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


def test_next_rule_code_increments_across_consecutive_calls():
    conn = _temp_db()
    try:
        first = next_rule_code(conn, "global-java")
        second = next_rule_code(conn, "global-java")
        third = next_rule_code(conn, "global-java")
        assert [first, second, third] == ["RN-JAVA-001", "RN-JAVA-002", "RN-JAVA-003"]
    finally:
        conn.close()


def test_next_rule_code_after_seeding_from_existing_data():
    """Mirrors the 002 migration: existing rows seed the counter so the next
    generated code continues after the real maximum, never colliding."""
    conn = _temp_db()
    try:
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("r1", "global-java", "RN-JAVA-005", "text", "cat", "sev"),
        )
        conn.commit()
        seed_id_counters(conn)

        result = next_rule_code(conn, "global-java")
        assert result == "RN-JAVA-006"
    finally:
        conn.close()


def test_next_lesson_code():
    conn = _temp_db()
    try:
        result = next_lesson_code(conn, "project-project-example")
        assert result == "LL-PROJECT-001"
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


def test_consecutive_generations_never_repeat():
    conn = _temp_db()
    try:
        ids = {next_sequential_id(conn, "pending_proposals", "prop") for _ in range(50)}
        assert len(ids) == 50
    finally:
        conn.close()


def test_padding_overflow_stays_unique_and_increasing():
    """Crossing the 4-digit padding boundary (…9999 -> …10000) must not
    collide or go backwards (reporte-rendimiento.md §3.3)."""
    conn = _temp_db()
    try:
        conn.execute(
            "INSERT INTO id_counters (name, next) VALUES ('prop', 9999)"
        )
        conn.commit()

        generated = [next_sequential_id(conn, "pending_proposals", "prop") for _ in range(3)]

        assert generated == ["prop-9999", "prop-10000", "prop-10001"]
        assert len(set(generated)) == len(generated)
    finally:
        conn.close()


def test_seed_id_counters_is_noop_on_empty_database():
    conn = _temp_db()
    try:
        seed_id_counters(conn)  # must not raise on a fresh, empty DB
        result = next_rule_code(conn, "global-java")
        assert result == "RN-JAVA-001"
    finally:
        conn.close()


def test_seed_id_counters_never_lowers_an_advanced_counter():
    conn = _temp_db()
    try:
        # Advance the counter past what seeding from (empty) data would produce.
        for _ in range(3):
            next_rule_code(conn, "global-java")

        seed_id_counters(conn)  # no rules exist yet, so seeding sees nothing

        result = next_rule_code(conn, "global-java")
        assert result == "RN-JAVA-004"
    finally:
        conn.close()
