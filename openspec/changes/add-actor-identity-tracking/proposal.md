## Why

Nothing in the schema today records *who* originated a proposal, a rule/lesson history entry, or a tool access — `pending_proposals`, `rule_history`, `lesson_history`, and `access_log` all capture *what* happened but never *who* did it. `check_access` (`utils/security.py`) resolves permissions from a single process-wide `MERIDIAN_ACCESS_LEVEL` env var, with no concept of a caller/actor at all.

This is the right tradeoff for today's single-user local usage — nobody needs to authenticate against themselves. But it is a hard blocker for a future networked mode where many contributors submit proposals and a specific group validates them: without a per-row actor, there is no way to say who proposed or approved a given change, and retrofitting that column onto tables that already hold real production history (this server is in daily personal use) would require backfilling or accepting permanent `NULL` gaps for everything written before the migration. Adding the column now, empty, is strictly cheaper than adding it later.

A precedent for the local-vs-networked split already exists in `server.py`: `run_stdio()` requires nothing, `run_http()` generates and requires a bearer session token. This change extends that same shape to the actor/role dimension instead of inventing a new one.

## What Changes

- Add a nullable `actor_id TEXT` column to `pending_proposals`, `rule_history`, `lesson_history`, and `access_log`.
- Add `utils/security.py::resolve_actor()`, which returns `getpass.getuser()` (the OS login name) when `MERIDIAN_MODE` is unset or `"local"` — zero configuration, no credentials, matching today's trusted-local behavior exactly.
- Add the `MERIDIAN_MODE` env var (`"local"` default | `"shared"`), read alongside `MERIDIAN_ACCESS_LEVEL`. In `"local"` mode `check_access` and every call site behave exactly as they do today, with `resolve_actor()`'s value threaded through only for attribution in the new columns.
- Thread the resolved actor through the existing write paths: `_security_pattern`'s call to `log_tool_access` (→ `access_log.actor_id`), `create_pending_proposal` (→ `pending_proposals.actor_id`), and `approve_proposal`'s history inserts (→ `rule_history.actor_id` / `lesson_history.actor_id`).
- `MERIDIAN_MODE="shared"` is recognized by `resolve_actor()` (raises `NotImplementedError` with a clear message) but **no credential verification, remote auth, or role table is implemented in this change** — this change only adds the data model and the local default, so the shared path can be built later without another migration.

Explicitly **out of scope**: any authentication mechanism, a `users`/`actors` table with roles, per-role `check_access` enforcement, and the networked/shared transport itself. This change is purely the data-model and local-default groundwork those would build on.

## Capabilities

### New Capabilities
- `actor-identity`: optional, zero-config attribution of who originated a proposal, history entry, or tool access, resolved locally today and ready for a future credentialed resolution path without a schema change.

### Modified Capabilities
(none — no existing `openspec/specs/` capability currently documents `pending_proposals`, `rule_history`/`lesson_history`, or `access_log`'s columns as spec-level requirements)

## Impact

- `src/meridian/db/schema.sql` — new nullable `actor_id` column on `pending_proposals`, `rule_history`, `lesson_history`, `access_log`.
- `src/meridian/db/migrations/006_actor_identity.sql` — new migration adding the four columns.
- `src/meridian/utils/security.py` — new `resolve_actor()`, new `get_mode()` (reads `MERIDIAN_MODE`), `log_tool_access` gains an `actor_id` parameter.
- `src/meridian/server.py` — `_security_pattern` resolves the actor once per call and passes it to `log_tool_access`.
- `src/meridian/tools/extraction.py` — `create_pending_proposal` persists `actor_id`.
- `src/meridian/tools/knowledge_management.py` — every `rule_history`/`lesson_history` insert site persists `actor_id`: `approve_proposal`'s branches (`_insert_new_rule`/`_insert_new_lesson`, update/deprecate branches), `promote_rule`, and the direct re-index path (`_insert_indexed_rule`/`_update_indexed_rule`/`_insert_indexed_lesson`/`_update_indexed_lesson`) — see design.md for why the latter is in scope too.
- New/updated unit tests for `resolve_actor()`, `get_mode()`, and the migration; integration test asserting `actor_id` is populated end-to-end through a propose → approve flow.
- No change to `MERIDIAN_ACCESS_LEVEL`'s existing behavior, to the proposal lifecycle's approval semantics, or to any transport.
