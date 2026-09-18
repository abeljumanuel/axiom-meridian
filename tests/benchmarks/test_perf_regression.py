"""Performance regression guards (plan-rendimiento.md T11).

Excluded from the default `uv run pytest` run (see the `benchmark` marker
and `addopts` in pyproject.toml) — run explicitly with:

    uv run pytest tests/benchmarks -m benchmark

Deviation from the plan: implemented with plain `time.perf_counter()`
instead of adding the `pytest-benchmark` dependency, to avoid touching
`uv.lock`/pyproject dependencies in an environment already documented as
fragile (reporte-instalacion.md). The numeric criteria are unchanged.

Two claims are checked:
1. `query_rules(detail="full")` cost is ~O(rows returned), not O(rows x
   file size) — the defect this whole effort (Option C) exists to fix.
2. `next_sequential_id` stays ~O(1) as `access_log` grows, via id_counters
   instead of `MAX(id) LIKE`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_consumption import query_rules
from meridian.tools.knowledge_management import index_rules_from_markdown
from meridian.utils.id_generator import next_sequential_id

pytestmark = pytest.mark.benchmark


def _kb(tmp_path) -> Path:
    kb_path = tmp_path / "kb"
    for d in (
        "knowledge-base/global",
        "knowledge-base/projects",
        "lessons/global",
        "lessons/projects",
    ):
        (kb_path / d).mkdir(parents=True)
    return kb_path


def _build_synthetic_rules_md(n: int) -> str:
    padding = (
        "Padding text to make each block a realistic size so the benchmark "
        "actually exercises file-size-proportional cost if it were present. "
    ) * 4
    blocks = [
        (
            f"## RN-BENCH-{i:04d}\n"
            "**Scope:** global\n"
            "**Categoría:** general\n"
            "**Severidad:** medium\n"
            "**Aplica a:** **/*\n"
            "**Tags:** bench\n"
            "**Fuente:** manual\n"
            f"**Regla:** Synthetic rule number {i}. {padding}\n"
        )
        for i in range(n)
    ]
    return "\n\n".join(blocks)


def _timed_query_rules_full(kb_path: Path, n_rules: int) -> float:
    md_path = kb_path / "knowledge-base" / "global" / "bench.md"
    md_path.write_text(_build_synthetic_rules_md(n_rules))
    index_rules_from_markdown(str(md_path), default_scope_id="global", mode="atomic")

    start = time.perf_counter()
    result = query_rules("global", detail="full")
    elapsed = time.perf_counter() - start

    data = json.loads(result)
    assert len(data) == n_rules
    assert all(r.get("error") is None for r in data)
    return elapsed


def test_query_rules_full_scales_with_rows_not_file_size(tmp_path, monkeypatch):
    kb_path = _kb(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    initialize_db(kb_path / "meridian.db")

    small_time = _timed_query_rules_full(kb_path, 100)
    large_time = _timed_query_rules_full(kb_path, 2000)

    small_per_row = small_time / 100
    large_per_row = large_time / 2000

    # T11 criterion: per-row cost at 2000 rows must not exceed 2x the
    # per-row cost at 100 rows. Under the old per-row read_bytes() bug,
    # per-row cost would grow with total file size (20x more rows AND each
    # read touches a file ~20x bigger) — nowhere near this bound.
    assert large_per_row <= small_per_row * 2 + 1e-6, (
        f"per-row cost regressed: {small_per_row:.6f}s @100 rows vs "
        f"{large_per_row:.6f}s @2000 rows"
    )


def test_next_sequential_id_stays_o1_as_access_log_grows(tmp_path, monkeypatch):
    kb_path = _kb(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    db_path = kb_path / "meridian.db"
    initialize_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.executemany(
            "INSERT INTO access_log (id, tool_name, access_level, result) "
            "VALUES (?, 'query_rules', 'read', 'success')",
            [(f"al-{i:05d}",) for i in range(1, 101)],
        )
        conn.commit()

        start = time.perf_counter()
        next_sequential_id(conn, "access_log", "al")
        small_time = time.perf_counter() - start

        conn.executemany(
            "INSERT INTO access_log (id, tool_name, access_level, result) "
            "VALUES (?, 'query_rules', 'read', 'success')",
            [(f"al-{i:06d}",) for i in range(101, 50001)],
        )
        conn.commit()

        start = time.perf_counter()
        next_sequential_id(conn, "access_log", "al")
        large_time = time.perf_counter() - start

        # T11 criterion: cost at 50,000 rows must not exceed 1.5x the cost
        # at 100 rows — id_counters is a single indexed UPDATE regardless
        # of access_log size, unlike the old MAX(id) LIKE full scan.
        assert large_time <= small_time * 1.5 + 1e-3, (
            f"next_sequential_id regressed: {small_time:.6f}s @100 rows vs "
            f"{large_time:.6f}s @50000 rows"
        )
    finally:
        conn.close()


def test_rule_history_lookup_uses_index_not_scan(tmp_path, monkeypatch):
    kb_path = _kb(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    db_path = kb_path / "meridian.db"
    initialize_db(db_path)
    conn = get_connection(db_path)
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM rule_history WHERE rule_id = ?",
            ("RN-BENCH-0001",),
        ).fetchall()
        plan_text = " ".join(str(row) for row in plan)
        assert "idx_rule_history_rule_id" in plan_text
        assert "SCAN" not in plan_text.upper() or "USING INDEX" in plan_text.upper()
    finally:
        conn.close()
