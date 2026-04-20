"""Unit tests for scope_resolver."""

import sqlite3
from pathlib import Path

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.utils.scope_resolver import (
    filter_by_attributes,
    load_scope_attributes,
    resolve_scope_hierarchy,
)


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    kb_path = tmp_path
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)
    db_path = kb_path / "test.db"
    initialize_db(db_path)
    return get_connection(db_path)


def _insert_rule(conn: sqlite3.Connection, rule_id: str, code: str) -> None:
    conn.execute(
        """
        INSERT INTO rules (id, scope_id, code, text, category, severity)
        VALUES (?, 'global', ?, 'text', 'general', 'medium')
        """,
        (rule_id, code),
    )
    conn.commit()


def test_resolve_psp_integrator(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    result = resolve_scope_hierarchy(conn, "project-psp-integrator")
    assert result == ["project-psp-integrator", "global-quarkus", "global-java", "global"]


def test_resolve_pac_module(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    result = resolve_scope_hierarchy(conn, "project-pac-module")
    assert result == ["project-pac-module", "global-nestjs", "global"]


def test_resolve_nonexistent(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    with pytest.raises(ValueError, match="project-nonexistent"):
        resolve_scope_hierarchy(conn, "project-nonexistent")


def test_load_attributes_psp(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    result = load_scope_attributes(conn, "project-psp-integrator")
    assert result == {
        "framework": "quarkus",
        "component_role": "gateway",
        "runtime_version": "java-21",
    }


def test_load_attributes_empty(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    result = load_scope_attributes(conn, "global")
    assert result == {}


def test_filter_no_attributes(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _insert_rule(conn, "rule-001", "RN-GLOBAL-001")
    result = filter_by_attributes(conn, ["rule-001"], {"framework": "quarkus"})
    assert result == ["rule-001"]


def test_filter_matching_attributes(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _insert_rule(conn, "rule-002", "RN-GLOBAL-002")
    conn.execute(
        "INSERT INTO rule_attributes (rule_id, key, value) VALUES (?, 'framework', 'quarkus')",
        ("rule-002",),
    )
    conn.commit()
    result = filter_by_attributes(conn, ["rule-002"], {"framework": "quarkus"})
    assert result == ["rule-002"]


def test_filter_non_matching(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _insert_rule(conn, "rule-003", "RN-GLOBAL-003")
    conn.execute(
        "INSERT INTO rule_attributes (rule_id, key, value) VALUES (?, 'framework', 'nestjs')",
        ("rule-003",),
    )
    conn.commit()
    result = filter_by_attributes(conn, ["rule-003"], {"framework": "quarkus"})
    assert result == []


def test_filter_unknown_key(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _insert_rule(conn, "rule-004", "RN-GLOBAL-004")
    conn.execute(
        "INSERT INTO rule_attributes (rule_id, key, value) VALUES (?, 'team', 'payments')",
        ("rule-004",),
    )
    conn.commit()
    result = filter_by_attributes(conn, ["rule-004"], {"framework": "quarkus"})
    assert result == ["rule-004"]


def test_filter_and_logic(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    _insert_rule(conn, "rule-005", "RN-GLOBAL-005")
    conn.execute(
        "INSERT INTO rule_attributes (rule_id, key, value) VALUES (?, 'framework', 'quarkus')",
        ("rule-005",),
    )
    conn.execute(
        "INSERT INTO rule_attributes (rule_id, key, value) VALUES (?, 'component_role', 'gateway')",
        ("rule-005",),
    )
    conn.commit()

    # Proyecto con ambos atributos → incluida
    result = filter_by_attributes(
        conn, ["rule-005"], {"framework": "quarkus", "component_role": "gateway"}
    )
    assert result == ["rule-005"]

    # Proyecto solo con framework (sin component_role) → incluida (conservadora)
    result = filter_by_attributes(conn, ["rule-005"], {"framework": "quarkus"})
    assert result == ["rule-005"]

    # Proyecto con component_role=worker → excluida
    result = filter_by_attributes(
        conn, ["rule-005"], {"framework": "quarkus", "component_role": "worker"}
    )
    assert result == []
