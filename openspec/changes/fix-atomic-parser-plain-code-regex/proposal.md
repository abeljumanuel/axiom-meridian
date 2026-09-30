## Why

`atomic_parser.py`'s block-header regex requires a `{TECH}` segment
(`RN-{TECH}-NNN` / `LL-{TECH}-NNN`), but the legacy plain-code format
(`RN-NNN` / `LL-NNN`, no `{TECH}`) is also valid content — it predates the
`{TECH}` convention and is what a migrated knowledge base uses for 95 of
105 blocks. The parser silently drops every plain-code block: no per-block
warning fires (the "no atomic blocks found" warning only triggers when a
whole file yields zero matches), so `index_rules_from_markdown` /
`index_lessons_from_markdown` index fewer rules/lessons than exist in the
file with no visible error. Reported by a user via
`create_pending_proposal`/indexing on 2026-09-30.

## What Changes

- Make the `{TECH}-` segment of the block-header regex optional (as a
  whole unit, not just its trailing character), so `## RN-NNN` and
  `## LL-NNN` are recognized as valid block headers alongside the existing
  `## RN-{TECH}-NNN` / `## LL-{TECH}-NNN` form.
- Update the "no atomic blocks found" warning text to reflect that the
  `{TECH}` segment is optional.
- Add a regression test asserting both the `{TECH}` and plain-code forms
  parse correctly, alongside the existing `{TECH}`-segment regression test
  (ADR-006, digits-in-TECH case).

Not in scope: `id_generator.py`'s `_max_code_suffix_by_segment` still
ignores codes whose `split("-")` isn't exactly 3 parts, so plain-code
blocks won't contribute to `id_counters` reconciliation even after this
fix. Tracked as known follow-up, not required for indexing to work
correctly.

## Capabilities

### New Capabilities
- `atomic-block-parsing`: the contract for what counts as a valid
  `## RN-*`/`## LL-*` block header in a knowledge-base Markdown file, and
  what `parse()` guarantees about indexing every block that matches it.

### Modified Capabilities
(none — no existing `openspec/specs/` entries yet; this is the first spec
for this codebase)

## Impact

- `src/meridian/parsers/atomic_parser.py` — `_BLOCK_HEADER_RE` and the
  "no atomic blocks found" warning message.
- `src/meridian/server.py` — the `mode` parameter's `Field(description=...)`
  on `index_rules_from_markdown` / `index_lessons_from_markdown` said only
  "parse canonical `## RN-XXX-NNN` blocks", which is what an MCP client
  reads from `tools/list` to decide how to call the tool (this server's
  equivalent of an OpenAPI operation description) — updated to state the
  `{TECH}` segment is optional. `get_rule_template`/`get_lesson_template`
  (lines 868/890) were left unchanged: they describe the canonical
  write-side template for *new* content, which this change doesn't alter
  — `id_generator.py` still always produces `RN-{TECH}-NNN`.
- `tests/unit/test_atomic_parser.py` — new regression test.
- No schema/migration changes, no change to `id_generator.py`,
  `knowledge_management.py`, or any `.md` field-label convention.
- Fixes indexing for legacy-format content already present in migrated
  knowledge bases; no effect on content already using the `{TECH}` form.
