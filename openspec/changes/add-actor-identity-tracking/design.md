## Context

Today `access_log`, `pending_proposals`, `rule_history`, and `lesson_history` (`db/schema.sql`) record no actor at all, and `check_access`/`get_access_level` (`utils/security.py:62-87`) resolve permissions from a single process-wide `MERIDIAN_ACCESS_LEVEL` env var. `server.py`'s `run_stdio()`/`run_http()` already establish a precedent for a local-vs-networked switch: stdio trusts the caller outright, HTTP requires a generated bearer token (`generate_session_token`, `security.py:93-95`). This change extends that same local/shared split to actor attribution, without building the shared side yet.

One fact surfaced while scoping this design, widening it beyond what `proposal.md`'s Impact section originally named: `rule_history`/`lesson_history` are written from **more than just `approve_proposal`**. The direct re-index path (`index_rules_from_markdown`/`index_lessons_from_markdown`, `write` level) writes `CREATED`/`UPDATED` history rows via `_insert_indexed_rule`/`_update_indexed_rule`/`_insert_indexed_lesson`/`_update_indexed_lesson` (`knowledge_management.py:197-272`, `~380-470`), entirely independent of `pending_proposals`. `approve_proposal`'s own branches write history via `_insert_new_rule`/`_insert_new_lesson` (`~963-1045`) and the update/deprecate branches (`~1384` for `promote_rule`). All of these run inside an MCP tool call already wrapped by `_security_pattern`, so all of them are in scope for attribution — leaving the index path's rows permanently `actor_id IS NULL` would be an arbitrary gap with no justification tied to this change's goal.

## Goals / Non-Goals

**Goals:**
- Every `access_log`, `pending_proposals`, `rule_history`, and `lesson_history` row written from this point forward carries an `actor_id`, resolved with zero configuration in local use.
- The local path (today's only real usage) behaves identically to today in every way except the new column being populated — no new required env var, no credential, no behavior change in `check_access`.
- The schema and the resolution hook are shaped so that a future `MERIDIAN_MODE="shared"` implementation is additive (a new credential-resolution branch inside `resolve_actor()`), not a second migration.

**Non-Goals:**
- Implementing `MERIDIAN_MODE="shared"`, any credential/token-to-actor mapping, an `actors`/`users` table, or per-role `check_access` enforcement. This change only reserves the mode value and fails loudly if it's selected.
- Backfilling `actor_id` on any row written before this change ships. They stay `NULL`, same as `superseded_by` on pre-existing `PROMOTED` rows (ADR-007, Decision §4) — a precedent already accepted in this codebase for additive, non-retroactive columns.
- Changing who is *allowed* to call a tool. `resolve_actor()` feeds attribution only; `check_access`'s allow/deny logic is untouched.

## Decisions

### 1. `resolve_actor()`/`get_mode()` live in `utils/security.py`, not a new module

`get_access_level()` (`security.py:62-74`) already owns the exact pattern these two functions need: read an env var, validate against a small fixed set, default when unset, raise `ValueError` on garbage. Two small functions following an existing idiom in the file that already owns `MERIDIAN_ACCESS_LEVEL` belong next to it, not in a new `utils/identity.py` that would split one concern (env-var-driven process configuration) across two files.

### 2. Call `resolve_actor()` inline at each insert site, not threaded as a function parameter

Every write site already calls shared utilities inline (`next_sequential_id(conn, ...)`, `sync_tags(conn, ...)`) rather than receiving their results as parameters from a caller several frames up. `resolve_actor()` is the same kind of cheap, side-effect-free lookup (an env var read plus, at most, `getpass.getuser()`) — calling it directly inside `_insert_indexed_rule`, `_update_indexed_rule`, `_insert_indexed_lesson`, `_update_indexed_lesson`, `_insert_new_rule`, `_insert_new_lesson`, the update/deprecate branches, and `promote_rule`'s insert keeps every call site self-contained. Rejected alternative: add an `actor_id: str` parameter to all eight functions and their callers. Rejected because it would ripple signature changes through every caller of every one of these helpers for a value they'd all compute identically by calling the same function — pure boilerplate with no behavioral difference.

`_security_pattern` (`server.py:100-156`) is the one exception: it already resolves per-call values once (`log_id`) and passes them down to `log_tool_access`, so it resolves the actor once per call the same way and passes it as `log_tool_access`'s new parameter — consistent with that function's existing shape, not the inline pattern used elsewhere.

### 3. `MERIDIAN_MODE` is validated eagerly inside `resolve_actor()`/`get_mode()`, mirroring `get_access_level()`

An unrecognized value (anything other than `"local"`/`"shared"`) raises `ValueError` immediately, the same contract `get_access_level()` already has for `MERIDIAN_ACCESS_LEVEL`. No new validation style is introduced.

### 4. `MERIDIAN_MODE="shared"` fails lazily, inside `resolve_actor()`, not at server startup

Rejected alternative: add a startup-time check in `server.py` (`run_stdio`/`run_http`) that refuses to start if `MERIDIAN_MODE=shared`. Rejected because it would require a new startup-validation path for a mode no code implements yet, duplicating the check `resolve_actor()` already needs to make at call time. Every code path that would need an actor already calls `resolve_actor()`, so failing there is sufficient and keeps all new logic contained to `utils/security.py`.

### 5. Attribution covers every `rule_history`/`lesson_history` write site, not only `approve_proposal`'s

Per the Context finding above: `_insert_indexed_rule`, `_update_indexed_rule`, `_insert_indexed_lesson`, `_update_indexed_lesson` (direct re-index path) get the same `resolve_actor()` call as `approve_proposal`'s branches and `promote_rule`. This corrects `proposal.md`'s Impact section, which under-scoped this to "approve_proposal's history-insert branches."

## Risks / Trade-offs

- **[Risk]** `getpass.getuser()` can raise `OSError` in environments with no password-database entry for the running uid (some containers/CI). → **Mitigation**: `resolve_actor()` catches that specific exception and falls back to a constant (`"unknown-local-user"`) rather than letting an attribution feature break a write path that worked before this change existed.
- **[Risk]** Broadening scope to nine insert sites (Decision §5) instead of the originally-scoped few increases the surface touched by this change. → **Mitigation**: the change is mechanical and identical at each site (one inline `resolve_actor()` call feeding one new bound parameter); covered by one integration test per write path (index, approve-create, approve-update, approve-deprecate, promote) rather than relying on inspection alone.
- **[Risk]** A future reader of `resolve_actor()` sees the `MERIDIAN_MODE="shared"` branch and assumes shared mode is partially functional. → **Mitigation**: the `NotImplementedError` message and this design doc are explicit that shared mode is reserved, not partially built; `proposal.md`'s "Explicitly out of scope" section says the same.

## Migration Plan

- New `src/meridian/db/migrations/006_actor_identity.sql`: additive only — `ALTER TABLE ... ADD COLUMN actor_id TEXT` on `pending_proposals`, `rule_history`, `lesson_history`, `access_log`. No `NOT NULL`, no default, no backfill `UPDATE`.
- Following migration 005's precedent (`migrations.py:53-61`), a Python dispatch branch for number `6` is needed in `_apply_migration`: `ALTER TABLE ADD COLUMN` has no `IF NOT EXISTS` form in SQLite, and `initialize_db` always runs pending migrations even right after creating a fresh database from `schema.sql` (which will already define `actor_id` directly). The guard checks one table (e.g. `access_log`) for the column's presence and skips the statements if already there.
- `db/schema.sql` updated in the same change so fresh installs get the four columns directly, same pattern as migrations 001/005's own comments describe.
- Deploy order: ship code + migration together; no manual step, since `initialize_db()` already runs pending migrations unconditionally on every startup.
- Rollback: the migration only adds nullable columns, safe to leave in place even if the feature code is rolled back — old code simply never reads/writes `actor_id`.
