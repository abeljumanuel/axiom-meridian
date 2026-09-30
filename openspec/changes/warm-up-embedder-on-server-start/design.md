## Context

Diagnosed with real measurements (not just the reporting team's log
timings, independently reproduced): `import torch` ~0.4s, `import
sentence_transformers` ~1.6s, `SentenceTransformer(...)` instantiation
~3.1s (model already cached locally) — ~5-7s total on the first call
that needs the embedder, falling to ~25ms on every call after. This is
inherent to the libraries involved, not a meridian inefficiency;
`_Embedder` was already correctly lazy and singleton-cached before this
change.

## Goals / Non-Goals

**Goals:**
- Reduce the chance that the first `approve_proposal` (or first semantic
  search) after a cold server start hits a client-side timeout, by
  starting the model load as early as possible.

**Non-Goals:**
- Eliminating the load cost itself. Not possible without a fundamentally
  different (and much heavier) embedding approach — out of scope.
- A flag to disable warm-up for KBs that never use embeddings. Considered
  and rejected: warm-up runs in the background and never blocks server
  startup or the first non-embedding tool call either way, so there's no
  real cost to opt out of — the flag would add a knob nobody needs to
  turn.
- Fixing the *first-call-after-cold-cache* worst case (a genuine
  HuggingFace Hub download, potentially much slower than the ~5-7s
  measured here with a warm local cache). That's an installation/
  environment concern (network speed, HF Hub availability), not
  something warm-up timing changes — it just starts the (possibly slow)
  download sooner instead of later.

## Decisions

**Background thread at server start, not eager loading before `mcp.run()`
blocks (synchronous warm-up) and not a config flag to opt in/out.**

Rejected alternative: load the model synchronously in `run_stdio`/
`run_http` before calling `mcp.run()`, so the server doesn't start
accepting connections until it's ready. Rejected because that moves the
problem rather than solving it: the *client's* connection attempt would
then wait out the full 5-7s (or worse, cold-cache) load before the
server even accepts the connection — plausibly the same timeout failure
observed, just relocated from "first tool call" to "initial connect."
A background thread lets the server accept the connection immediately
and only makes the *embedding-needing* call potentially wait, and only
for whatever's left of the load by the time it arrives.

**Reuse `_Embedder._load()`'s own lock rather than a separate
"is warming up" flag or `asyncio` task.**

`_load()` already double-checks `self._model is not None` before and
after acquiring its lock — exactly the coordination needed between the
background warm-up thread and a real request thread arriving mid-load.
Adding a second coordination mechanism (a flag, a future/task the real
call could `await`) would duplicate what the lock already guarantees
correctly, for no behavior difference — a background caller and a real
caller converge on the exact same "wait for whoever's loading it" outcome
either way.

## Risks / Trade-offs

[Every server start now spends ~5-7s of CPU loading a model that a given
session might never use (e.g. a purely read-only `query_rules` session
with no `query_text`)] → accepted: the cost is backgrounded (doesn't
delay startup or non-embedding tool calls), and `approve_proposal` now
always attempts to embed regardless — the "never needs it" case is
narrower than it used to be, and the compute cost itself is a fixed
~5-7s of one CPU core, not something scaling with KB size or usage.

[If the daemon thread's model load raises (e.g. `sentence_transformers`
not installed, corrupted cache), the exception is silently lost — daemon
threads don't propagate exceptions to the main thread] → acceptable:
`_load()`'s own exception, if any, will simply surface again on the
first real caller (which re-enters `_load()`, hits the lock, and — since
`self._model` is still `None` — retries the same import/instantiation
and raises the same way it always would have without warm-up). Warm-up
failing just forfeits its own head start, it doesn't hide the underlying
problem from the caller who actually needs the answer.

## Migration Plan

Pure code change, no schema/data impact. Deploy = merge + restart the
MCP server process (needed regardless to pick up any change, per
Hallazgo 7's own finding).
