## 1. Database migration

- [x] 1.1 Create `src/meridian/db/migrations/005_deprecation_lifecycle.sql`: `ALTER TABLE rule_history ADD COLUMN superseded_by TEXT REFERENCES rules(id)`, `ALTER TABLE lesson_history ADD COLUMN superseded_by TEXT REFERENCES lessons(id)`, `CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status)`. **Correction found during implementation:** a Python dispatch branch for `number == 5` *was* needed in `_apply_migration` (mirrors migration 1's pattern) — `ALTER TABLE ADD COLUMN` has no `IF NOT EXISTS` form, so it fails with `duplicate column name` when `initialize_db` runs pending migrations right after creating a fresh database from `schema.sql` (which already has the column). See design.md's updated Migration Plan note.
- [x] 1.2 Update `src/meridian/db/schema.sql`: add `superseded_by` to `rule_history` and `lesson_history` `CREATE TABLE` statements, and add `idx_lessons_status` alongside the existing `idx_rules_status`, so fresh installs match migration 005.
- [x] 1.3 Unit test (`tests/unit/test_migrations.py`): applying migration 005 on a database at `user_version=4` succeeds, leaves existing `rule_history`/`lesson_history` rows with `superseded_by IS NULL`, and `PRAGMA user_version` becomes `5`.
- [x] 1.4 Unit test: a fresh `db init` database (schema.sql path) has the same `rule_history`/`lesson_history` columns and `idx_lessons_status` as a migrated one.

## 2. Proposal creation: `create_pending_proposal` support for `type="deprecate"`

- [x] 2.1 In `src/meridian/tools/extraction.py::create_pending_proposal`, widen the `type` whitelist to `("rule", "lesson", "update", "deprecate")` and extend the `if type == "update":` branch to `if type in ("update", "deprecate"):` so `deprecate` reuses the existing `RN-`/`LL-` target-id resolution and existence check (lines ~110-156).
- [x] 2.2 Add optional parameters `reason: str | None = None` and `metadata: dict | None = None` to `create_pending_proposal`'s signature, and extend its `INSERT INTO pending_proposals` to persist both into their existing `reason`/`metadata` columns (`metadata` as `json.dumps(metadata) if metadata else None`, same pattern already used for `suggested_attributes`).
- [x] 2.3 For `type="deprecate"`, validate `superseded_by` when present (passed inside `metadata`): if `metadata.get("superseded_by")` is set, confirm it references an existing row in `rules`/`lessons` (by the appropriate table for its `RN-`/`LL-` prefix) with `status='active'`; raise `ValueError` naming the invalid id otherwise.
- [x] 2.4 Unit tests (`tests/unit` or extend existing extraction tests): `type="deprecate"` proposal is created with `reason`/`metadata` persisted; missing/invalid `target_id` raises the same way `type="update"` does; a `superseded_by` pointing at a nonexistent or non-active rule raises `ValueError`. Implemented in `tests/integration/test_audit_and_extraction.py` (5 new tests), with a `_seed_rule_by_code` helper added because the existing `_seed_rules` fixture uses a synthetic `id` distinct from `code`, unlike the real `id == code` convention `_resolve_update_target`/`approve_proposal` rely on.

## 3. Vector store deletion

- [x] 3.1 Add `delete_rule(rule_id: str) -> None` and `delete_lesson(lesson_id: str) -> None` to `src/meridian/rag/vector_store.py`, thin wrappers over `collection.delete(ids=[rule_id])` / `collection.delete(ids=[lesson_id])` on the existing `_RULES_COLLECTION`/`_LESSONS_COLLECTION`.
- [x] 3.2 Unit tests: new `tests/unit/test_vector_store.py` — `delete_rule`/`delete_lesson` remove a previously-upserted id from `search_rules`/`search_lessons` results; calling delete on an id that was never upserted does not raise.

## 4. Shared embedding-removal helper

- [x] 4.1 Add `_remove_embedding_after_deprecate(conn, *, table, kind, code, delete_fn)` to `src/meridian/tools/knowledge_management.py`, mirroring `_embed_and_upsert_after_approve`'s shape: looks up the row's `id` by `code`, calls `delete_fn(id)` (the appropriate `vector_store.delete_rule`/`delete_lesson`), sets `embedding_id = NULL` and commits, wrapped so any exception is logged (`logger.exception`) and swallowed. Docstring explicitly states it only handles vector-store cleanup, not `rule_history`/`lesson_history` semantics.
- [x] 4.2 Unit test (`tests/unit/test_remove_embedding_after_deprecate.py`, new file): clears `embedding_id` and calls the delete function on success; an exception from `delete_fn` is logged and swallowed and leaves `embedding_id` untouched (confirmed: failure does not force-null it); an unknown `code` returns `False` without raising.

## 5. Approval flow: `_approve_deprecate_proposal`

- [x] 5.1 In `approve_proposal` (`knowledge_management.py:586-598`), add a dispatch branch: `elif proposal["type"] == "deprecate": return _approve_deprecate_proposal(conn, proposal_id, proposal, metadata)`.
- [x] 5.2 Implement `_approve_deprecate_proposal`, parallel in structure to `_approve_update_proposal`: resolve target via `_resolve_update_target` (already generic over `RN-`/`LL-`); inside one transaction, `UPDATE {table} SET status='deprecated', updated_at=datetime('now')`, call `_mark_deprecated_in_md` with the target's `file_path`/`file_offset`/`byte_length`, insert into `{hist_table}` with `change_type='DEPRECATED'`, `reason=proposal["reason"]`, `superseded_by=metadata.get("superseded_by")`, mark the proposal `approved`, commit.
- [x] 5.3 Post-commit, call `_remove_embedding_after_deprecate` for the deprecated row (rules → `vector_store.delete_rule`, lessons → `vector_store.delete_lesson`).
- [x] 5.4 Return shape: `proposal_id`, `target_id`, `status`, `superseded_by`, `embedding_removed` (boolean, mirroring the existing `embedded` boolean on create/update approvals).
- [x] 5.5 Integration test (`tests/integration/test_rag_query.py` — placed there rather than `test_proposals_flow.py` since it needs the real embedder/vector-store fixtures already set up in that file): `test_approve_deprecate_proposal_rule_full_flow` asserts `rules.status='deprecated'`, scope_id unchanged, `.md` block marked, `rule_history` row with `change_type='DEPRECATED'` + expected `reason`/`superseded_by`, `embedding_id IS NULL`, and the rule no longer in `vector_store.search_rules`.
- [x] 5.6 Same for a lesson target: `test_approve_deprecate_proposal_lesson_full_flow`, confirming the tool/approval branch is generic over both `RN-`/`LL-`.

## 6. `promote_rule`: close the embedding-cleanup asymmetry

- [x] 6.1 In `promote_rule`, after its existing `rule_history` insert and `conn.commit()`, invoke `_remove_embedding_after_deprecate` (Task 4.1) for the promoted-away rule; return gains an `embedding_removed` key.
- [x] 6.2 Integration test (`tests/integration/test_rag_query.py::test_promote_rule_removes_embedding_immediately`): `promote_rule` on an already-embedded rule results in `embedding_id IS NULL` and the rule no longer appearing in `vector_store.search_rules`, immediately.

## 7. `generate_embeddings`: backfill purge

- [x] 7.1 Add `_purge_deprecated_embeddings_for_table(conn, *, table, kind, delete_fn, scope_id)` to `knowledge_management.py`, a sibling function to `_generate_embeddings_for_table` (reuses `_remove_embedding_after_deprecate` per row, so the purge and the single-row cleanup paths share one implementation): selects `id, code FROM {table} WHERE status='deprecated' AND embedding_id IS NOT NULL` (optionally filtered by `scope_id`, same parity as the embed-side query), returns the count purged.
- [x] 7.2 Call `_purge_deprecated_embeddings_for_table` for both `rules` and `lessons` from `generate_embeddings`, after the existing embed calls, and add a `purged` key to its returned dict alongside `processed`/`skipped`/`errors`.
- [x] 7.3 Unit tests (`tests/unit/test_purge_deprecated_embeddings.py`, new file, 4 tests): a `status='deprecated'` row with a non-`NULL` `embedding_id` is purged and counted; an already-clean deprecated row is untouched; an active row is untouched; `scope_id` filters the purge.
- [x] 7.4 Integration test (`tests/integration/test_rag_query.py::test_generate_embeddings_backfills_pre_existing_deprecated_rows`): a rule deprecated by flipping `status` directly (simulating pre-fix `promote_rule`, embedding never cleaned up) is purged by a subsequent `generate_embeddings()` call, with `purged == 1`.

## 8. `get_rule_audit_log`: surface both deprecation origins

- [x] 8.1 **Naming correction found during implementation:** the function with the `deprecated_rules`/`superseded_by` logic is `get_rule_audit_log` (scope/project-wide chronology), not `get_rule_timeline` (a different, single-rule function at a different location) — proposal.md/design.md/spec.md all named the wrong function; corrected the behavior there and noting the doc mismatch here rather than silently diverging code from docs. In `knowledge_consumption.py::get_rule_audit_log`'s `deprecated_rules` query, widened `AND rh.change_type = 'DEPRECATED'` to `AND rh.change_type IN ('DEPRECATED', 'PROMOTED')`, selected `rh.superseded_by` directly (removed the old per-row subquery that parsed a 'PROMOTED' row's `reason` string into a fake `superseded_by`), and kept `reason` (aliased `deprecation_reason`) populated as-is so pre-migration-005 `PROMOTED` rows still show their scope-destination text — which, per Decision 4, is in fact *every* `PROMOTED` row, since `promote_rule` never sets the structured column.
- [x] 8.2 Integration tests (new file `tests/integration/test_rule_audit_log.py`): a rule deprecated via `promote_rule` appears in `get_rule_audit_log`'s `deprecated_rules` with `superseded_by IS NULL` and its scope-destination `reason`; a rule deprecated via the `deprecate` proposal type appears with a structured `superseded_by`.

## 9. `query_rules`/`query_lessons`: `include_deprecated` toggle

- [x] 9.1 Added `include_deprecated: bool = False` to `query_rules`'s signature; the plain-SQL branch only appends `AND status = 'active'` when `False`; the semantic (`query_text`) branch is unchanged (deprecated rows are no longer present in the index per Tasks 5-7).
- [x] 9.2 Same change for `query_lessons`.
- [x] 9.3 Integration tests: `test_index_and_query.py` — `test_query_rules_excludes_deprecated_by_default`, `test_query_rules_include_deprecated_true_surfaces_it`, `test_query_lessons_include_deprecated`; `test_rag_query.py::test_include_deprecated_true_does_not_revive_semantic_results` — confirms `include_deprecated=True` with `query_text` still excludes a rule deprecated via the new flow (removed from the index, not just filtered).

## 10. New `deprecate_rule` MCP tool

- [x] 10.1 Add `"deprecate_rule": "analyze"` to `TOOL_ACCESS_LEVELS` in `src/meridian/utils/security.py`.
- [x] 10.2 Register `deprecate_rule(rule_id, reason, superseded_by=None)` in `src/meridian/server.py`, following `promote_rule`'s pattern (`project_id=None`, same as `get_rule_context`/`get_rule_timeline`'s precedent for a tool that only takes an id). `_impl()` looks up the target's current `text`/`what_happened` (by `RN-`/`LL-` prefix) for `proposed_text`, then delegates to `extraction.create_pending_proposal(conn, "deprecate", current_text, "", target_id=rule_id, reason=reason, metadata={"superseded_by": superseded_by} if superseded_by else None)`.
- [x] 10.3 Docstring states access level `analyze`, that the call only creates a proposal, and that it accepts both `RN-` and `LL-` ids.
- [x] 10.4 Updated `tests/contract/test_mcp_tool_signatures.py` (expected signature for `deprecate_rule`; `include_deprecated` added to `query_rules`/`query_lessons`) **and** `src/meridian/server.py`'s `query_rules`/`query_lessons` MCP wrappers themselves — found during implementation that the contract test checks the server.py wrapper signatures, which also needed `include_deprecated` threaded through to the `knowledge_consumption` call (not just the internal functions edited in Group 9).
- [x] 10.5 Integration tests (`tests/integration/test_access_control.py`): `test_deprecate_rule_analyze_level_creates_visible_proposal` (end-to-end through the registered MCP tool, visible via `list_pending_proposals`) and `test_read_level_denies_deprecate_rule` (read-level credential denied). Fixed two tests' bodies that an earlier edit in this session had accidentally spliced together (stray assertions from `test_create_pending_proposal_exposes_update_target` had landed inside the new deprecate test) — caught by the first test run, corrected before marking this done.

## 11. Verification

- [x] 11.1 `uv run pytest` — 344 passed.
- [x] 11.2 `uv run ruff check src tests` — no findings.
- [x] 11.3 Confirmed both design.md open questions resolved as leaned (Tasks 2.3, 7.1); updated design.md's "Open Questions" section to record the resolutions and the `get_rule_audit_log` naming correction (Task 8.1).
