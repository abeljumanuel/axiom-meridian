## Why

Follow-up from the reporting team's log analysis (Hallazgo 1 of their
second-round verification): observed connection/first-call latency of
4.1–5.8s typically, up to a reported 35s, with a timeout failure at
28051ms against what appears to be a ~30s client-side cap. The pattern
(one slow call, then 30ms–670ms for the rest) is the signature of a
lazy-loaded singleton.

Confirmed and quantified against the code: `rag/embedder.py`'s
`_Embedder._load()` lazily imports `torch` (~0.4s) and
`sentence_transformers` (~1.6s), then instantiates `SentenceTransformer`
(~3.1s with the model already cached locally, more on a cold
HuggingFace Hub cache) — ~5-7s total, measured directly, matching the
reported range. This has always been true of any first semantic
(`query_text`) search or explicit `generate_embeddings` call.

What's new: `fix-approve-proposal-stale-embeddings` (this incident's own
earlier fix) made `approve_proposal` call `embedder.generate_embedding()`
synchronously after every create/update approval. Before that change,
a plain rule/lesson approval never touched the embedder at all — now
the *first* `approve_proposal` after a cold server start also pays this
cost inline, widening the set of calls exposed to the timeout risk from
"the first semantic search" to "the first approval of any kind."

## What Changes

- `rag/embedder.py`: new `warm_up_in_background()` — starts
  `_Embedder._load()` on a daemon background thread, non-blocking.
  Relies on `_load()`'s existing lock/double-checked-None pattern for
  correctness: a real request that arrives before warm-up finishes just
  blocks on the same in-progress load rather than starting a second one
  (the *total* cost per process is unchanged — only how early it starts).
- `server.py::run_stdio` / `run_http`: call
  `embedder.warm_up_in_background()` right after `init_db()`, before
  `mcp.run(...)` starts serving. Unconditional — no flag to disable, since
  it never blocks server startup or connection acceptance either way.

## Capabilities

### New Capabilities
- `embedder-warm-start`: the contract that the MCP server begins loading
  the embedding model in the background as soon as it starts, rather
  than waiting for the first call that needs it.

### Modified Capabilities
(none)

## Impact

- `src/meridian/rag/embedder.py` — new `warm_up_in_background()`.
- `src/meridian/server.py` — `run_stdio`, `run_http`.
- No schema/data changes. No change to `generate_embedding`/
  `generate_embeddings_batch`'s own behavior or signatures.
- Every server start now spends ~5-7s of background CPU loading the
  model, even for a session that never ends up using semantic search or
  approving anything — a deliberate trade-off (see design.md) since it
  never delays the server accepting connections either way.
