## Context

Confirmed against the actual code (not just the user's report): `_approve_update_proposal` splices a new block into the file via `_splice_atomic_block`, then updates only the edited row's own `file_offset`/`byte_length` (`_update_rule_row`/`_update_lesson_row`). No other row sharing that `file_path` is touched. `_mark_deprecated_in_md` (called from `promote_rule`) has the identical gap — it also changes a block's byte length in place (inserting a `**Status:** deprecated` line) without shifting anything else.

This is deterministic, not a concurrency bug: it reproduces with two UPDATE approvals run strictly one after another, as long as the first changes its block's byte length and the second targets a block later in the same file. Verified with an integration-style repro (two sequential `approve_proposal` calls) during incident triage.

Also confirmed: `index_rules_from_markdown(mode="atomic")` cannot be used to *repair* this after the fact — `_index_rules_atomic`'s upsert skips the DB write entirely (`if existing_text == clean_text: continue`) whenever a block's text already matches what's stored, which is true for every unaffected row. It refreshes `indexed_files` (clearing `STALE_INDEX`) but leaves every already-correct row's stale offset untouched, masking the problem instead of fixing it.

A second, independent bug surfaced while writing the first regression test for this change (a realistic multi-block file, seeded with `atomic_parse`'s own offsets — no prior test did either): `_build_rule_atomic_block` returns a block with no trailing newline, and `_splice_atomic_block` replaces the *old* block's full span — which, by the parser's own convention, extends up to and including the separator before the next header — with that newline-less text. The next header ends up glued to the new block's last line, on a single UPDATE approval, with no second write or stale offset required. Reproduced directly: one `approve_proposal` UPDATE call against a two-block file was enough.

## Goals / Non-Goals

**Goals:**
- After any write that changes one block's byte length in a `.md` file with other indexed blocks, every other `rules`/`lessons` row for that `file_path` positioned after the edited block keeps an accurate `file_offset`, in the same transaction as the write.
- Cover both known call sites: `_approve_update_proposal` and `_mark_deprecated_in_md`.

**Non-Goals:**
- Repairing already-corrupted data (handled separately, operationally, via `scripts/repair_offset_corruption.py` against the reporting user's own `KNOWLEDGE_BASE_PATH` — not a product change).
- Changing `index_rules_from_markdown`'s upsert-skip behavior. It's a legitimate optimization for its own purpose (avoid no-op history rows on reindex); the point of this change is that offset integrity no longer depends on it.
- A general-purpose "whole file changed externally" reconciliation tool. This change only keeps offsets in sync for edits Meridian itself makes through `write_block`.

## Decisions

**A single helper, `shift_offsets_after(conn, file_path, edited_offset, delta)` in `utils/read_index.py`, called once per write that changes a block's length, rather than a full re-parse+resync.**

Rejected alternative: re-run `atomic_parse()` and resync every row's offset after every write (the same approach the repair script uses operationally). Rejected for the *product* path because it's O(blocks in file) work, with a full file read and UTF-8 decode, on every single UPDATE approval or deprecation — for a fix whose correct behavior is a single `UPDATE ... SET file_offset = file_offset + ? WHERE file_path = ? AND file_offset > ?` per table. The resync approach is right for one-off repair of already-bad data (where you can't trust any stored offset), wrong as the steady-state mechanism (where only one offset per write is ever wrong, and its correction is a closed-form shift).

**Boundary condition: `file_offset > edited_offset`, not `>=`.** The edited row's own `file_offset` is unchanged by the edit (the block still starts at the same place, it just got longer or shorter) — so it's never `> edited_offset`, and the shift naturally excludes it without needing to filter by id. Verified: since blocks don't overlap and the edited row's own offset update happens independently (`_update_rule_row`/`_update_lesson_row` keeps passing `old_offset`, not a new one), there's no row that could sit exactly at `edited_offset` other than the one just edited.

**Shift both `rules` and `lessons` tables, filtered by `file_path`,** rather than restricting to whichever table the edited row belongs to. A `.md` file is conventionally single-purpose (rules or lessons, not mixed), but nothing enforces that at the schema level, and shifting the empty/irrelevant table is a no-op `UPDATE` matching zero rows — cheaper than adding a branch to get it "more precisely" wrong if that assumption ever breaks.

**Fix the missing trailing newline in `_splice_atomic_block` (the splice site), not in `_build_rule_atomic_block`/`_build_lesson_atomic_block` (the block builders).**

Rejected alternative: make the builder functions themselves always return a trailing `\n`. Rejected because those functions are also used by `_approve_create_proposal` → `_append_atomic_block`, which already adds its own explicit `\n\n` separator regardless of the block text's own ending — correct there either way, but it mixes two different concerns (the builder's job is rendering fields; the separator between blocks is the splice/append site's job) and would leave the actual bug — `_splice_atomic_block` assuming its input already ends correctly — unfixed in principle, just accidentally papered over for this one caller. Guaranteeing the invariant at the site that has the requirement (`_splice_atomic_block`: "whatever I insert must properly separate from what follows") is more locally correct and doesn't depend on every block-producing function elsewhere remembering to do it too.

## Risks / Trade-offs

[A future write path that changes a block's length without going through `_approve_update_proposal` or `_mark_deprecated_in_md` reintroduces the same bug] → not mitigated by this change beyond covering the two call sites that exist today. `write_block` itself (the single place bytes are written) doesn't call `shift_offsets_after` automatically, because it doesn't know the *old* length of whatever block changed — only the caller does. Documented in `write_block`'s docstring as a requirement for any future caller that edits an existing block in place (append-only writes, like `_append_atomic_block`, don't need it — nothing after an append shifts).

## Migration Plan

Pure code change, no schema/data migration. Deploy = merge + restart the MCP server process. No effect on already-written data — this only changes what happens on the *next* write that changes a block's length. The reporting user's already-corrupted `java.md` is fixed separately via `scripts/repair_offset_corruption.py`, independent of when this lands.
