## 1. Embedding status feedback

- [x] 1.1 `_embed_and_upsert_after_approve`: return `True` on success,
      `False` on any caught exception (instead of `None`).
- [x] 1.2 `_approve_create_proposal`: capture the return value and add
      `"embedded": <bool>` to the returned dict, for both rule and
      lesson proposal types.
- [x] 1.3 `_approve_update_proposal`: same, for both rules and lessons
      target tables.

## 2. Separator preservation

- [x] 2.1 `_splice_atomic_block`: compute
      `len(old_block_text) - len(old_block_text.rstrip("\n"))` and use
      `max(that, 1)` trailing newlines on the new block instead of the
      current unconditional single `\n`.

## 3. Regression tests

- [x] 3.1 Integration test: approve a CREATE proposal, assert
      `result["embedded"] is True` and the row's `embedding_id` is set
      (happy path, real embedder).
- [x] 3.2 Integration test: approve a CREATE proposal with the vector
      store monkeypatched to fail, assert `result["embedded"] is False`
      and the approval itself still succeeds (reuses the existing
      failure-survival test's setup).
- [x] 3.3 Same two, for the UPDATE path.
- [x] 3.4 Integration test: seed a file where a block is followed by a
      blank line (two newlines) before the next header; approve an
      UPDATE on it; assert the blank line survives (two newlines) and
      the file still parses into the same block count with correct
      content. Repeat for a block with only a single newline before the
      next header (no blank line) — assert that stays single too.

## 4. Verification

- [x] 4.1 Run `uv run pytest` — full suite passes.
- [x] 4.2 Run `uv run ruff check src tests` — no new findings.
