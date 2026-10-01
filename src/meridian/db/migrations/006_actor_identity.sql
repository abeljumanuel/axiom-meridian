-- Migration 006: actor attribution (openspec/changes/add-actor-identity-tracking).
-- Adds a nullable actor_id to pending_proposals, rule_history,
-- lesson_history, and access_log, resolved today by
-- utils/security.py::resolve_actor() (local OS user, zero configuration) —
-- groundwork for a future MERIDIAN_MODE="shared" credentialed resolution
-- path, not yet implemented. Pre-existing rows keep actor_id = NULL.
--
-- Additive, nullable columns — but ALTER TABLE ADD COLUMN has no
-- "IF NOT EXISTS" form in SQLite, so a Python dispatch branch IS needed in
-- migrations.py::_apply_migration for this number, mirroring migration 005's
-- guard: a database created fresh from schema.sql (which already defines
-- these columns) would otherwise fail with "duplicate column name" when
-- initialize_db runs pending migrations right after creating it.

ALTER TABLE pending_proposals ADD COLUMN actor_id TEXT;
ALTER TABLE rule_history ADD COLUMN actor_id TEXT;
ALTER TABLE lesson_history ADD COLUMN actor_id TEXT;
ALTER TABLE access_log ADD COLUMN actor_id TEXT;
