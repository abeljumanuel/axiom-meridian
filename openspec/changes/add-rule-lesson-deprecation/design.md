## Context

Today `status='deprecated'` is only ever written by `promote_rule` (`knowledge_management.py:1262-1320`), as a side effect of moving a rule to another scope. `ADR-007-rule-lesson-deprecation-lifecycle.md` (repo root) documents the full motivation and the three implementation facts that shape this design:

1. `query_rules`/`query_lessons`'s semantic (`query_text`) branch has no `status` filtering at all — ChromaDB metadata never carries `status`, so a deprecated rule stays a live semantic-search candidate forever.
2. `promote_rule` writes `rule_history.change_type='PROMOTED'`, never `'DEPRECATED'`; `get_rule_audit_log`'s `deprecated_rules` query filters on `'DEPRECATED'` only, so promotion-driven deprecations never appear there, and `superseded_by` is currently derived by parsing `PROMOTED`'s free-text `reason` (which holds a scope id, not an `RN-`/`LL-` code).
3. `db/schema.sql` already defines `CHECK (status IN ('active','deprecated'))` and `idx_rules_status` for fresh installs — the real gap (retrofitting pre-existing databases) is out of scope for this change.

Two more facts, found while scoping this design (not in the ADR):

4. `extraction.py::create_pending_proposal` (lines 83-192) is the obvious shared helper for creating the new `deprecate` proposal — it already does sequential-id generation, `strip_private_tags`, scope validation, and (for `type="update"`) generic `RN-`/`LL-` target resolution (lines 110-156). But its `type` whitelist (line ~104) is `("rule", "lesson", "update")`, and its `INSERT` (lines 172-189) never persists the `reason`/`metadata` columns of `pending_proposals`, even though both already exist in the schema. Either fact would silently break a naive `deprecate_rule` implementation that assumes reusing this helper "just works."
5. `generate_embeddings`/`_generate_embeddings_for_table` was previously refactored specifically for single-responsibility (project history: Global Rule RN-002 audit). Its current query (`WHERE status='active' AND embedding_id IS NULL`) is the structural opposite of the purge target this change needs (`WHERE status='deprecated' AND embedding_id IS NOT NULL`) — folding both into one function would reintroduce the exact kind of multi-responsibility function that audit already removed.

## Goals / Non-Goals

**Goals:**
- A rule or lesson can be deprecated on its own, without a scope change, through the same human-approval governance every other knowledge write goes through.
- `superseded_by` becomes a real, queryable reference instead of a parsed string, for deprecations from both `deprecate_rule` and `promote_rule`.
- Deprecated rows stop being semantic-search candidates — by removal from the vector index, not just a client-side filter — including a one-time cleanup of rows already deprecated via `promote_rule` before this change ships.
- `query_rules`/`query_lessons` gain an explicit, opt-in way to see deprecated content (`include_deprecated=True`), consistent in both the SQL and semantic branches.

**Non-Goals:**
- Retrofitting `CHECK (status IN (...))` onto databases created before `schema.sql` already defined it — deferred to a separate hardening ADR (ADR-007, Decision §5).
- Unifying `promote_rule` and `deprecate_rule` into one code path. They remain distinct tools with distinct `rule_history.change_type` values (`'PROMOTED'` vs `'DEPRECATED'`); only the embedding-removal mechanism and the `get_rule_audit_log` read filter are shared.
- Reactivating a deprecated rule/lesson (no `reactivate_rule` tool). Out of scope; the design only ensures a *future* reactivation (however it lands) would be re-embedded automatically by the existing `generate_embeddings` logic, since clearing `embedding_id` on deprecation is itself a goal.
- Any change to `write_block`/`shift_offsets_after`'s existing contract — deprecation reuses `_mark_deprecated_in_md`, which already writes through `write_block`.

## Decisions

### 1. Deprecation stays inside the existing proposal/approval pipeline

`deprecate_rule` creates a `pending_proposals` row (`type="deprecate"`); `approve_proposal` gains a third dispatch branch, `_approve_deprecate_proposal`, parallel to the existing `_approve_update_proposal`. Rejected alternative: a `write`-level tool that mutates `status` directly (symmetric to how `promote_rule` works today). Rejected because it would create two different governance models for the same kind of state change — every other knowledge mutation (create, update) already requires an approved proposal, and `promote_rule`'s direct-write shape is legacy, not a pattern to extend.

### 2. Extend `create_pending_proposal` rather than writing a parallel insert

`create_pending_proposal` gains `type in ("update", "deprecate")` sharing the existing target-resolution branch, plus two new optional parameters, `reason: str | None` and `metadata: dict | None`, written into `pending_proposals`' already-existing columns. Rejected alternative: have `deprecate_rule`'s implementation `INSERT INTO pending_proposals` directly. Rejected because it would duplicate sequential-id generation, `strip_private_tags`, and scope/target validation that already exists and is already exercised by every other proposal type — exactly the kind of duplication the project's own DRY global rule flags.

### 3. `superseded_by` lives on `rule_history`/`lesson_history`, not on `rules`/`lessons`

A new nullable `superseded_by TEXT REFERENCES rules(id)` / `REFERENCES lessons(id)` column is added to the two history tables, not to the main `rules`/`lessons` tables. Rationale: `reason` already lives on history, not on the row itself, and a history table is the natural place for "what happened and why" — a row's current `status` is state, but *why* and *replaced by what* are facts about the deprecation event, which could in principle happen more than once in a row's life. Kept nullable and not required at the tool-parameter level (ADR-007 Decision §2): a deprecation without a replacement is legitimate, and the `.md`/history is the source of truth — it should not contain an invented value.

### 4. `get_rule_audit_log`'s read filter widens; `promote_rule`'s write value does not change

`deprecated_rules`'s query moves from `change_type = 'DEPRECATED'` to `change_type IN ('DEPRECATED', 'PROMOTED')`. Rejected alternative: change `promote_rule` to write `change_type='DEPRECATED'` instead of `'PROMOTED'`. Rejected because `'PROMOTED'` is an existing, already-relied-upon value (tests, any external consumer reading `rule_history` directly) carrying information `'DEPRECATED'` alone would lose — *why* the rule was deprecated (promoted elsewhere) is itself meaningful and distinct from a plain deprecation. Widening a read filter is strictly lower-risk than changing a write value with unknown consumers.

Consequence: rows written by `promote_rule` **before** this change ships will have `superseded_by IS NULL` in history (the column didn't exist yet) even though their free-text `reason` (`"Promoted to scope {new_scope_id}"`) still describes where they went. `get_rule_audit_log`'s response keeps surfacing `reason` as-is alongside the new `superseded_by`, so no information is lost for pre-existing rows — callers needing the destination scope for an old `PROMOTED` entry still read it from `reason`, same as today.

### 5. Embedding cleanup: delete from the vector store, via one shared helper

`vector_store.delete_rule`/`delete_lesson` (thin wrappers over `collection.delete(ids=[...])`) are called from a single new helper in `knowledge_management.py` (mirroring `_embed_and_upsert_after_approve`'s shape: best-effort, logged-and-swallowed on failure, never affecting a transaction that already committed), used by both `_approve_deprecate_proposal` and `promote_rule`. Rejected alternative: tag the ChromaDB metadata with `status='deprecated'` and filter at query time instead of deleting. Rejected per ADR-007: deletion is what actually delivers the efficiency motivating this change (smaller index, no wasted top-k slots), not just a client-side filter on top of a bloated index; reactivation is already handled for free by `generate_embeddings`'s existing `embedding_id IS NULL` re-embed query once this change also clears `embedding_id` on deprecation.

### 6. Backfill purge lives in a new sibling function, not inside `_generate_embeddings_for_table`

A new `_purge_deprecated_embeddings_for_table` function (same per-table shape as `_generate_embeddings_for_table`, called once for rules and once for lessons from `generate_embeddings`) handles `WHERE status='deprecated' AND embedding_id IS NOT NULL`. Rejected alternative: add a second query inside `_generate_embeddings_for_table` itself. Rejected because that function was already refactored once for single-responsibility (project history, Global Rule RN-002 audit) — its one job is "embed what's missing"; "purge what's stale" is a different query over a different predicate and belongs in its own function, called alongside it, not folded in.

### 7. `deprecate_rule` access level: `analyze`, not `write`

Matches `create_pending_proposal`'s own level: `deprecate_rule` only ever creates a `pending_proposals` row, it never mutates `rules`/`lessons`/the `.md` files itself — that happens in `approve_proposal` (`write`), consistent with how `extract_rules_from_transcript`/`create_pending_proposal` (propose) are `analyze` while `approve_proposal`/`promote_rule` (mutate) are `write`.

## Risks / Trade-offs

- **[Risk]** First `generate_embeddings` run after deploying this change may purge a large backlog of pre-existing `promote_rule`-deprecated rows in one pass, on top of its existing embed workload. → **Mitigation**: reuse the function's existing `scope_id` parameter for the purge query too, so an operator can run it incrementally per scope instead of one large全-scope pass; document the first post-deploy run as an explicit operational step in the proposal/rollout notes, not something that must happen automatically at migration time.
- **[Risk]** `promote_rule` and `deprecate_rule` sharing only the embedding-removal helper (not history semantics) could read as "these are now the same flow" to a future maintainer, who then conflates `'PROMOTED'` and `'DEPRECATED'` incorrectly. → **Mitigation**: docstring on the shared helper explicitly states it only handles vector-store cleanup, and `get_rule_audit_log`'s widened filter (Decision §4) plus its own docstring state why both values are accepted there specifically.
- **[Risk]** `vector_store.delete_rule`/`delete_lesson` called on an id that was never embedded (`embedding_id` already `NULL`) or that ChromaDB has no record of. → **Mitigation**: wrap the call in the same try/except/log pattern as `_embed_and_upsert_after_approve`; a delete on a non-existent ChromaDB id is a no-op there, but the wrapper must not assume that and must treat any exception as non-fatal regardless of cause.
- **[Risk]** `superseded_by` being `NULL` for all historical `PROMOTED` rows (Decision §4) could be mistaken for a bug by someone diffing old vs. new entries in `get_rule_audit_log` output. → **Mitigation**: `reason` remains populated and visible on those same rows; this is called out explicitly here and should be called out again in the tool's own docstring/response shape.

## Migration Plan

- New `src/meridian/db/migrations/005_deprecation_lifecycle.sql`: additive only (`ALTER TABLE ... ADD COLUMN superseded_by TEXT REFERENCES rules(id)/lessons(id)`, `CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status)`). No `NOT NULL`, no default requiring a backfill UPDATE — unlike migration 001's `lessons` columns, these are nullable from day one.
  - **Implementation correction (found during Task 1.1):** a Python dispatch branch for number `5` in `_apply_migration` *is* still needed, mirroring migration 1's own pattern — `initialize_db` always calls `apply_pending_migrations` even right after creating a brand-new database from `schema.sql` (which already defines `superseded_by`), and unlike `CREATE TABLE IF NOT EXISTS`/`CREATE INDEX IF NOT EXISTS` (what migrations 2-4 use), `ALTER TABLE ADD COLUMN` has no `IF NOT EXISTS` form in SQLite — it raises `duplicate column name` on a fresh database. The dispatch branch checks whether `rule_history` already has `superseded_by` and skips the file's statements if so, exactly like migration 1's check on `lessons`.
- `db/schema.sql` updated in the same change so fresh installs get the columns/index directly (same pattern migration 004's own comment documents: "Fresh installs get the same data directly from schema.sql; this migration backfills existing databases").
- Deploy order: ship code + migration together — `initialize_db()` already runs pending migrations unconditionally on every startup, so no separate manual migration step is needed.
- Recommended post-deploy operational step (not part of the migration itself): run `generate_embeddings` once (optionally per scope) to purge any rows deprecated via `promote_rule` before this change shipped — see Risk above.
- Rollback: the migration only adds nullable columns and an index, safe to leave in place even if the feature code is rolled back (old code simply never reads/writes the new column). If the feature itself needs disabling without a schema rollback, remove `deprecate_rule` from `TOOL_ACCESS_LEVELS`/`server.py` — no data correctness issue results from the proposal/approval branch being unreachable while the columns remain.

## Open Questions (resolved during implementation)

- **`superseded_by` validation:** resolved as leaned — `create_pending_proposal` validates that `superseded_by`, when provided, references an existing `status='active'` rule/lesson, raising `ValueError` otherwise (Task 2.3).
- **`generate_embeddings` purge scoping:** resolved as leaned — `_purge_deprecated_embeddings_for_table` accepts the same `scope_id` parameter `generate_embeddings` already threads through to the embed side, so one call scopes both (Task 7.1).

One naming correction surfaced during implementation, not anticipated here: the function carrying `deprecated_rules`/`superseded_by` (Decision 4, Risks) is `get_rule_audit_log`, not `get_rule_timeline` — a different, single-rule function. This document and the capability spec were corrected to name it accurately; see Task 8.1's note.
