-- Migration 001: Add missing columns to lessons table
-- Applied when lessons table exists but lacks source_type, source_ref, created_at, updated_at

ALTER TABLE lessons ADD COLUMN source_type TEXT;
ALTER TABLE lessons ADD COLUMN source_ref TEXT;
ALTER TABLE lessons ADD COLUMN created_at TEXT DEFAULT (datetime('now'));
ALTER TABLE lessons ADD COLUMN updated_at TEXT DEFAULT (datetime('now'));

-- Add previous_text and new_text to lesson_history if they don't exist
-- SQLite does not support dropping columns, so we check via pragma
