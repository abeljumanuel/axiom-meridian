## 1. Offset-shift helper

- [x] 1.1 Add `shift_offsets_after(conn, file_path, edited_offset, delta)` to
      `src/meridian/utils/read_index.py`: a no-op when `delta == 0`,
      otherwise `UPDATE {table} SET file_offset = file_offset + ? WHERE
      file_path = ? AND file_offset > ?` for both `rules` and `lessons`.
- [x] 1.2 Document the requirement on `write_block`'s docstring: any future
      caller that rewrites an *existing* block in place (not an append)
      must call `shift_offsets_after` itself with the old/new length delta.

## 2. Wire into both call sites

- [x] 2.1 `_approve_update_proposal` (`knowledge_management.py`): after
      `_splice_atomic_block` returns `new_length`, call
      `shift_offsets_after(conn, dest_path, old_offset, new_length -
      old_length)` before committing.
- [x] 2.2 `_mark_deprecated_in_md`: after computing `new_block_bytes`,
      call `shift_offsets_after(conn, path, file_offset, len(new_block_bytes)
      - byte_length)` before/alongside its `write_block` call, in the
      same (caller's) transaction.
- [x] 2.3 (found while implementing 2.2, same bug class) `promote_rule`
      never updated the deprecated rule's *own* `byte_length` after
      `_mark_deprecated_in_md` grows its block — a later UPDATE approval
      targeting that same (now-deprecated) rule would use the stale
      length as `old_length` and reproduce this corruption on itself.
      `_mark_deprecated_in_md` now returns the new byte_length;
      `promote_rule` persists it to the row.

## 3. Trailing-newline fix (found while writing task 4's test)

- [x] 3.1 `_splice_atomic_block`: append `\n` to the encoded new block text
      if it doesn't already end with one, before splicing — otherwise a
      single UPDATE approval glues the next header onto the new block's
      last line, independent of any offset-shift issue. Document why on
      the function's docstring.

## 4. Regression tests

- [x] 4.1 Unit test in `tests/unit/test_read_index.py`: `shift_offsets_after`
      shifts only rows in the same file positioned after the edit, leaves
      rows in other files and rows positioned before/at the edit untouched,
      for both positive and negative `delta`, and is a no-op for `delta=0`.
- [x] 4.2 Integration test in `tests/integration/test_proposals_flow.py`
      reproducing the reported incident: two sequential `approve_proposal`
      UPDATE calls against blocks in the same file (plus a third,
      downstream, unrelated rule), the first growing its block — assert
      no block is corrupted or glued to its neighbor, and every
      downstream row's `file_offset`/`byte_length` matches its real
      position (re-parsed via `atomic_parser.parse`) after both approvals.
      Seeds offsets via `atomic_parse` on the constructed file, matching
      how real initial indexing computes them.
- [x] 4.3 Integration test for `promote_rule`/`_mark_deprecated_in_md`:
      deprecate a rule in a file with a later rule, assert the later
      rule's offset shifted and still resolves to its real block, and its
      content has no deprecation marker bleeding into it.

## 5. Documentation

- [x] 5.1 Update `CLAUDE.md`'s ADR-005 paragraph: replace "Any code that
      rewrites a block in the middle of a file changes its length and
      silently invalidates the *write-path* offsets of all later blocks
      in that file (known weakness — re-index required)" with a
      description of the new behavior (offsets shift automatically via
      `shift_offsets_after`).

## 6. Verification

- [x] 6.1 Run `uv run pytest` — full suite passes.
- [x] 6.2 Run `uv run ruff check src tests` — no new findings.
