-- Migration 001: Add missing columns to lessons table
-- Applied when lessons table exists but lacks source_type, source_ref, created_at, updated_at
--
-- created_at/updated_at are added WITHOUT a DEFAULT clause and backfilled
-- via UPDATE, not "ADD COLUMN ... DEFAULT (datetime('now'))": SQLite
-- rejects a non-constant default in ADD COLUMN once the table has any rows
-- ("Cannot add a column with non-constant default") — which is exactly the
-- case on any real field database. Since ALTER TABLE ADD COLUMN cannot
-- attach a working default for *future* inserts on this pre-existing table
-- either way, the application (knowledge_management.py) sets these columns
-- explicitly via datetime('now') on insert instead of relying on a
-- column-level default for lessons.

ALTER TABLE lessons ADD COLUMN source_type TEXT;
ALTER TABLE lessons ADD COLUMN source_ref TEXT;
ALTER TABLE lessons ADD COLUMN created_at TEXT;
ALTER TABLE lessons ADD COLUMN updated_at TEXT;

UPDATE lessons SET created_at = datetime('now') WHERE created_at IS NULL;
UPDATE lessons SET updated_at = datetime('now') WHERE updated_at IS NULL;

-- Add previous_text and new_text to lesson_history if they don't exist
-- SQLite does not support dropping columns, so we check via pragma
