-- Migration 003: indexed_files + rule_tags/lesson_tags (Opción C read path)
-- Schema only. Data backfill (tags from the legacy JSON column, file
-- fingerprints for every file_path already referenced by rules/lessons)
-- runs in Python: meridian.utils.read_index.backfill_read_index, invoked by
-- db/migrations.py right after this file's statements.

CREATE TABLE IF NOT EXISTS indexed_files (
  file_path    TEXT PRIMARY KEY,
  mtime        REAL NOT NULL,
  content_hash TEXT NOT NULL,
  updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rule_tags (
  rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  tag     TEXT NOT NULL,
  PRIMARY KEY (rule_id, tag)
);

CREATE TABLE IF NOT EXISTS lesson_tags (
  lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  tag       TEXT NOT NULL,
  PRIMARY KEY (lesson_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_rule_tags_tag ON rule_tags(tag);
CREATE INDEX IF NOT EXISTS idx_lesson_tags_tag ON lesson_tags(tag);
