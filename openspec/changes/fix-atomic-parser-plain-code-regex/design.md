## Context

This is a single-regex bug fix in `atomic_parser.py`, contained to one
module with no new dependency, no data-model change, and no cross-service
impact — most design sections below are intentionally short. It's included
because the regex has one real decision point (how to make the `{TECH}`
segment optional) that's easy to get subtly wrong, as the user's own first
attempt at a fix did.

## Goals / Non-Goals

**Goals:**
- Recognize `## RN-NNN` / `## LL-NNN` (no `{TECH}`) as valid block headers,
  with no change to how `## RN-{TECH}-NNN` / `## LL-{TECH}-NNN` headers are
  recognized or how `code` is extracted (unchanged: the full header line,
  not a regex capture group).

**Non-Goals:**
- Making `id_generator.py` count plain-code IDs toward `id_counters`
  reconciliation (`_max_code_suffix_by_segment` still requires 3
  hyphen-separated parts). Tracked as a known follow-up in the proposal,
  not fixed here.
- Changing the atomic block *field* format (Scope/Categoría/etc.) — only
  the header-line recognition regex changes.
- Retroactively re-indexing already-indexed files; existing indexed rows
  are untouched, this only affects blocks parsed from now on.

## Decisions

**Make `(?:[A-Z0-9]+-)?` (the segment plus its trailing hyphen) optional as
one unit, not just widen the character class or make only the hyphen
optional.**

Current regex: `^## (RN|LL)-[A-Z0-9]+-\d+` — `{TECH}` and its hyphen are
both mandatory.

Rejected alternative (the user's first draft, `(?:[A-Z0-9}+-)?`): had a
typo (`}` instead of `]`) that left the character class unterminated —
`re.compile` raises `re.error: bad character range +-) at position 23`.
Beyond the typo, the *shape* of the fix (wrap `[A-Z0-9]+-` as one optional
non-capturing group) is correct, which is why the fix here is the same
shape with the character class closed properly.

Rejected alternative: making `[A-Z0-9]+` optional but leaving the `-`
literal outside the group (e.g. `(?:[A-Z0-9]+)?-\d+`) — this still
requires a literal `-` between the prefix and the digits regardless of
whether `{TECH}` is present, which would make `## RN-086` require
`## RN--086` to match. The hyphen has to be inside the optional group,
not outside it.

Final regex: `^## (RN|LL)-(?:[A-Z0-9]+-)?\d+`

## Risks / Trade-offs

[A plain code and a `{TECH}` code could theoretically collide if a KB ever
mixed both styles for the same numeric suffix, e.g. `RN-042` and
`RN-JAVA-042` both existing] → not a new risk introduced by this change:
`code` has always been the raw header text, and uniqueness of `code` was
never enforced by the parser (it's enforced, if at all, at the
`rules`/`lessons` table level on write). Out of scope for this fix.

[Silent data loss pattern repeats if a third header variant shows up
later] → the per-file "no atomic blocks found" warning still only fires
when zero blocks match in the whole file, not per-block; this fix doesn't
add per-block validation. Acceptable for this change since it directly
fixes the reported case; a broader "warn on lines that look like a header
but don't fully match" check is future work, not blocking this fix.

## Migration Plan

Pure code change, no data migration. Deploy = merge + restart the MCP
server process (editable install via `pip install -e .`, per
`scripts/install.sh`). Rollback = revert the regex line; no persisted
state depends on the new behavior.
