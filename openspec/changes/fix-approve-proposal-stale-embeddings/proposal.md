## Why

Reported (Hallazgo 5) after approving `RN-JAVA-004`/`RN-JAVA-005`
(new rules) and updating `RN-086`/`RN-092`: `query_rules(query_text=...)`
(semantic/ChromaDB search) never surfaced the two new rules, and served
stale tags for the two updated ones. Verified against the code:

- `_approve_create_proposal` inserts the new row with `embedding_id`
  left `NULL` (the column has no default in the insert) and never calls
  anything in `rag/vector_store.py` — the row simply doesn't exist in
  ChromaDB until someone runs `generate_embeddings` by hand. Semantic
  search (`vector_store.search_rules`) only ever returns ids that were
  explicitly upserted, so a never-embedded rule is invisible to it, with
  no error or warning.
- `_approve_update_proposal`/`_update_rule_row` set `embedding_id = NULL`
  on every update — but that only marks the SQL row as "needs
  re-embedding." It doesn't touch ChromaDB at all, so the *old* document
  and metadata (old tags, old text) keep sitting in the vector store
  under that same id, served to every semantic search until someone runs
  `generate_embeddings`, which re-upserts by id and only then overwrites
  the stale copy.

`generate_embeddings` already does the right thing — embed batches of
`embedding_id IS NULL` rows and upsert them — the gap is that nothing
calls it (or does the equivalent for one row) as part of approving a
proposal, so every approval leaves a visible staleness window until an
operator remembers to run it manually.

## What Changes

- New `_embed_and_upsert_after_approve()` in `knowledge_management.py`:
  re-fetches the just-approved row, embeds its text
  (`embedder.generate_embedding`), upserts it into ChromaDB
  (`vector_store.upsert_rule`/`upsert_lesson`), and sets `embedding_id`
  — called from both `_approve_create_proposal` and
  `_approve_update_proposal`, **after** their own transaction has
  already committed. A failure here (model load, ChromaDB unavailable,
  ...) is logged and leaves `embedding_id` `NULL` for a later
  `generate_embeddings` pass to catch — it must never roll back or
  otherwise affect an approval that already succeeded. Deliberately
  *not* run inside the approval's own transaction: embedding is a
  potentially slow, lazy-loaded-model operation (first call loads a
  sentence-transformers model), and holding a SQLite transaction open
  for that is exactly the kind of long-held-lock risk
  `fix-connection-lock` (ADR-006) already fixed once.
- `query_rules`/`query_lessons`: when a `query_text` search runs and
  there are active rows in scope with `embedding_id IS NULL` (embedding
  still pending — e.g. the above best-effort step failed, or rows
  predate this fix and haven't been backfilled), log a server-side
  warning naming the count, so an operator watching logs has a signal
  that semantic results may be incomplete, instead of it being silent
  end-to-end. Not changing the tool's return shape (ADR-001: `query_*`
  tools return a plain serialized array) — a SQL-merge or a
  result-embedded warning field would be a larger, riskier API-contract
  change than this incident calls for; logging closes the "en silencio"
  gap without touching what callers already parse.

## Capabilities

### New Capabilities
- `approve-proposal-embedding-sync`: the contract that approving a
  rule/lesson proposal (create or update) keeps its ChromaDB entry
  consistent with what was just approved, best-effort and without
  blocking the approval itself.

### Modified Capabilities
(none)

## Impact

- `src/meridian/tools/knowledge_management.py` —
  `_embed_and_upsert_after_approve` (new), called from
  `_approve_create_proposal` and `_approve_update_proposal`.
- `src/meridian/tools/knowledge_consumption.py` — `query_rules`,
  `query_lessons`: add the pending-embeddings log warning.
- No schema/migration changes. `generate_embeddings` itself is
  unchanged — still the correct tool for a full/backfill re-embed; this
  change just means normal approvals no longer *need* it to stay current
  in the common case.
- Runtime cost: one embed + one ChromaDB upsert added to the approval
  path, after commit (not inside the critical transaction). First call
  after server start pays the lazy model-load cost `generate_embeddings`
  already pays today on its first use — not new, just potentially
  triggered earlier (on the first approval instead of the first
  `generate_embeddings` call or semantic query).
