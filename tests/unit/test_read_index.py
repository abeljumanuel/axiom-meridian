"""Unit tests for read_index.py: write_block, check_files_fresh, sync_tags,
and the migration-003 backfill (indexed_files + rule_tags/lesson_tags)."""

import json
import tempfile
import time
from pathlib import Path

from meridian.db.connection import get_connection, initialize_db
from meridian.utils.read_index import (
    backfill_read_index,
    check_files_fresh,
    normalize_tag_list,
    refresh_indexed_file,
    sync_tags,
    write_block,
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
    return get_connection(db_path), kb_path


def test_normalize_tag_list_handles_json_csv_and_list():
    assert normalize_tag_list(["go", " fiber ", ""]) == ["fiber", "go"]
    assert normalize_tag_list('["go", "fiber"]') == ["fiber", "go"]
    assert normalize_tag_list("go, fiber") == ["fiber", "go"]
    assert normalize_tag_list(None) == []
    assert normalize_tag_list("[]") == []


def test_write_block_writes_file_and_indexes_it():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"## RN-GLOBAL-001\nhello\n")
        conn.commit()

        assert target.read_bytes() == b"## RN-GLOBAL-001\nhello\n"

        row = conn.execute(
            "SELECT mtime, content_hash FROM indexed_files WHERE file_path = ?",
            (str(target),),
        ).fetchone()
        assert row is not None
        import hashlib

        assert row[1] == hashlib.sha256(target.read_bytes()).hexdigest()
    finally:
        conn.close()


def test_write_block_upserts_on_rewrite():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"first")
        write_block(conn, target, b"second")
        conn.commit()

        rows = conn.execute(
            "SELECT content_hash FROM indexed_files WHERE file_path = ?",
            (str(target),),
        ).fetchall()
        assert len(rows) == 1  # upsert, not a duplicate row

        import hashlib

        assert rows[0][0] == hashlib.sha256(b"second").hexdigest()
    finally:
        conn.close()


def test_check_files_fresh_true_right_after_write():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"content")
        conn.commit()

        result = check_files_fresh(conn, [str(target)])
        assert result == {str(target): True}
    finally:
        conn.close()


def test_check_files_fresh_false_for_untracked_file():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "untracked.md"
        target.write_text("hi")

        result = check_files_fresh(conn, [str(target)])
        assert result == {str(target): False}
    finally:
        conn.close()


def test_check_files_fresh_false_for_missing_file():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"content")
        conn.commit()
        target.unlink()

        result = check_files_fresh(conn, [str(target)])
        assert result == {str(target): False}
    finally:
        conn.close()


def test_check_files_fresh_detects_external_edit_via_mtime_and_hash():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"original")
        conn.commit()

        time.sleep(0.01)
        target.write_bytes(b"tampered")  # external edit, bumps mtime

        result = check_files_fresh(conn, [str(target)])
        assert result == {str(target): False}
    finally:
        conn.close()


def test_check_files_fresh_one_stat_per_distinct_file(monkeypatch):
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        write_block(conn, target, b"content")
        conn.commit()

        stat_calls = 0
        original_stat = Path.stat

        def counting_stat(self, *args, **kwargs):
            nonlocal stat_calls
            if self == target:
                stat_calls += 1
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", counting_stat)

        # 10 "rows" all pointing at the same file.
        result = check_files_fresh(conn, [str(target)] * 10)

        assert result == {str(target): True}
        assert stat_calls == 1
    finally:
        conn.close()


def test_sync_tags_replaces_existing_set():
    conn, kb_path = _temp_db()
    try:
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity) "
            "VALUES ('r1', 'global', 'RN-GLOBAL-001', 'text', 'general', 'medium')"
        )
        conn.commit()

        sync_tags(conn, "rule_tags", "rule_id", "r1", ["go", "fiber"])
        conn.commit()
        tags = {
            row[0]
            for row in conn.execute(
                "SELECT tag FROM rule_tags WHERE rule_id = ?", ("r1",)
            )
        }
        assert tags == {"go", "fiber"}

        sync_tags(conn, "rule_tags", "rule_id", "r1", ["quarkus"])
        conn.commit()
        tags = {
            row[0]
            for row in conn.execute(
                "SELECT tag FROM rule_tags WHERE rule_id = ?", ("r1",)
            )
        }
        assert tags == {"quarkus"}
    finally:
        conn.close()


def test_backfill_read_index_from_existing_data():
    """Mirrors migration 003's acceptance criteria: 3 rules with tags
    ['a','b'], [], null migrate with exact counts, and indexed_files gets a
    row per existing file with a matching content hash."""
    conn, kb_path = _temp_db()
    try:
        md_path = kb_path / "knowledge-base" / "global" / "general.md"
        md_path.write_text("## RN-GLOBAL-001\nsome text\n")

        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "tags, file_path) VALUES (?, 'global', ?, 'text', 'general', "
            "'medium', ?, ?)",
            ("r1", "RN-GLOBAL-001", json.dumps(["a", "b"]), str(md_path)),
        )
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "tags, file_path) VALUES (?, 'global', ?, 'text', 'general', "
            "'medium', ?, ?)",
            ("r2", "RN-GLOBAL-002", json.dumps([]), str(md_path)),
        )
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "tags, file_path) VALUES (?, 'global', ?, 'text', 'general', "
            "'medium', NULL, ?)",
            ("r3", "RN-GLOBAL-003", str(md_path)),
        )
        conn.commit()

        stats = backfill_read_index(conn)
        conn.commit()

        assert stats["tag_rows_inserted"] == 2
        count = conn.execute("SELECT COUNT(*) FROM rule_tags").fetchone()[0]
        assert count == 2

        import hashlib

        row = conn.execute(
            "SELECT content_hash FROM indexed_files WHERE file_path = ?",
            (str(md_path),),
        ).fetchone()
        assert row is not None
        assert row[0] == hashlib.sha256(md_path.read_bytes()).hexdigest()
    finally:
        conn.close()


def test_backfill_read_index_skips_missing_files():
    conn, kb_path = _temp_db()
    try:
        missing_path = kb_path / "knowledge-base" / "global" / "gone.md"
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "file_path) VALUES ('r1', 'global', 'RN-GLOBAL-001', 'text', "
            "'general', 'medium', ?)",
            (str(missing_path),),
        )
        conn.commit()

        stats = backfill_read_index(conn)

        assert stats["files_referenced"] == 1
        assert stats["files_indexed"] == 0
        count = conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_refresh_indexed_file_used_by_reindexing():
    conn, kb_path = _temp_db()
    try:
        target = kb_path / "note.md"
        target.write_text("content")

        refresh_indexed_file(conn, target)
        conn.commit()

        result = check_files_fresh(conn, [str(target)])
        assert result == {str(target): True}
    finally:
        conn.close()
