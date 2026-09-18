# ADR-005: Indexed Read Path with Per-File Freshness (Opción C, Phase 2)

**Status:** Accepted and implemented
**Date:** 2026-09-18
**Product:** Axiom Meridian
**Author:** Axiom JUMA
**Deciders:** abeljuanmanuel
**Implements:** Phase 2 (T04–T11) of `plan-rendimiento.md`, completing the Option C decision in `archy-rendimiento.md` (Phase 1 — id_counters, N+1 fix, migration runner — is [ADR-004](ADR-004-id-counters-and-nplus1-fix.md))

---

## Context

[ADR-004](ADR-004-id-counters-and-nplus1-fix.md) fixed two of the four unbounded cost mechanisms `reporte-rendimiento.md` documented (the `access_log` ID-generation scan, the `filter_by_attributes` N+1) but deliberately deferred the third and largest: `detail="full"` queries re-reading the entire source `.md` file once per row (`_read_positional_text`), which `archy-rendimiento.md` identifies as the one mechanism Option A/B cannot fix and Option C exists specifically to address. This ADR implements that remaining piece, plus the two components `archy-rendimiento.md` bundles with it: exact tag matching (replacing `tags LIKE '%tag%'`) and the offset fragility mitigation (a single write helper).

This ADR was originally going to be filed as "ADR-003" per `archy-rendimiento.md` §7's own suggestion, but that number was already used by the scope-inference fix, and "ADR-004" by Phase 1 — hence 005.

---

## Decision

Implement Option C's read path as specified in `archy-rendimiento.md` §6 (Mermaid diagram) and `plan-rendimiento.md` T04–T11, with the deviations noted under Consequences.

### T04 — `indexed_files` / `rule_tags` / `lesson_tags` + backfill

Three new tables (`db/schema.sql` for fresh installs, `db/migrations/003_read_index.sql` for existing ones):

```sql
indexed_files(file_path PK, mtime, content_hash, updated_at)
rule_tags(rule_id, tag, PRIMARY KEY(rule_id, tag))
lesson_tags(lesson_id, tag, PRIMARY KEY(lesson_id, tag))
```

`utils/read_index.backfill_read_index()` (dispatched by migration 003 in `db/migrations.py`, mirroring the `seed_id_counters` pattern from ADR-004) populates both from existing data: tags parsed from the legacy `rules.tags`/`lessons.tags` JSON column, `indexed_files` fingerprinted for every distinct `file_path` that still exists on disk (a referenced-but-missing file is simply not indexed — it will correctly report `STALE_INDEX`, the same outcome `path.exists()` produced before). A post-backfill verification (`migrations.py::_verify_migration_003`) checks `COUNT(rule_tags)`/`COUNT(lesson_tags)` against the parsed JSON arrays and `COUNT(indexed_files)` against files actually present on disk, raising (and triggering the T01 runner's rollback) on any mismatch.

**Bug found and fixed along the way, not originally in scope:** the E2E test built for T10 (below) — the first test in this whole effort to run migration 001 against a `lessons` table that actually has rows — hit `sqlite3.OperationalError: Cannot add a column with non-constant default`. SQLite rejects `ALTER TABLE ADD COLUMN ... DEFAULT (datetime('now'))` once the table is non-empty; ADR-004's Phase 1 testing only ever exercised this against an *empty* legacy `lessons` table, so it went undetected. Fixed in `001_lessons_columns.sql` (columns added without a default, backfilled via `UPDATE ... WHERE ... IS NULL`) and in `knowledge_management.py` (the two `lessons` INSERT statements now set `created_at`/`updated_at` explicitly via `datetime('now')` in the SQL, rather than relying on a column-level default that a migrated database's `ALTER TABLE` can no longer attach). This is called out explicitly because it means **ADR-004's "135 unit tests / 25 integration tests pass" claim was true but insufficiently tested against realistic field data** — a lesson for how this capstone's own testing should be evaluated going forward: an empty-table migration test is not equivalent to a populated-table one.

### T05 — `write_block`, the single write choke point

`utils/read_index.write_block(conn, path, new_content)` writes a `.md` file's bytes and upserts its `indexed_files` row (hashing the bytes just written, no extra read) in one call. The three existing writers — `_append_atomic_block` (proposal creation), the byte-slice replace in `approve_proposal`'s `update` path, and `_mark_deprecated_in_md` (`promote_rule`) — now go through it exclusively; `grep -n 'write_bytes\|open("ab")' src/meridian/tools/knowledge_management.py` shows exactly one hit, inside `write_block` itself. `sync_tags()` (DELETE + INSERT of the normalized set) keeps `rule_tags`/`lesson_tags` in step at every point `rules.tags`/`lessons.tags` is written: `approve_proposal` (both create and update paths) and `index_rules_from_markdown`/`index_lessons_from_markdown` (which also call `refresh_indexed_file()` once per processed file, not per block, via `if blocks: refresh_indexed_file(...)`).

This is the direct mitigation for `archy-rendimiento.md` §7-Riesgo 1 ("a write path forgets to refresh `indexed_files`"): there is now exactly one function capable of writing a knowledge `.md` file's bytes, and it cannot write without also updating the fingerprint.

### T06 — Indexed reads with per-file freshness

`utils/read_index.check_files_fresh(conn, file_paths)` takes the *distinct* file paths from a result set (not one per row) and returns fresh/stale per file: `stat()` once, compare `mtime` to the indexed value (fast path, no content read), and only on a mismatch fall back to a sha256 comparison against `content_hash` (verified by benchmark: 10 rows from the same fresh file → 1 `stat()` call, 0 content reads). `knowledge_consumption._resolve_full_text()` uses this to attach `text`/`error` to each row of `query_rules`, `query_lessons`, and `get_rule_context` — reading `rules.text` / `lessons.what_happened` (already loaded by `SELECT *`), never the file, when fresh. RAG-path rows (`file_path is None`, text lives only in ChromaDB) bypass the freshness check entirely and always serve their embedded text, matching the pre-existing behavior of `_read_positional_text` for that case. `_read_positional_text` and every `Path.read_bytes()` call are gone from `knowledge_consumption.py`.

The four `tags LIKE '%tag%'` filters (`query_rules`/`query_lessons`, SQL path) became `EXISTS (SELECT 1 FROM rule_tags rt WHERE rt.rule_id = rules.id AND (rt.tag = ? OR ...))` — exact equality, batched OR clauses for a list of tags, same parameter-binding discipline as the rest of the codebase.

### T07/T08 — Contract tests and suite adaptation

`tests/integration/test_external_edits.py` (new): a query right after indexing serves fresh text with no error; an external edit (bypassing Meridian) marks **every** row backed by that file `STALE_INDEX` — not just the row whose bytes moved, which is the actual behavioral difference file-granularity introduces over the old per-row-offset check; re-indexing after an external edit recovers service. `tests/unit/test_read_index.py` (new, 12 cases) covers `write_block`, `check_files_fresh` (including the one-stat-per-distinct-file property via a `Path.stat` spy), and `sync_tags` in isolation.

Only one existing test needed adaptation (T08's actual scope turned out to be much smaller than planned): `test_query_rules_full` asserted `"Regla:" in data[0]["text"]`, which was true only because the old code served the *raw markdown block* (header, field labels, everything) — the new code serves the *parsed* `rules.text` value, which is the clean rule content without field labels. This is the intended, documented consequence of serving text from the index instead of the file. Every other integration test (`test_proposals_flow`, `test_audit_and_extraction`, `test_skill_generator`) passed unchanged.

### T10 — Field migration E2E test

`tests/integration/test_field_migration_e2e.py`: builds a database on the pre-migration schema (no `id_counters`/`indexed_files`/`rule_tags`/`lesson_tags`, `lessons` missing the 001 columns) with realistic data — two rules and a lesson with real `.md` files behind them, `rule_history`, an `access_log` row at `al-9999` (the padding boundary ADR-004 specifically seeds around), a pending proposal — then runs `initialize_db()` (the full 001→002→003 chain) and verifies: no data lost, all three migrations' schema changes present, `id_counters` seeded past the real max with no collision (`next_rule_code` → `RN-JAVA-003`, `next_sequential_id` → `al-10000`), tags and `indexed_files` backfilled with exact, verified counts, and — critically — that normal tool usage (`query_rules`, `approve_proposal`) works correctly immediately afterward on the migrated database. This test is what caught the non-constant-default bug above.

Not implemented from T10's original scope: a dedicated corrupted-migration-on-this-exact-fixture scenario and a rerun-idempotency scenario on this exact fixture. Both properties are already covered generically (and pass) in `tests/unit/test_migrations.py` against the same runner — judged redundant to re-prove them again bespoke to this fixture, given time already spent finding and fixing the real defect above.

### T11 — Performance regression benchmarks

`tests/benchmarks/test_perf_regression.py`, gated behind a `benchmark` pytest marker excluded from the default run (`addopts = "-m 'not benchmark'"` in `pyproject.toml`), run explicitly via `uv run pytest tests/benchmarks -m benchmark`:

- `query_rules(detail="full")` per-row cost at 2000 rules in one file is within 2x the per-row cost at 100 rules (plan's numeric criterion) — passes comfortably, since cost no longer depends on file size at all.
- `next_sequential_id` cost with 50,000 `access_log` rows is within 1.5x the cost with 100 (plan's numeric criterion) — passes, exercising ADR-004's `id_counters`.
- `EXPLAIN QUERY PLAN` on a `rule_history` lookup by `rule_id` asserts `idx_rule_history_rule_id` usage.

**Deviation:** implemented with plain `time.perf_counter()` rather than adding the `pytest-benchmark` dependency the plan specified. Reason: this environment's `.venv` is separately documented as fragile (`reporte-instalacion.md` — editable install doesn't expose the package correctly), and adding a new dependency (`uv add`, touching `uv.lock`) was judged an avoidable risk for a benchmark whose numeric criteria are fully expressible without it. The acceptance criteria (numeric thresholds, default-run exclusion) are met either way.

---

## Consequences

### Positive

- The mechanism `archy-rendimiento.md` identified as the one Option A/B structurally cannot fix — `detail="full"` cost scaling with file size — is gone, verified by benchmark and by a `Path.stat`-spy unit test (1 stat, 0 content reads, per distinct fresh file).
- `audit_pr`/`check_feature_against_rules` — the heaviest consumers per `reporte-rendimiento.md` §3.1 — benefit automatically; they call `query_rules`/`query_lessons` with `detail="full"` and inherit the fix without their own changes.
- Tag filtering became correct, not just faster: `tags="go"` no longer matches `"golang"` (a real substring-matching bug in the old `LIKE '%go%'`, same defect class as [ADR-003](ADR-003-legacy-scope-inference.md)'s scope-inference fix, independently discovered here).
- Offset fragility (`reporte-rendimiento.md` §3.5) no longer affects reads at all — only `write_block`'s callers still use offsets, and only as write-path metadata.
- Found and fixed a real, previously-undetected migration defect (the non-constant-default bug above) that would have broken migration 001 on essentially every real installed database with existing lessons.
- 180 unit + integration tests pass (up from ADR-004's 147+25=172); 3 benchmark tests pass with the plan's exact numeric criteria.

### Negative / Trade-offs (accepted, matching `archy-rendimiento.md`'s own risk analysis)

- **mtime-preserving adversarial edits are not caught.** `check_files_fresh`'s fast path trusts `mtime` without hashing when it matches the indexed value; an edit that changes content but resets `mtime` back to the exact original value (e.g. via `os.utime`) would report `fresh` incorrectly. This is `read_index.py`'s documented limitation, not an oversight: T06's own acceptance criterion demands "0 content reads when fresh," which is logically incompatible with always-hash. Mirrors the same class of limitation in any mtime-based cache (build tools, bundlers). Not exploitable by the normal write paths (all of which go through `write_block`, which always updates `mtime` correctly); only relevant to a deliberately adversarial external actor with filesystem access, which is already outside Meridian's threat model (README's security levels govern *tool* access, not filesystem access).
- **The legacy `tags` JSON column is now write-only for filtering purposes** — still populated (for backward-compat / anything reading it directly), but no longer read by `query_rules`/`query_lessons`. Two representations of the same data now coexist; not unified in this pass.
- **Fixed per-operation costs remain untouched** (Option B, still not adopted — 14 ephemeral connections, repeated pragmas/filesystem checks). Unchanged from ADR-004.
- **T10's originally-planned failure/idempotency variants on the field fixture were not added**, judged redundant given generic coverage exists; if the specific interaction between a populated field database and a mid-chain migration failure ever needs re-verification, that's the gap.
- **`pytest-benchmark` was not added**, a documented deviation from the plan's letter (see T11 above); the acceptance criteria are met by the alternative implementation.

---

## Alternatives considered

Superseded by `archy-rendimiento.md`'s decision — not re-litigated here (see ADR-004's own "Alternatives considered" for A vs. B vs. C). The only choice at this ADR's level: do Phase 2 as one delivery (as done here) versus splitting T04–T06 (schema+write+read) from T07–T11 (verification+docs) into separate deliveries. Rejected splitting further: T04/T05/T06 are load-bearing on each other's contract (the `indexed_files` semantics) in a way that makes a genuinely useful intermediate checkpoint hard to define, unlike the Phase 1/Phase 2 split itself (ADR-004 vs. this ADR), which *did* have a clean, independently valuable boundary.

---

## Related decisions

- [ADR-004: ID Counters and N+1 Fix](ADR-004-id-counters-and-nplus1-fix.md) — Phase 1 of this same Option C decision; this ADR completes it.
- [ADR-003: Legacy Scope Inference](ADR-003-legacy-scope-inference.md) — same defect class (substring vs. exact/word-boundary matching) independently found in tag filtering here.
- [ADR-001: Response Serialization Format](ADR-001-response-serialization-format.md) — the `STALE_INDEX` shape-per-row contract this ADR preserves while changing its granularity.
- `archy-rendimiento.md` / `plan-rendimiento.md` — architectural decision and full 11-mission plan this ADR completes.
- **Pending work:** unify the legacy `tags` JSON column with `rule_tags`/`lesson_tags` (currently duplicated); Option B's fixed-cost-per-operation concerns (connection pooling, pragma caching), still not addressed by either ADR-004 or this one.
