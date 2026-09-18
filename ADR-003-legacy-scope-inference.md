# ADR-003: Word-Boundary Matching for Legacy Scope Inference

**Status:** Accepted
**Date:** 2026-09-17
**Product:** Axiom Meridian
**Author:** Axiom JUMA
**Deciders:** abeljuanmanuel
**Supersedes:** Naive substring keyword matching in `convert_to_atomic_format()` (never formally decided — introduced ad hoc, documented as defective in `reporte-indexacion.md`)

---

## Context

`reporte-indexacion.md` (2026-06-12) documented a critical defect in `migrate rules`: while migrating 30 Clean Code rules, every rule was assigned to scope `global-go` instead of `global`. Root cause, in `src/meridian/tools/knowledge_management.py` (then lines 987–1004, function `convert_to_atomic_format()`):

```python
elif "go" in raw_lower:  # substring match, not word match
    inferred_scope = "global-go"
```

`raw_lower` is the full lowercased text of the legacy rule block. Because the check is substring containment rather than word matching, any Spanish word containing the letters "go" triggered a false positive: `código`, `cargo`, `embargo`. The same defect class also affected `"java" in raw_lower`, which matches inside `"javascript"` — not called out in the original report but found while implementing this fix.

The report proposed four options (word-boundary fix, validation-with-warning, format auto-detection + `import` command, remove inference entirely) and explicitly deferred the decision: *"Siguiente paso: Seleccionar una opción y proceder a redactar el ADR correspondiente."* This ADR makes that decision, scoped narrowly to eliminating the false-positive bug.

### Explicitly out of scope for this ADR

`reporte-indexacion.md` bundled three separate problems under "scope inference": (1) the false-positive substring bug, (2) legacy vs. atomic format incompatibility (`migrate rules` silently returns 0 blocks on atomic-format input), and (3) the explicit `--scope` CLI parameter being silently overridden by inference with no warning. This ADR resolves only (1). Problems (2) and (3) remain open — see **Related decisions**.

---

## Decision

Adopt **Option A — Word-Boundary Matching** from `reporte-indexacion.md` §4.1, implemented as an ordered list of regex patterns rather than an `if/elif` chain of substring checks.

### Implementation

`src/meridian/tools/knowledge_management.py`:

```python
_SCOPE_KEYWORD_PATTERNS: list[tuple[str, str]] = [
    (r"\bquarkus\b", "global-quarkus"),
    (r"\bjava\b", "global-java"),
    (r"\bnestjs\b", "global-nestjs"),
    (r"\bspring-boot\b", "global-spring-boot"),
    (r"\bgo-fiber\b", "global-go-fiber"),
    (r"\bgo-gin\b", "global-go-gin"),
    (r"\bgo\b", "global-go"),
    (r"\bflutter\b", "global-flutter"),
]


def _infer_scope_from_text(raw_lower: str, default_scope_id: str) -> tuple[str, bool]:
    for pattern, scope in _SCOPE_KEYWORD_PATTERNS:
        if re.search(pattern, raw_lower):
            return scope, False
    return default_scope_id, True
```

`convert_to_atomic_format()` now calls this helper instead of inlining the checks. Order is preserved from the original code: compound keywords (`go-fiber`, `go-gin`) are checked before the generic `go`, so specific scopes still win over the generic one.

`\b` is a zero-width word-boundary assertion — it matches between a word character (`[A-Za-z0-9_]`) and a non-word character (or string edge). `código` has no `\b` immediately before `go` (the preceding character `ó`/`i` is itself a word character in the substring sense at that position — more precisely, `go` is not flanked by non-word boundaries there), so `\bgo\b` does not match it, `cargo`, or `embargo`. `javascript` does not match `\bjava\b` for the same reason.

### Tests

`tests/unit/test_scope_inference.py` (new, 9 cases) — regression coverage for every false positive named in the report (`código`, `cargo`, `embargo`, `javascript`) plus positive matches (`go`, `java`, `go-fiber`, `go-gin` as standalone words) and the no-keyword fallback path.

---

## Consequences

### Positive

- Eliminates the reported false positives immediately, with no CLI, schema, or MCP interface changes — non-breaking, per the report's own risk assessment for this option.
- Also fixes the unreported `java`/`javascript` case, since the same pattern-based approach covers it for free.
- Effort and risk matched the report's estimate (~30 min, low risk) — appropriate given this was the narrowest fix among the four, chosen to unblock migration quickly rather than redesign the pipeline.
- Testable in isolation: `_infer_scope_from_text()` is a pure function, no DB or filesystem required.

### Negative / Trade-offs (accepted, not resolved)

- **Silent override of `--scope` persists.** As before, if any keyword matches, the caller's explicit `default_scope_id` is discarded without warning. This is exactly the problem Option B (validation with warning) addresses; it was not adopted here because it requires new `pending_proposals` metadata and CLI-level UX work beyond a bug fix. Left as future work.
- **Legacy/atomic format incompatibility persists.** `migrate rules` still only understands the legacy `### ` format; feeding it an atomic-format file still silently returns zero blocks. This is Option C's concern and is a larger, separate effort (~1 day per the report).
- **Keyword vocabulary stays hardcoded and finite.** Adding a new framework still requires a code change to `_SCOPE_KEYWORD_PATTERNS`, in tension with the dynamic-attribute philosophy established in [ADR-002](ADR-002-dynamic-context-attributes.md) (scopes/rules gain new context dimensions via `INSERT`, not schema/code changes). This is a one-time legacy-migration utility, not the query-time filtering path ADR-002 governs, so the inconsistency is tolerated here — but if this vocabulary keeps growing, it should move to a data-driven source (e.g. read known `framework` values from `scope_attributes`) rather than staying hardcoded.

---

## Alternatives considered

**Option B — Validation with warning.** Rejected for now, not permanently. Improves transparency (records both inferred and explicit scope, flags conflicts) without breaking compatibility, but requires `pending_proposals` schema/metadata changes and CLI UX beyond the scope of a bug fix. Revisit if silent `--scope` overrides cause real migration errors in practice.

**Option C — Auto-detect format + `import` command.** Rejected for now. Solves a materially different, larger problem (parser selection) and was estimated at ~1 day with medium risk (changes the migration CLI surface). Doing it alongside a 30-minute regex fix would have mixed two unrelated architectural changes into one commit.

**Option D — Remove inference, require `--scope`.** Rejected. Deterministic and simple, but a breaking change: existing scripts and workflows that rely on automatic inference would fail outright. The false-positive bug this ADR fixes was the actual reported defect — removing a feature is not proportionate to fixing a bug in it.

---

## Related decisions

- `reporte-indexacion.md` — original defect report; source of the four options evaluated here.
- [ADR-002: Dynamic Context Attributes](ADR-002-dynamic-context-attributes.md) — the `framework` attribute vocabulary (`quarkus`, `java`, `nestjs`, `spring-boot`, `go-fiber`, `go-gin`, `go`, `flutter`) mirrors `_SCOPE_KEYWORD_PATTERNS` exactly; the tension between hardcoded migration-time keywords and dynamic query-time attributes is noted above and should inform a future refactor if the keyword list grows.
- **Pending ADR** — legacy/atomic format auto-detection (Option C above).
- **Pending ADR** — explicit-scope vs. inferred-scope conflict handling (Option B above).
