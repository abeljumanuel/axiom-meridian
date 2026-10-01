# ADR-007: Standalone Deprecation Lifecycle for Rules and Lessons

**Status:** Proposed
**Date:** 2026-10-01
**Product:** Axiom Meridian
**Author:** Axiom JUMA
**Deciders:** abeljuanmanuel
**Implements:** the deprecation-lifecycle gap raised in the user's RN-077 report (2026-10-01), extending `changes/test-20160420.md` §LIFECYCLE-01 (`deprecate_lesson`) and §BUG-001 (`status` without `CHECK`)

---

## Context

A user report (2026-10-01) describes needing to deprecate `RN-077` without moving it to another scope, and finds that the only existing path to `status='deprecated'` is `promote_rule`, which couples deprecation to a scope change. The report proposes five changes, prioritizing (1) a standalone `deprecate_rule` operation and (2) an `include_deprecated` flag on `query_rules`, and deferring (3) excluding deprecated entries from semantic search, (4) always resolving deprecated rules in `get_rule_context`, and (5) a `CHECK` constraint on `status` to a second, "hardening" tranche.

Reading the implementation (not just the PRD) surfaced three facts the report could not have known from the spec alone:

1. **The semantic-search path has no `status` filtering of any kind.** `knowledge_consumption.py::query_rules` (and `query_lessons`) filters `status = 'active'` only in its plain-SQL branch (`query_rules`, scope-only SQL path). The `query_text` branch calls `vector_store.search_rules`/`search_lessons`, whose `where_filter` only constrains `scope_id` — `_rule_embedding_metadata`/`_lesson_embedding_metadata` (`knowledge_management.py`) never attach `status` to the Chroma metadata in the first place. A rule deprecated today remains a semantic-search candidate indefinitely. This makes the report's point 3 a **correctness bug**, not an efficiency item, and it directly undermines point 2 (`include_deprecated=false` by default) for any query that supplies `query_text`.
2. **`superseded_by` is not a column anywhere.** `get_rule_timeline` derives it by string-parsing the free-text `reason` field of a `rule_history` row with `change_type='PROMOTED'` — and that `reason` is literally `f"Promoted to scope {new_scope_id}"` (`promote_rule`), i.e. a scope id, not an `RN-`/`LL-` code. Worse, the query that builds `deprecated_rules` filters on `change_type = 'DEPRECATED'`, which `promote_rule` never writes (it writes `'PROMOTED'`) — so **no rule deprecated via `promote_rule` appears in `get_rule_timeline`'s `deprecated_rules` today.**
3. **The `CHECK` constraint the report says is missing (point 5) already exists** in `db/schema.sql` for both `rules.status` and `lessons.status`, with a supporting index for `rules` (`idx_rules_status`) but not for `lessons`. What is actually missing is a migration retrofitting the `CHECK` onto databases created before it was added to `schema.sql` — a materially different, lower-urgency problem (SQLite cannot `ALTER TABLE ADD CHECK`; retrofitting requires a full table rebuild).

These three facts change the shape of the recommended first tranche relative to the report's own proposal.

---

## Decision

Adopt the report's **Option 1** (`deprecate_rule` as a `type="deprecate"` proposal routed through `approve_proposal`) as the base, extended as follows. All of the below ship together as the first tranche — point 3 is pulled forward from the report's second tranche for the reason in Context §1.

### 1. `deprecate_rule(rule_id, reason, superseded_by=None)` — new tool, `analyze` access level

Creates a `pending_proposals` row with `type="deprecate"`, `target_id=<RN-/LL- id>`, `reason` (existing column), `metadata={"superseded_by": ...}` (existing column) — no schema change to `pending_proposals` (`type` is unconstrained `TEXT NOT NULL`). Designed generically over `RN-`/`LL-` by reusing `_resolve_update_target`'s existing prefix dispatch, so the same tool and proposal type close `changes/test-20160420.md`'s LIFECYCLE-01 (`deprecate_lesson`) as a side effect, instead of building a second parallel path for lessons.

`approve_proposal` gains a third branch, `_approve_deprecate_proposal`, parallel to the existing `_approve_update_proposal`:
- `UPDATE {table} SET status='deprecated'`
- reuse `_mark_deprecated_in_md` (already generic over `file_path`/`offset`/`length`, not coupled to `promote_rule`)
- `INSERT INTO {hist_table} (..., change_type='DEPRECATED', reason, superseded_by)`
- mark the proposal `approved`
- all in one transaction, same pattern as `_approve_update_proposal`

Nothing changes about the governance model: deprecation still requires human approval via `approve_proposal`, exactly as `update`-type proposals do today.

### 2. `superseded_by` as a structured, nullable column — not required

Add `rule_history.superseded_by TEXT REFERENCES rules(id)` and `lesson_history.superseded_by TEXT REFERENCES lessons(id)` (additive `ALTER TABLE`, no `CHECK` involved, safe on existing databases). Kept **recommended, not required**: a deprecation without a replacement is a legitimate outcome (a rule that simply stopped applying), and forcing the field would push the proposer toward inventing a value — at odds with the project's "the `.md`/history is the source of truth" posture.

**Required companion change:** widen `get_rule_timeline`'s `deprecated_rules` filter from `change_type = 'DEPRECATED'` to `change_type IN ('DEPRECATED', 'PROMOTED')`. Without this, the new structured `superseded_by` only ever gets populated for the new `deprecate_rule` path, while `promote_rule`-originated deprecations keep relying on the broken string-parse fallback — two inconsistent mechanisms serving the same displayed field. This is a one-line query change but is load-bearing for point 2 to mean anything project-wide.

### 3. Vector-store removal on deprecation, pulled into the first tranche

Add `vector_store.delete_rule`/`delete_lesson` (thin wrappers over `collection.delete(ids=[...])`), called post-commit from `_approve_deprecate_proposal` with the same failure-isolation contract `_embed_and_upsert_after_approve` already documents ("a failure here ... must never affect an approval that already succeeded"). Also clear `embedding_id = NULL` on the row, so a future reactivation is picked up automatically by `generate_embeddings`'s existing `WHERE status = 'active' AND embedding_id IS NULL` query — no new reactivation tooling needed.

Removal (not a `status` metadata flag) was chosen over filtering, because it is what actually delivers the efficiency the user asked about (smaller index, no wasted top-k slots, no wasted compute) rather than a client-side filter on top of a bloated index — consistent with the report's own framing ("es lo que da la eficiencia real").

**Backfill requirement:** rules/lessons already deprecated via `promote_rule` in production are already polluting the semantic index today and have no path to clean up, since `generate_embeddings` only processes `status='active'` rows. Extend `generate_embeddings` (not a new tool) to also purge any `status='deprecated' AND embedding_id IS NOT NULL` row it finds, reporting a `purged` count alongside its existing `processed`/`skipped`/`errors`.

**Consistency requirement:** `promote_rule` must call the same embedding-removal helper `_approve_deprecate_proposal` uses, so a rule deprecated via promotion is cleaned from the index immediately too, rather than waiting on the next `generate_embeddings` run. Leaving this asymmetric (instant cleanup for the new tool, deferred cleanup for `promote_rule`) is accepted only as transitional, tracked under Risks below, not as a permanent gap.

### 4. `include_deprecated=false` default on `query_rules`/`query_lessons` — both branches

Applies to the plain-SQL branch (already filters `status='active'`, gains the parameter) and the semantic branch (gains it by construction, since deprecated rows are no longer in the vector store per §3; when `include_deprecated=true`, the SQL branch drops its `status` filter and the semantic branch has nothing extra to do, since removed embeddings are not re-added by this flag — a full view of deprecated content still goes through `get_rule_context`/`get_rule_timeline`, which already resolve deprecated rows unconditionally).

### 5. `CHECK` retrofit and `lessons.status` index — deferred to a follow-up hardening ADR

`schema.sql` already enforces `CHECK (status IN ('active', 'deprecated'))` for both tables on fresh installs (`rules`, `lessons`) and already indexes `rules.status`. This tranche only adds the missing `CREATE INDEX idx_lessons_status ON lessons(status)` (cheap, additive, bundled into the same migration as the `superseded_by` columns). Retrofitting the `CHECK` onto pre-existing databases requires a full table rebuild (new table, copy, drop, rename, recreate every index and every FK pointing at `rules`/`lessons` from `rule_attributes`, `rule_tags`, `rule_lesson_links`, `lesson_history`, etc.) — too much risk for an exposure that today is limited to controlled application code (`promote_rule`, `approve_proposal`'s create path, the new `deprecate_rule`), none of which writes unvalidated `status` values. Revisit if a future tool ever writes `status` outside `approve_proposal`'s choke point.

---

## Consequences

### Positive

- RN-077-shaped cases (deprecate without promoting) are solved directly, with full governance (proposal → approval) preserved.
- `LIFECYCLE-01` (`deprecate_lesson`) closes as a side effect of the same design, with no separate implementation.
- The semantic-search correctness bug (deprecated content surfacing in `query_text` results with no filter at all) is fixed, not just documented as a future optimization.
- `superseded_by` becomes a real, queryable reference instead of a parsed scope-id string, for both deprecation origins (`deprecate_rule` and `promote_rule`) once `get_rule_timeline`'s filter is widened.
- The vector index actually shrinks as rules/lessons are deprecated, instead of growing without bound — the efficiency outcome the user asked about.

### Negative / Trade-offs (accepted)

- **First-tranche scope is larger than the report proposed**: touches `vector_store.py`, `generate_embeddings`, `promote_rule`, and `get_rule_timeline`, not just a new tool and a query flag. Accepted because shipping only points 1-2 would leave `include_deprecated=false` silently broken for any `query_text` call — a worse outcome than a larger, coherent PR.
- **`superseded_by` is not enforced**, so some deprecations will carry no replacement reference. Accepted; governance can push for it at review time (the human approver can reject a proposal that should name a replacement) without a database-level restriction.
- **`promote_rule` and `deprecate_rule` share an embedding-removal helper but are not otherwise unified** — `promote_rule` still logs `change_type='PROMOTED'`, not `'DEPRECATED'`, to avoid changing its existing, already-relied-upon history semantics. The two are reconciled only at the `get_rule_timeline` read layer (§2), not by collapsing them into one code path.
- **The `CHECK` retrofit is deferred**, leaving pre-existing databases theoretically able to accept an invalid `status` value through a future, as-yet-unwritten code path. Accepted given today's exposure is zero outside `approve_proposal`.

---

## Related decisions

- Builds on the proposal-lifecycle invariant established across the codebase (`approve_proposal` as the single choke point for all knowledge writes) rather than introducing a parallel write path.
- Extends the embedding-visibility work from the immediately preceding commit (`caa1de4`, "surface embedding status on approve, warm up embedder at startup") to the deprecation direction: that commit surfaced embedding status on creation/update; this ADR's `purged`/`embedding_removed` reporting (Decision §1, §3) is the symmetric counterpart for removal.
- Supersedes none of ADR-001 through ADR-006; does not touch serialization (ADR-001), dynamic attributes (ADR-002), legacy scope inference (ADR-003), id counters (ADR-004), the indexed read path (ADR-005), or connection/parser hardening (ADR-006).
