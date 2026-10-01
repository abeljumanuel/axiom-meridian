-- Migration 005: standalone rule/lesson deprecation lifecycle (ADR-007,
-- openspec/changes/add-rule-lesson-deprecation). Adds a structured
-- superseded_by reference to rule_history/lesson_history (today's
-- get_rule_timeline derives it by parsing a PROMOTED row's free-text
-- reason, which actually holds a scope id, not an RN-/LL- code) and the
-- idx_lessons_status index that rules already has (idx_rules_status) but
-- lessons never did.
--
-- Additive only: nullable columns, no default requiring a backfill UPDATE,
-- so no Python dispatch branch is needed in migrations.py::_apply_migration
-- for this number.

ALTER TABLE rule_history ADD COLUMN superseded_by TEXT REFERENCES rules(id);
ALTER TABLE lesson_history ADD COLUMN superseded_by TEXT REFERENCES lessons(id);

CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);
