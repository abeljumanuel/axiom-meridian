## 1. Database migration

- [x] 1.1 Create `src/meridian/db/migrations/006_actor_identity.sql`: `ALTER TABLE pending_proposals ADD COLUMN actor_id TEXT`, `ALTER TABLE rule_history ADD COLUMN actor_id TEXT`, `ALTER TABLE lesson_history ADD COLUMN actor_id TEXT`, `ALTER TABLE access_log ADD COLUMN actor_id TEXT`. Add a Python dispatch branch for `number == 6` in `_apply_migration` (`db/migrations.py`), mirroring migration 005's guard (`migrations.py:53-61`): check `access_log` for an existing `actor_id` column and skip the statements if present, since a fresh `schema.sql`-created database will already have it.
- [x] 1.2 Update `src/meridian/db/schema.sql`: add `actor_id TEXT` to the `CREATE TABLE` statements for `pending_proposals`, `rule_history`, `lesson_history`, `access_log`, so fresh installs match migration 006.
- [x] 1.3 Unit test (`tests/unit/test_migrations.py`): applying migration 006 on a database at `user_version=5` succeeds, leaves existing rows in all four tables with `actor_id IS NULL`, and `PRAGMA user_version` becomes `6`.
- [x] 1.4 Unit test: a fresh `db init` database has the same four `actor_id` columns as a migrated one (no `duplicate column name` error).

## 2. Actor and mode resolution

- [x] 2.1 In `src/meridian/utils/security.py`, add `get_mode() -> str`: reads `MERIDIAN_MODE` from the environment, defaults to `"local"`, lowercases, raises `ValueError` naming the invalid value if not in `{"local", "shared"}` — same shape as `get_access_level()` (`security.py:62-74`).
- [x] 2.2 Add `resolve_actor() -> str`: calls `get_mode()`; if `"local"`, returns `getpass.getuser()`, catching `OSError` and falling back to the constant `"unknown-local-user"`; if `"shared"`, raises `NotImplementedError("MERIDIAN_MODE=shared is not yet implemented; see ADR-007 follow-up / add-actor-identity-tracking design.md")`.
- [x] 2.3 Unit tests (`tests/unit/test_security.py`): `resolve_actor()` returns `getpass.getuser()` when `MERIDIAN_MODE` is unset and when explicitly `"local"`; returns the fallback constant when `getpass.getuser()` raises `OSError` (mock it); raises `NotImplementedError` mentioning `MERIDIAN_MODE`/"shared" when `MERIDIAN_MODE=shared`; raises `ValueError` for an unrecognized `MERIDIAN_MODE` value.

## 3. `access_log` attribution

- [x] 3.1 Add `actor_id: str` as a new parameter to `log_tool_access` (`security.py:131-147`), included in the `INSERT INTO access_log` columns/values.
- [x] 3.2 In `_security_pattern` (`server.py:100-156`), resolve the actor once per call (same pattern as `log_id`) and pass it to all three `log_tool_access` call sites (success, `AccessDeniedError`, generic exception).
- [x] 3.3 Integration test (`tests/integration/test_access_control.py::test_access_log_records_actor_id`): any MCP tool call (success and denied paths) results in an `access_log` row with `actor_id` equal to `resolve_actor()`'s value.

## 4. `pending_proposals` attribution

- [x] 4.1 In `src/meridian/tools/extraction.py::create_pending_proposal`, call `resolve_actor()` and include it in the `INSERT INTO pending_proposals` (~line 201) as `actor_id`.
- [x] 4.2 Integration test (`tests/integration/test_access_control.py::test_create_pending_proposal_records_actor_id`): a proposal created via `create_pending_proposal` has `actor_id` equal to `resolve_actor()`'s value at creation time.

## 5. `rule_history`/`lesson_history` attribution — direct re-index path

- [x] 5.1 In `_insert_indexed_rule` (`knowledge_management.py:197-230`), call `resolve_actor()` and include it in the `rule_history` insert (`CREATED`).
- [x] 5.2 In `_update_indexed_rule` (`knowledge_management.py:233-272`), same for its `rule_history` insert (`UPDATED`).
- [x] 5.3 In `_insert_indexed_lesson` and `_update_indexed_lesson` (`knowledge_management.py:383-470`), same for their `lesson_history` inserts (`CREATED`, `DEPRECATED`-via-reindex).
- [x] 5.4 Integration tests (`tests/integration/test_actor_identity.py::test_index_rules_from_markdown_create_and_update_record_actor_id`, `::test_index_lessons_from_markdown_create_and_update_record_actor_id`): running `index_rules_from_markdown`/`index_lessons_from_markdown` (create and update cases) results in `rule_history`/`lesson_history` rows with `actor_id` populated.

## 6. `rule_history`/`lesson_history` attribution — proposal-approval path

- [x] 6.1 In `_approve_update_proposal`'s generic `INSERT INTO {hist_table}` (`knowledge_management.py:819`), add `actor_id` via `resolve_actor()`.
- [x] 6.2 In `_approve_deprecate_proposal`'s generic `INSERT INTO {hist_table}` (`knowledge_management.py:900-907`), same.
- [x] 6.3 In `_insert_new_rule` (`knowledge_management.py:935-...`, `rule_history` insert ~976) and `_insert_new_lesson` (`~995-...`, `lesson_history` insert ~1039), same.
- [x] 6.4 In `promote_rule`'s `rule_history` insert (`knowledge_management.py:1381-1389`), same.
- [x] 6.5 Integration tests (`tests/integration/test_actor_identity.py`: `test_approve_create_rule_proposal_records_actor_id`, `test_approve_create_lesson_proposal_records_actor_id`, `test_approve_update_proposal_records_actor_id`, `test_approve_deprecate_proposal_records_actor_id`, `test_promote_rule_records_actor_id`, `test_approval_actor_id_is_independent_of_proposal_actor_id`): each approval branch records `actor_id`; the last test proves independence from the proposal's own `actor_id` by mocking the two `resolve_actor()` call sites (`extraction.py` vs `knowledge_management.py`) to return different values.

## 7. Local-user non-regression verification

These tests exist specifically to prove the local-only user (today's only real deployment) sees no behavioral difference other than the new `actor_id` field appearing in output.

- [x] 7.1 Unit test (`tests/unit/test_security.py::test_check_access_unaffected_by_mode`): `check_access`'s allow/deny result for every tool in `TOOL_ACCESS_LEVELS`, at every `MERIDIAN_ACCESS_LEVEL`, is identical whether `MERIDIAN_MODE` is unset or `"local"`.
- [x] 7.2 Full existing suite run with `MERIDIAN_MODE` unset (its default state in every test process) — zero pre-existing test files modified to keep passing: 371 passed (344 pre-change + 27 new from this change), `ruff check src tests` clean.
- [x] 7.3 Integration test (`tests/integration/test_actor_identity.py::test_propose_approve_flow_identical_with_mode_unset_vs_local`): the same propose → approve flow run twice — once with `MERIDIAN_MODE` unset, once with `MERIDIAN_MODE=local` explicit — produces identical `rules` row contents.
- [x] 7.4 Integration tests (additive-output check, `test_actor_identity.py`: `test_additive_output_get_rule_context`, `test_additive_output_get_rule_audit_log`, `test_additive_output_list_pending_proposals`): `get_rule_context`, `get_rule_audit_log`, and `list_pending_proposals` each gain `actor_id` as a new key with all pre-existing fields (`change_type`, `rule_id`, etc.) unchanged.
- [x] 7.5 Integration test (`test_actor_identity.py::test_get_rule_timeline_unaffected_by_actor_identity`): confirms `get_rule_timeline` (the one sibling using an explicit column list, not `SELECT *`) has no `actor_id` key, before or after this change.
- [x] 7.6 Integration test (`tests/integration/test_access_control.py::test_resolve_actor_fallback_end_to_end`): simulates `getpass.getuser()` raising `OSError` during a real `create_pending_proposal` call end-to-end — the call still succeeds, writing `"unknown-local-user"` into `actor_id`, with no new exception surfacing to the MCP client.

## 8. Verification

- [x] 8.1 `uv run pytest` — 371 passed.
- [x] 8.2 `uv run ruff check src tests` — no findings.
