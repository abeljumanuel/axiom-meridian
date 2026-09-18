# ADR-004: Performance Remediation, Phase 1 — Migration Runner, ID Counters, N+1 Fix

**Status:** Accepted (Phase 1 of 2 — implemented); Phase 2 not started
**Date:** 2026-09-17
**Product:** Axiom Meridian
**Author:** Axiom JUMA
**Deciders:** abeljuanmanuel
**Implements:** Phase 1 (T01, T02, T03) of `plan-rendimiento.md`, itself implementing the Option C decision in `archy-rendimiento.md`

---

## Context

`reporte-rendimiento.md` (2026-06-11) documented four independent, unbounded performance costs: a `MAX(id) ... LIKE 'prefix-%'` full-table scan on `access_log` in the critical path of all 26 MCP tools, an N+1 query pattern in `filter_by_attributes`, a full-file reread per row on `detail="full"` queries, and 14 ephemeral SQLite connections per operation. `archy-rendimiento.md` decided **Option C — lectura servida desde el índice**, which by the report's own definition subsumes Option A's hot-path fixes (id counters, N+1 fix, missing indices) as prerequisites. `plan-rendimiento.md` sequenced the implementation into 11 missions across 3 phases; its own naming convention called the documentation mission `T09 — ADR-003`, but that number was already claimed by [ADR-003](ADR-003-legacy-scope-inference.md) (scope inference, decided earlier in this same work session) — hence this ADR is numbered 004.

This ADR documents **only Phase 1** (T01–T03, the "quick wins" — I1 in the plan's integration map): the migration runner, ID counters, and N+1 fix. **Phase 2** (T04–T11: `indexed_files`/`rule_tags`/`lesson_tags`, the `write_block` helper, the indexed read path, and the `STALE_INDEX` granularity change) is the larger, riskier half of Option C — it changes an observable contract (`STALE_INDEX` from per-row to per-file) and requires a data backfill on installed bases. It has **not** been implemented and is deliberately left open; see **Related decisions**.

---

## Decision

Implement T01, T02, and T03 from `plan-rendimiento.md` as specified, with the deviations noted under Consequences.

### T01 — Migration runner (`src/meridian/db/migrations.py`)

No mechanism previously applied any file under `db/migrations/` — `001_lessons_columns.sql` was dead weight (see [ADR-002](ADR-002-dynamic-context-attributes.md)'s sibling finding in `reporte-indexacion.md`). The new runner:

- Discovers `NNN_*.sql` files, tracks progress via `PRAGMA user_version` (not a bookkeeping table — the plan's chosen design).
- Copies the database to `<name>.bak-<timestamp>` before touching anything, only when at least one migration is pending.
- Applies each migration in its own transaction; a failure rolls back that migration only (earlier ones in the same run stay committed) and raises with the backup path.
- Special-cases migration `001` (detect via `PRAGMA table_info(lessons)` whether the columns already exist — true for any database created after `schema.sql` was updated — and skip the `ALTER TABLE` statements without failing).
- `initialize_db()` calls it unconditionally, on both fresh and existing databases.

### T02 — `filter_by_attributes` N+1 fix (`src/meridian/utils/scope_resolver.py`)

Replaced the per-`rule_id` query with a single `WHERE rule_id IN (...)` query, batched at 500 IDs (SQLite's `SQLITE_MAX_VARIABLE_NUMBER` safety margin), grouped in Python. ADR-002's conservative-inclusion semantics (no attributes → include; unknown key → include; AND logic on matching keys) are preserved exactly — the rewrite only changes *how* the data is fetched, not the filtering logic itself.

### T03 — ID counters (`id_counters` table + `src/meridian/utils/id_generator.py`)

`next_rule_code`, `next_lesson_code`, and `next_sequential_id` now allocate from `id_counters(name, next)` via `UPDATE ... RETURNING`, an O(1) atomic increment, instead of `SELECT MAX(id) LIKE 'prefix-%'`. Public signatures are unchanged (same 15 call sites untouched). External code formats (`RN-{TECH}-NNN`, `LL-{TECH}-NNN`, `{prefix}-NNNN`) are unchanged, including padding overflow behavior (`…9999` → `…10000`, never colliding).

`seed_id_counters()` backfills counters from the **real numeric maximum** per prefix/segment (not lexicographic `MAX()`, which breaks past 999/9999 per `reporte-rendimiento.md` §3.3) — invoked once by migration `002_id_counters.sql`, idempotent via `ON CONFLICT ... DO UPDATE SET next = MAX(next, excluded.next)` (never lowers an already-advanced counter).

`schema.sql` gained the `id_counters` table and the four indices T03 specifies (`rule_history(rule_id)`, `lesson_history(lesson_id)`, `pending_proposals(scope_id)`, `pr_audits(pr_ref, project_id)`) for fresh installs; `002_id_counters.sql` adds the same via `CREATE TABLE/INDEX IF NOT EXISTS` for installed databases.

### Tests

`tests/unit/test_migrations.py` (new, 5 cases — no-op on fresh DB, legacy DB gets migration 001 applied with a backup created, idempotent re-run creates no second backup, failing migration rolls back with backup, partial failure keeps earlier migrations in the same run committed). `tests/unit/test_id_generator.py` (rewritten, 10 cases — first allocation, consecutive increments, seeding from existing data, padding overflow, no-op seeding on empty DB, seeding never lowers an advanced counter). `tests/unit/test_scope_resolver.py` (+1 case — 1000 `rule_ids` filtered with a `set_trace_callback` spy asserting exactly 2 queries, not 1000).

---

## Consequences

### Positive

- Verified via `EXPLAIN QUERY PLAN`: `rule_history`/`lesson_history`/`pr_audits` lookups now use the new indices (`SEARCH ... USING INDEX idx_*`), confirmed against a live test database.
- `grep -rn "MAX(" src/` shows zero remaining full-table-scan `MAX(...) LIKE` patterns; the only `MAX(...)` left is the scalar `MAX(next, excluded.next)` comparison in the counter seed's `ON CONFLICT`, which is O(1).
- 135 unit tests pass (was 114 before this work began across this session, including ADR-003's 9); 25 relevant integration tests (`test_proposals_flow`, `test_index_and_query`, `test_audit_and_extraction`, `test_skill_generator`) pass unchanged — no observable behavior regression in flows exercised by the existing suite.
- `ruff check` clean on every touched file.
- The migration runner is now real infrastructure: `002_id_counters.sql` is the first migration to actually exercise it end-to-end (001 predates the runner and is special-cased), and any future migration (including Phase 2's `003_read_index.sql`) can build on it directly.

### Negative / Trade-offs

- **`grep -rn 'LIKE' src/meridian/utils/id_generator.py` is not literally zero**, contrary to T03's acceptance criterion as written. `seed_id_counters()` — the one-time backfill helper — still uses `LIKE 'prefix-%'` to find existing rows to seed from; this is unavoidable (it's reading historical data, not generating new IDs) and doesn't run on the hot path (only once, from migration 002). The criterion's letter isn't met; its actual intent (no scan in the ID-generation hot path) is.
- **Phase 1 alone does not fix the degradation that scales worst.** Per `archy-rendimiento.md` §2's own framing, the `access_log`/N+1/counter costs are two of three unbounded mechanisms; the full-file reread on `detail="full"` (the one Option C exists specifically to fix) is untouched. `audit_pr`/`check_feature_against_rules` — the heaviest consumers — see no improvement from this ADR alone.
- **The fixed per-operation cost (14 ephemeral connections, repeated pragmas/filesystem checks) is unchanged.** This was Option B's concern, explicitly not adopted by `archy-rendimiento.md`, and Phase 1 doesn't touch it either.
- **Backup files accumulate.** Every machine that runs a version with pending migrations gets a `meridian.db.bak-<timestamp>` it must clean up manually; no retention policy exists yet.

---

## Alternatives considered

Superseded by `archy-rendimiento.md`'s decision (Option C over A/B) — not re-litigated here. The only choice made at this ADR's level was **sequencing**: implement Phase 1 now, defer Phase 2. Rejected alternative: implement all of Option C (T01–T11) in one pass. Rejected because Phase 2 changes an observable contract (`STALE_INDEX` granularity), requires a backfill migration over installed bases with a formal rollback story, and — per the plan's own estimate — represents 6 of the 9 person-days of this decision. Compressing that into the same session as Phase 1 trades a verifiable, low-risk delivery for an unverified, high-risk one; `archy-rendimiento.md` §7's own risk analysis (Riesgo 1 and 2) argues for exactly this kind of staged rollout.

---

## Related decisions

- `reporte-rendimiento.md` / `archy-rendimiento.md` / `plan-rendimiento.md` — evidence, decision, and full 11-mission plan this ADR partially implements.
- [ADR-002: Dynamic Context Attributes](ADR-002-dynamic-context-attributes.md) — `filter_by_attributes`' conservative-inclusion semantics, preserved exactly by T02.
- [ADR-003: Legacy Scope Inference](ADR-003-legacy-scope-inference.md) — the ADR that claimed number 003 before this one, hence the renumbering.
- **Pending work (Phase 2, T04–T11):** `indexed_files`/`rule_tags`/`lesson_tags` migration with backfill, the `write_block` write-path helper, the indexed read path replacing `_read_positional_text`, `STALE_INDEX` granularity change (row → file), exact tag matching, contract tests, integration-suite adaptation, an E2E migration test over a populated field database, and a regression benchmark. Should become its own ADR (working title: ADR-005, since 003 and 004 are now taken) when undertaken.
