"""Unit tests for `python -m meridian index` (src/meridian/__main__.py).

Exercises the CLI entry point that scripts/install.sh's optional seed step
relies on to load the repo's example knowledge-base/*.md files into a
freshly installed KNOWLEDGE_BASE_PATH.
"""

from __future__ import annotations

import json
import sys

import pytest

from meridian.__main__ import main
from meridian.db.connection import get_connection
from meridian.config import get_db_path


@pytest.fixture
def tmp_kb(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb"
    for d in (
        "knowledge-base/global",
        "knowledge-base/projects",
        "lessons/global",
        "lessons/projects",
    ):
        (kb_path / d).mkdir(parents=True)
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    return kb_path


def _run_cli(monkeypatch, args: list[str]) -> str:
    monkeypatch.setattr(sys, "argv", ["meridian", *args])
    return main()


def test_index_rules_atomic_file(tmp_kb, monkeypatch, capsys):
    rules_md = tmp_kb / "knowledge-base" / "global" / "test-rules.md"
    rules_md.write_text(
        "## RN-GLOBAL-900\n"
        "**Scope:** global\n"
        "**Categoría:** naming\n"
        "**Severidad:** medium\n"
        "**Aplica a:** *\n"
        "**Tags:** cli-test\n"
        "**Fuente:** unit-test\n"
        "**Regla:** Use descriptive names.\n"
    )

    _run_cli(monkeypatch, ["index", "rules", str(rules_md), "--scope", "global"])

    output = json.loads(capsys.readouterr().out)
    assert output["indexed"] == 1
    assert output["created"] == 1

    conn = get_connection(get_db_path())
    try:
        row = conn.execute(
            "SELECT scope_id, text FROM rules WHERE code = 'RN-GLOBAL-900'"
        ).fetchone()
        assert row == ("global", "Use descriptive names.")
    finally:
        conn.close()


def test_index_lessons_atomic_file(tmp_kb, monkeypatch, capsys):
    lessons_md = tmp_kb / "lessons" / "global" / "test-lessons.md"
    lessons_md.write_text(
        "## LL-GLOBAL-900\n"
        "**Scope:** global\n"
        "**Proyecto:** test\n"
        "**Fecha:** 2026-01-01\n"
        "**Severidad del impacto:** medium\n"
        "**Área afectada:** ci\n"
        "**Tags:** cli-test\n"
        "**Qué pasó:** A test lesson happened.\n"
        "**Impacto:** none\n"
        "**Causa raíz:** testing\n"
        "**Resolución:** n/a\n"
        "**Originó regla:** \n"
    )

    _run_cli(monkeypatch, ["index", "lessons", str(lessons_md), "--scope", "global"])

    output = json.loads(capsys.readouterr().out)
    assert output["indexed"] == 1
    assert output["created"] == 1

    conn = get_connection(get_db_path())
    try:
        row = conn.execute(
            "SELECT scope_id FROM lessons WHERE code = 'LL-GLOBAL-900'"
        ).fetchone()
        assert row == ("global",)
    finally:
        conn.close()


def test_index_unknown_doc_type_exits(tmp_kb, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, ["index", "bogus", "somefile.md", "--scope", "global"])
    assert "Unknown index doc_type" in capsys.readouterr().out


def test_index_missing_scope_flag_exits(tmp_kb, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, ["index", "rules", "somefile.md"])
    assert "Usage: python -m meridian index" in capsys.readouterr().out
