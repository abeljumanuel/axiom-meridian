## 1. Embed-after-approve

- [x] 1.1 Add `_embed_and_upsert_after_approve()` to
      `knowledge_management.py`: re-fetch the row by code, embed its
      text, upsert into the vector store, set `embedding_id`, commit its
      own mini-transaction — all wrapped so any exception is logged and
      swallowed, never raised to the caller.
- [x] 1.2 Call it from `_approve_create_proposal`, after its own
      `conn.commit()`, for both `rule` and `lesson` proposal types.
- [x] 1.3 Call it from `_approve_update_proposal`, after its own
      `conn.commit()`, for both `rules` and `lessons` target tables.

## 2. Pending-embeddings visibility

- [x] 2.1 `query_rules`: when `query_text` triggers the semantic path,
      also check for active rows in the resolved scopes with
      `embedding_id IS NULL` and log a warning naming the count if any.
- [x] 2.2 Same for `query_lessons`.

## 3. Regression tests

- [x] 3.1 Integration test: approve a `type="rule"` CREATE proposal
      (with a fake/stub embedder + vector store, or the real lazy one if
      fast enough in CI) and assert the resulting row's `embedding_id`
      is set and `vector_store.search_rules` finds it.
- [x] 3.2 Integration test: approve a `type="update"` proposal changing
      text/tags on an already-embedded rule, and assert the vector
      store's entry reflects the new text/tags, not the old ones.
- [x] 3.3 Unit test: `_embed_and_upsert_after_approve` swallows an
      exception from the embed/upsert step and leaves `embedding_id`
      `NULL` rather than propagating.
- [x] 3.4 Unit/integration test: `query_rules`/`query_lessons` with
      `query_text` logs a warning when active un-embedded rows exist in
      scope (capture via `caplog` or equivalent).

## 4. Verification

- [x] 4.1 Run `uv run pytest` — full suite passes.
- [x] 4.2 Run `uv run ruff check src tests` — no new findings.
