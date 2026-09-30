## Why

A user reported that approving two UPDATE proposals against the same
`.md` file (`java.md`) corrupted it: the first approval (`prop-0013`,
target `RN-086`) grew its block by 969 bytes, shifting every later block
in the file by 969 bytes on disk — but `_approve_update_proposal` only
updates the *edited row's own* `file_offset`/`byte_length`, never the
other rows sharing that file. The second approval (`prop-0014`, target
`RN-092`) then spliced its new text in at `RN-092`'s now-stale cached
offset, which pointed 969 bytes too early — truncating `RN-086`'s tail
and leaving ~970 bytes of `RN-092`'s old text appended after its new
text. Verified against the code: this is deterministic, not a
concurrency issue — it reproduces with the two approvals run strictly
sequentially, as long as the first changes block length and the second
targets a block later in the same file.

`rules.text`/`lessons.what_happened` (what `query_rules`/`get_rule_context`
actually read, per ADR-005) were never corrupted — only the `.md` file and
the write-path `file_offset`/`byte_length` metadata. But every later
write to an affected file (another UPDATE approval, or `promote_rule`'s
`_mark_deprecated_in_md`, which has the identical bug) corrupts the file
further, compounding the damage.

**A second, more fundamental bug found while writing the regression test
for the above:** `_splice_atomic_block` replaces the *old* block's full
span (correctly including the separator before the next header) with
`_build_rule_atomic_block`'s output, which has no trailing newline of its
own. This glues the next header directly onto the new block's last line —
on a *single* UPDATE approval, independent of any second write or stale
offset. This matches the report's first symptom more precisely than the
offset-drift theory alone ("RN-086 ... sigue directamente ## RN-092" —
not just truncated, glued with zero separation). No existing test
exercised the UPDATE path against a file with content after the target
block, which is why this had never been caught.

## What Changes

- Add `shift_offsets_after(conn, file_path, edited_offset, delta)` to
  `utils/read_index.py`: after a block's byte length changes by `delta`
  at `edited_offset`, shift `file_offset` by `delta` for every `rules`/
  `lessons` row in the same `file_path` positioned after it
  (`file_offset > edited_offset`) — in the same DB transaction as the
  file write and the edited row's own offset update.
- Call it from `_approve_update_proposal` (`knowledge_management.py`)
  right after `_splice_atomic_block`, with `delta = new_length -
  old_length`.
- Call it from `_mark_deprecated_in_md`, with `delta = len(new_block_bytes)
  - byte_length` (deprecation marking always grows the block by one line).
  Also fixes `promote_rule` never persisting the deprecated row's own new
  `byte_length` (found in the same pass — same bug class, same call site).
- `_splice_atomic_block`: always ensure the spliced-in block ends with
  exactly one `\n` before whatever follows, fixing the header-gluing bug
  above.
- Regression tests: a unit test for `shift_offsets_after` in isolation,
  and integration tests reproducing the exact reported scenario (two
  sequential UPDATE approvals on the same file, first one growing its
  block — plus a downstream unrelated rule, to prove the shift isn't
  limited to the immediately-next block) and `promote_rule`'s equivalent —
  asserting later blocks land at the *correct* position and no block's
  text is corrupted or glued to its neighbor.
- Update `CLAUDE.md`'s ADR-005 paragraph, which currently documents this
  as a "known weakness (re-index required)" — no longer accurate once
  offsets are kept in sync at write time.

Not in scope: a repair/resync tool for *already*-corrupted data (the
reporting user's own incident). That's a one-off operational task against
their specific `KNOWLEDGE_BASE_PATH`, not a product change — offered to
them separately, outside this change.

## Capabilities

### New Capabilities
- `atomic-block-offset-integrity`: the contract that every `rules`/
  `lessons` row's cached `file_offset` stays accurate relative to its
  block's real position on disk, across writes that change another
  block's length in the same file.

### Modified Capabilities
(none — no existing `openspec/specs/` entry for offset/write-path
behavior yet; this change adds the first one)

## Impact

- `src/meridian/utils/read_index.py` — new `shift_offsets_after` helper.
- `src/meridian/tools/knowledge_management.py` — `_approve_update_proposal`,
  `_mark_deprecated_in_md`, `promote_rule` (byte_length persistence), and
  `_splice_atomic_block` (trailing-newline fix).
- `tests/unit/test_read_index.py`, `tests/integration/test_proposals_flow.py`
  — new regression tests.
- `CLAUDE.md` — correct the ADR-005 paragraph's "known weakness" note.
- No schema/migration changes. No effect on `rules.text`/
  `lessons.what_happened` (already correct per the report) or on the
  read path (ADR-005 unaffected — reads never touched offsets).
