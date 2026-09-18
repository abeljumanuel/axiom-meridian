-- Migration 002: id_counters table + supporting history/lookup indices
-- Replaces the MAX(id) LIKE 'prefix-%' full-table scan that ran on the
-- critical path of all 26 MCP tools (reporte-rendimiento.md §3.2/§3.3) with
-- an atomically-incremented counter table.
--
-- Seeding id_counters from the real data already in the database happens in
-- Python (meridian.utils.id_generator.seed_id_counters), invoked by
-- db/migrations.py right after this file's statements run — the per-prefix
-- and per-tech-segment numeric-max computation isn't expressible cleanly in
-- portable SQL.

CREATE TABLE IF NOT EXISTS id_counters (
  name TEXT PRIMARY KEY,
  next INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rule_history_rule_id ON rule_history(rule_id);
CREATE INDEX IF NOT EXISTS idx_lesson_history_lesson_id ON lesson_history(lesson_id);
CREATE INDEX IF NOT EXISTS idx_pending_proposals_scope_id ON pending_proposals(scope_id);
CREATE INDEX IF NOT EXISTS idx_pr_audits_ref_project ON pr_audits(pr_ref, project_id);
