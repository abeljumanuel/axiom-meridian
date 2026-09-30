## Context

Confirmed against the code: `_generate_embeddings_for_table` (backing
the `generate_embeddings` tool) already has the correct embed-and-upsert
logic, batched. `approve_proposal`'s two paths (create, update) never
call it or anything equivalent — a newly-created row's `embedding_id`
starts `NULL` and stays that way until someone runs
`generate_embeddings`; an updated row's `embedding_id` gets reset to
`NULL` by `_update_rule_row`/`_update_lesson_row`, but the *old* ChromaDB
document under that id is never touched, so it keeps being served to
semantic queries — `NULL` in SQL means "needs re-embedding," not "not in
Chroma," and the two facts only get reconciled when `generate_embeddings`
next runs and re-upserts by id (which does correctly overwrite the old
document, since `collection.upsert` replaces by id — verified in
`vector_store.upsert_rule`).

## Goals / Non-Goals

**Goals:**
- Approving a rule/lesson (create or update) makes it correctly findable
  via semantic search (`query_text`) without requiring a manual
  `generate_embeddings` call afterward, in the common case.
- An embedding failure never affects whether the approval itself
  succeeds.

**Non-Goals:**
- A message queue / background worker for embeddings. The codebase has
  no async task infrastructure today; introducing one for this is a much
  bigger change than the incident calls for. Best-effort-after-commit,
  falling back to `generate_embeddings` as the safety net, is
  proportionate.
- Changing `query_rules`/`query_lessons`'s return shape to merge SQL and
  semantic results, or to carry a warning field. ADR-001 fixed this
  contract (plain serialized array) deliberately; the incident's own
  second ask ("combinar... o avisar") explicitly offered logging as the
  lighter alternative, which is what's implemented here.
- Retroactively backfilling embeddings for rows already `NULL` before
  this change ships. `generate_embeddings` already does exactly that;
  running it once after deploying this is an operational step, not part
  of the change.

## Decisions

**Embed after the approval's own `conn.commit()`, not inside its
transaction.**

Rejected alternative: embed-then-upsert inside the same transaction as
the row/history writes. Rejected because `embedder.generate_embedding`
lazy-loads a sentence-transformers model on first use (real, possibly
multi-second latency, plus a dependency on `torch`/model files being
available) and `vector_store.upsert_rule` talks to ChromaDB (another
I/O dependency) — holding a SQLite write transaction open across either
is exactly the failure mode `fix-connection-lock`/ADR-006 already
diagnosed and fixed once (a long-held transaction blocking a second
writer). Committing the approval first, then best-effort embedding in
its own mini follow-up transaction (row write + its own commit), means
an embedding failure degrades to "needs a `generate_embeddings` pass
later," never to "the approval didn't go through" or "the database was
locked for the duration of a model load."

**Per-row embed (`embedder.generate_embedding`, singular) at approval
time, not a batched call.**

Rejected alternative: queue the code and batch-embed periodically (e.g.
piggyback on the next `generate_embeddings` call, or a batch of N).
Rejected as over-engineering for this codebase's actual write volume
(proposals are approved one at a time, interactively, by a human) — the
existing batch path (`_generate_embeddings_for_table`) stays exactly as
it is today for its own use case (bulk/backfill), and this change adds
a separate, simple single-row path for the interactive approval case.
Re-fetching the row by `code` after commit (rather than threading the
in-memory `metadata`/`proposed_text` through) guarantees the embedded
text/metadata exactly matches what's actually persisted, at the cost of
one extra `SELECT` — negligible next to the embed+upsert itself.

**Warn (log), don't merge, on the `query_rules`/`query_lessons` side.**

Already covered in the proposal's "What Changes" — restated here because
it's a real design choice, not an oversight: a SQL+semantic merge
changes ranking semantics (how do un-embedded SQL matches interleave
with semantically-ranked ones?) in a way that deserves its own design
pass if ever wanted, not a same-incident bolt-on.

## Risks / Trade-offs

[A burst of approvals right after a cold server start each pay the
lazy model-load cost independently if they race before the singleton
loads] → not a new risk: `_Embedder`'s `_load()` is already guarded by a
lock and a "already loaded" check (`if self._model is not None: return
self._model`), so only the first concurrent caller actually loads the
model; the rest block briefly on the lock and then proceed. No change
needed here.

[ChromaDB being down/misconfigured means every approval now logs an
embedding-failure exception] → acceptable: this is the intended
degrade-gracefully path, and it's exactly the situation
`generate_embeddings`'s own error handling already handles the same way
(count errors, keep going). An operator seeing repeated embed-failure
log lines has a clear, actionable signal — better than the current
"looks fine, semantic search is just quietly wrong" state.

## Migration Plan

Pure code change, no schema/migration. Deploy = merge + restart the MCP
server. Existing rows with `embedding_id IS NULL` from before this
change are unaffected until someone runs `generate_embeddings` once
(unchanged tool, still the correct backfill path) — this change only
prevents the gap from growing on new approvals going forward.
