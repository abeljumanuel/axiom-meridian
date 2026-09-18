"""Contract tests for the indexed read path's STALE_INDEX behavior
(archy-rendimiento.md §7-Riesgo 1 and 3; plan-rendimiento.md T07).

Two properties must hold:
1. An edit made outside Meridian (a human editing a .md by hand) must never
   result in stale text being served — the next query returns STALE_INDEX
   for every row backed by that file, never old SQLite text.
2. Re-indexing the edited file recovers normal service.

Response *shape* is unchanged from before ADR-005: `text` and, when stale,
`error: "STALE_INDEX"` still appear per row in the serialized payload
(ADR-001) — what changed is the granularity at which staleness is detected
(per-file, not per-row-offset), not the contract's shape.
"""

from __future__ import annotations

import json
import shutil

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_consumption import query_rules
from meridian.tools.knowledge_management import index_rules_from_markdown


@pytest.fixture
def tmp_kb(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb"
    kb_path.mkdir()
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)

    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def _index_java_fixture(kb_path) -> str:
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")
    return filepath


def test_query_after_indexing_serves_fresh_text_with_no_error(tmp_kb):
    kb_path, _conn = tmp_kb
    _index_java_fixture(kb_path)

    data = json.loads(query_rules("global-java", detail="full"))

    assert len(data) == 3
    for row in data:
        assert row["text"]
        assert "error" not in row


def test_external_edit_produces_stale_index_for_every_row_of_that_file(tmp_kb):
    """The whole point of file-granularity: editing one file marks *all*
    rows backed by it stale, not just the row whose bytes moved."""
    kb_path, _conn = tmp_kb
    filepath = _index_java_fixture(kb_path)

    # Simulate a human editing the file directly, bypassing Meridian.
    original = open(filepath, encoding="utf-8").read()
    open(filepath, "w", encoding="utf-8").write(original + "\n<!-- edited by hand -->\n")

    data = json.loads(query_rules("global-java", detail="full"))

    assert len(data) == 3
    for row in data:
        assert row["text"] is None
        assert row["error"] == "STALE_INDEX"


def test_reindexing_after_external_edit_recovers_service(tmp_kb):
    kb_path, _conn = tmp_kb
    filepath = _index_java_fixture(kb_path)

    original = open(filepath, encoding="utf-8").read()
    open(filepath, "w", encoding="utf-8").write(original + "\n<!-- edited -->\n")

    stale = json.loads(query_rules("global-java", detail="full"))
    assert all(r.get("error") == "STALE_INDEX" for r in stale)

    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    fresh = json.loads(query_rules("global-java", detail="full"))
    assert len(fresh) == 3
    for row in fresh:
        assert row["text"]
        assert "error" not in row
