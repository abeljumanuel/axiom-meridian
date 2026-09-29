# ADR-006: Connection Hardening (busy_timeout + early commit) and Atomic Parser Robustness

**Status:** Accepted
**Date:** 2026-09-22
**Product:** Axiom Meridian
**Author:** Axiom JUMA
**Deciders:** abeljuanmanuel
**Implements:** the two decisions documented in `reporte-tecnico-conexiones-concurrentes-y-parser-atomico-2026-09-22.md` (sections 4.1 and 4.2)

---

## Context

Deploying Meridian to a test environment surfaced two failures: (A) updating a Global Rule failed unless only one SQLite connection was open at a time, and (B) indexing the knowledge base failed until the atomic parser was modified — the user's own fix for (B) does not compile (`re.error: unbalanced parenthesis` on import, reproduced in the technical report's section 3.2) and its companion change (`_KNOWN_FIELD_NAMES`) silently corrupts the `text` field of every parsed `LL-*` lesson block, since it omits the five lesson-specific field labels (`Impacto`, `Causa raíz`, `Resolución`, `Originó regla`, and implicitly `Qué pasó` itself as a stop condition for the fields after it).

`reporte-tecnico-conexiones-concurrentes-y-parser-atomico-2026-09-22.md` documents both problems with 4 options each (A–D per problem). Problem A is not new: `reporte-rendimiento.md` (2026-06-11) already identified "14 ephemeral SQLite connections per operation" as a fixed per-operation cost, and `archy-rendimiento.md` explicitly chose **Option C** (indexed read path) over **Option B** (connection pooling) — a decision reaffirmed in [ADR-004](ADR-004-id-counters-and-nplus1-fix.md) §Consequences ("Fixed per-operation costs remain untouched... Option B's concern, explicitly not adopted") and again in [ADR-005](ADR-005-indexed-read-path.md) §Consequences and §Related decisions ("Pending work: ... Option B's fixed-cost-per-operation concerns, still not addressed"). That prior decision was about **throughput/cost**, not correctness — the failure reported here is a correctness/reliability bug (a write collision), a different axis this ADR evaluates on its own merits rather than reopening the cost question ADR-004/005 already closed twice.

---

## Decision

### Problem A — Connection concurrency: Option A1 (formalize the working fix)

Adopt `busy_timeout=5000` in `db/connection.py::get_connection` plus the explicit `conn.commit()` immediately after `next_sequential_id()` in `server.py::_security_pattern`, exactly as already present (uncommitted) in the working tree, formalized with a regression test that opens two real connections and asserts the second does not fail while the first holds an open write transaction.

**Why, with evidence:** the report's root-cause chain (§2.1, §3.1–3.3) shows the specific collision the user hit is `_security_pattern`'s `next_sequential_id()` call leaving an uncommitted transaction open on the server's long-lived global connection (`server.py::conn`) while `impl_callable()` opens a **second**, independent connection via `get_connection(get_db_path())` — one of the 14 call sites in `tools/knowledge_management.py`/`tools/knowledge_consumption.py` — to write to `rules`/`rule_history`. Without `busy_timeout`, the second writer fails immediately (`SQLITE_BUSY`); the report's table in §4.1 confirms Option A1 is the only option, alongside B1/C1, that "ataca la causa específica reportada por el usuario," at the lowest effort (`<1 día`) and lowest risk ("Bajo") of the four.

Options B1 (single shared connection, no more per-call `get_connection()`) and C1 (connection pool) were **not** chosen: both reopen, for a correctness problem A1 already resolves, the exact cost/effort trade-off `archy-rendimiento.md` deliberately closed in favor of Option C twice already (ADR-004, ADR-005) — refactoring the same 14 call sites B1/C1 both require, at 2–5 days of effort and "riesgo... Medio" per the report's comparative table, for no correctness gain beyond what A1 already delivers. Option D1 (`busy_timeout` alone, no early commit) was rejected because the report's own analysis (§4.1, Opción D1 "Desventajas") notes it would only turn the immediate failure into a wait bounded by however long `impl_callable()` takes — not a guaranteed fix — whereas A1's early commit removes the collision at its source.

### Problem B — Parser robustness: Option A2, augmented with Option B2's diagnostic

Adopt Option A2 as the base: widen `_BLOCK_HEADER_RE`'s `{TECH}` segment from `[A-Z]+` to `[A-Z0-9]+` (keeping the segment **mandatory** — not optional, unlike the user's current broken regex), and replace the incomplete `_KNOWN_FIELD_NAMES` (6 rule-only fields) with the complete set of field labels from both `RULE_TEMPLATE` and `LESSON_TEMPLATE` (`tools/knowledge_templates.py`): `Scope`, `Categoría`, `Severidad`, `Aplica a`, `Tags`, `Fuente`, `Proyecto`, `Fecha`, `Severidad del impacto`, `Área afectada`, `Impacto`, `Causa raíz`, `Resolución`, `Originó regla`.

Bundled with it, at negligible added cost (report's own estimate: both options are independently `<1 día`): Option B2's diagnostic — if `parse()` is called on a non-empty file and `_BLOCK_HEADER_RE.finditer()` returns zero matches, emit an explicit warning naming the file and the expected header format, instead of silently returning `indexed: 0`.

**Why, with evidence:**

- The `_KNOWN_FIELD_NAMES` half of A2 is not optional — it is a **confirmed** bug (report §2.2, §3.3), independent of whatever caused the original indexing failure: any `LL-*` block parsed by `atomic_parse()` today has its `text` field corrupted (swallowing `Impacto`/`Causa raíz`/`Resolución`/`Originó regla` into what should be just `Qué pasó`), because the current field-boundary list only contains rule fields. This must ship regardless of which regex option is chosen.
- The regex half of A2 is the report's most-supported hypothesis for the original indexing failure: `id_generator.py::_extract_segment()` (§3.2, §3.5) derives `{TECH}` from the last hyphen-segment of a `scope_id` with **no** character-class restriction, while the parser's original regex required pure `[A-Z]+` — a scope whose segment includes digits (e.g. a custom `global-java17`) produces an ID the parser can never match, and `parse()` returns `([], [])` with no error, matching the reported symptom exactly.
- A2 does not require touching `id_generator.py` or scope creation (unlike C2), which the report flags as unconfirmed scope in this codebase (§4.2, Opción C2: "no se encontró un tool `create_scope` expuesto en `server.py`"); today's 19 scopes are static seed data in `db/schema.sql`, so C2 has no clear implementation surface to anchor to and was rejected on that basis.
- D2 (silently fall back to `legacy_parse()` on zero matches) was rejected: per the report's comparative table it "puede enmascarar errores reales de formato" — a genuinely malformed atomic file would be silently reinterpreted as legacy content instead of surfacing a clear header-format error, working against the project's own "Markdown is the single source of truth, tools must not paper over drift" posture (`CLAUDE.md`).
- B2 alone (§4.2) was rejected as the *sole* fix because it is purely diagnostic — it would have shortened the user's debugging session but does not, by itself, make a validly-authored file with a digit-bearing `{TECH}` segment index correctly. Folding it into A2 costs nothing extra and converts any *future* zero-match case (regardless of cause) from a silent, hours-long debugging session into an immediate, actionable warning — the report itself frames B2 as "complementaria a cualquier otra opción."

---

## Consequences

### Positive

- The specific collision the user hit (Global Rule update failing under more than one open connection) is eliminated at its source, not merely slowed down, per the report's §3.1–3.3 root-cause trace.
- The `LL-*` text-corruption bug in `_KNOWN_FIELD_NAMES` is fixed as a side effect of adopting A2, independent of whatever the original indexing root cause turns out to be.
- No refactor of the 14 `get_connection()` call sites, no new abstraction (pool/module) — consistent with the project's twice-made decision (ADR-004, ADR-005) not to invest in that surface for cost reasons; this ADR does not reopen that question.
- A future file that indexes to 0 blocks — for *any* reason, not just the digit-segment hypothesis — now surfaces an explicit warning instead of a silent `indexed: 0`, per B2's inclusion.
- Both changes are small, independently testable, and match the low-risk profile the report's own comparative tables assign to A1 and A2 ("Bajo" risk in both §4.1 and §4.2 tables).

### Negative / Trade-offs (accepted)

- **The 14-ephemeral-connections architecture remains untouched**, same as ADR-004 and ADR-005 left it. Cross-process contention (CLI running `python -m meridian ...` while the MCP server is up) is mitigated by `busy_timeout` but not eliminated — two processes writing at the exact same moment still serialize through a wait, not a queue. Per the report's §3.5 limitation, no connection-pool fix inside the server process can prevent this anyway (separate OS processes), so this is accepted as inherent to the current process model, not specific to choosing A1 over B1/C1.
- **The `{TECH}` ID segment contract is relaxed** from pure `[A-Z]+` to `[A-Z0-9]+`, without a corresponding guard at scope-creation time (Option C2, rejected for lack of an implementation surface — see Decision above). If a future scope-creation flow is added, it should decide explicitly whether to constrain `{TECH}` at that point; until then, the parser now accepts whatever `_extract_segment()` can already produce, closing the gap between generator and parser rather than tightening either.
- **B2's diagnostic does not fix anything by itself** — a file that legitimately produces 0 blocks in some other still-unknown scenario now surfaces a warning, but the underlying cause of *that* scenario (if it's not the digit-segment hypothesis) is not addressed by this ADR.
- **The original root cause of the user's indexing failure remains a documented hypothesis, not a confirmed fact** (report §3.5) — the user did not share the exact traceback or the specific `scope_id`/file involved. If A2 does not fully resolve a recurrence, the next debugging session should start from B2's new explicit warning rather than re-deriving the hypothesis from scratch.

---

## Alternatives considered

Covered in full, with effort/risk tables, in `reporte-tecnico-conexiones-concurrentes-y-parser-atomico-2026-09-22.md` §4.1 (B1, C1, D1) and §4.2 (B2, C2, D2). Not re-litigated here beyond the justification above. The one alternative not in the report itself: doing nothing and keeping the user's current working-tree fix as-is — rejected outright, since it does not compile (§3.2) and would break `import meridian.parsers.atomic_parser` for every consumer, including the MCP server's own startup.

---

## Related decisions

- [ADR-004: ID Counters and N+1 Fix](ADR-004-id-counters-and-nplus1-fix.md) — first decision to explicitly defer the 14-ephemeral-connections concern (Option B) in favor of Option C.
- [ADR-005: Indexed Read Path](ADR-005-indexed-read-path.md) — reaffirms the same deferral; lists it as "Pending work." This ADR deliberately does not pick that work back up, addressing only the correctness collision, not the underlying cost.
- `reporte-tecnico-conexiones-concurrentes-y-parser-atomico-2026-09-22.md` — full evidence base, options, and comparative tables for both decisions made here.
- **Pending work:** the connection-pooling/shared-connection question (Options B1/C1) remains open, same as it has since ADR-004; should it ever be revisited, it should be justified on throughput grounds (as originally scoped in `archy-rendimiento.md`) rather than correctness, since correctness is what this ADR resolves. Confirming or ruling out the digit-segment hypothesis for Problem B (e.g. via a synthetic scope + indexing test, per report §6.3) is also open.
