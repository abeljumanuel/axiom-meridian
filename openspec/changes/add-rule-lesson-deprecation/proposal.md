## Why

The only existing path to `rules.status = 'deprecated'`/`lessons.status = 'deprecated'` is `promote_rule`, which couples deprecation to a scope change — it cannot express "this rule is no longer valid, full stop" (the motivating case: `RN-077` needs to be deprecated without moving scope). Reading the implementation (not just the PRD) also surfaced two latent bugs this change must close, not just the missing tool:

- `query_rules`/`query_lessons`'s semantic (`query_text`) branch applies **no `status` filtering at all** — `_rule_embedding_metadata`/`_lesson_embedding_metadata` never attach `status` to ChromaDB metadata, and `vector_store.search_rules`/`search_lessons` only filter by `scope_id`. A deprecated rule stays a live semantic-search candidate indefinitely.
- `promote_rule` writes `rule_history.change_type = 'PROMOTED'`, never `'DEPRECATED'` — so `get_rule_audit_log`'s `deprecated_rules` block (which filters on `change_type = 'DEPRECATED'`) never surfaces rules deprecated via `promote_rule`, and its `superseded_by` is a string-parse of `PROMOTED`'s free-text `reason` (which actually holds a scope id, not an `RN-`/`LL-` code).

Full analysis and the rejected alternatives live in `ADR-007-rule-lesson-deprecation-lifecycle.md` at the repo root.

## What Changes

- New `deprecate_rule(rule_id, reason, superseded_by=None)` MCP tool (`analyze` access level), generic over `RN-`/`LL-` prefixes so it also covers lesson deprecation — closing `changes/test-20160420.md`'s LIFECYCLE-01 (`deprecate_lesson`) as a side effect instead of a separate tool.
- `extraction.py::create_pending_proposal` gains `type="deprecate"` support (sharing the existing `target_id` validation branch used by `"update"`) and two new optional parameters, `reason` and `metadata`, persisted into `pending_proposals`' existing `reason`/`metadata` columns (today silently dropped by that function for every proposal type).
- `approve_proposal` gains a new `_approve_deprecate_proposal` branch: sets `status='deprecated'`, rewrites the `.md` block via the existing `_mark_deprecated_in_md`, and records a `rule_history`/`lesson_history` row with `change_type='DEPRECATED'` and the new `superseded_by` field.
- New `rule_history.superseded_by` / `lesson_history.superseded_by` columns (nullable, not required at the API level) replace the current practice of parsing a replacement id out of free text.
- `get_rule_audit_log`'s `deprecated_rules` query widens from `change_type = 'DEPRECATED'` to `change_type IN ('DEPRECATED', 'PROMOTED')`, so `promote_rule`-originated deprecations are also covered by the structured `superseded_by`.
- New `vector_store.delete_rule`/`delete_lesson`, called post-commit from `_approve_deprecate_proposal` (best-effort, same failure-isolation contract as `_embed_and_upsert_after_approve`) to remove the row from the semantic index and clear its `embedding_id`.
- `promote_rule` calls the same embedding-removal helper, so promotion-driven deprecation no longer leaves a stale entry in the vector index.
- `generate_embeddings` additionally purges any `status='deprecated' AND embedding_id IS NOT NULL` row it finds (backfill for rules/lessons already deprecated via `promote_rule` before this change ships), reporting a new `purged` count.
- `query_rules`/`query_lessons` gain `include_deprecated: bool = False`; the existing SQL branch drops its `status='active'` filter when `True`, the semantic branch needs no extra filtering once the index is kept clean by the points above.
- `tests/contract/test_mcp_tool_signatures.py` updated with `deprecate_rule`'s signature and the new `include_deprecated` parameter on `query_rules`/`query_lessons`.

Explicitly **out of scope**: retrofitting `CHECK (status IN ('active','deprecated'))` onto databases created before `schema.sql` already defined it (deferred to a separate hardening ADR per ADR-007).

## Capabilities

### New Capabilities
- `rule-lesson-deprecation`: a proposal-gated (`type="deprecate"` → `approve_proposal`) way to deprecate a rule or lesson independently of `promote_rule`, with structured `superseded_by` tracking, semantic-index cleanup on deprecation, and an explicit `include_deprecated` toggle on `query_rules`/`query_lessons`.

### Modified Capabilities
(none — no existing `openspec/specs/` capability currently documents `promote_rule`, `get_rule_audit_log`, or `query_rules`/`query_lessons`'s status filtering as spec-level requirements; their changes here are covered as implementation details of the new capability above)

## Impact

- `src/meridian/server.py` — new `deprecate_rule` tool registration, following the `promote_rule` pattern (`tool_name`/`params`/`project_id`/`_impl()`/`_security_pattern`).
- `src/meridian/utils/security.py` — `TOOL_ACCESS_LEVELS["deprecate_rule"] = "analyze"`.
- `src/meridian/tools/extraction.py` — `create_pending_proposal`: `type="deprecate"` support, new `reason`/`metadata` parameters.
- `src/meridian/tools/knowledge_management.py` — `approve_proposal` dispatch, new `_approve_deprecate_proposal`, `generate_embeddings`/`_generate_embeddings_for_table` purge logic, `promote_rule` calling the shared embedding-removal helper.
- `src/meridian/tools/knowledge_consumption.py` — `query_rules`, `query_lessons` (`include_deprecated` parameter), `get_rule_audit_log` (`deprecated_rules` filter).
- `src/meridian/rag/vector_store.py` — new `delete_rule`, `delete_lesson`.
- `src/meridian/db/schema.sql` and a new `src/meridian/db/migrations/005_*.sql` — `rule_history.superseded_by`, `lesson_history.superseded_by`, `idx_lessons_status`.
- `tests/contract/test_mcp_tool_signatures.py`, plus new/updated unit and integration tests (approval branch, migration, vector store deletion, full propose→approve→purge→query flow).
- No change to the governance model: deprecation still requires a human-approved proposal, same as `update`-type proposals today. No change to `write_block`'s role as the sole `.md` byte-writer.
