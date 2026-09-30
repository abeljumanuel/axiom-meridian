## 1. Warm-up

- [x] 1.1 `rag/embedder.py`: `warm_up_in_background()` — starts
      `_embedder._load()` on a daemon `threading.Thread`.
- [x] 1.2 `server.py`: call `embedder.warm_up_in_background()` in both
      `run_stdio` and `run_http`, right after `init_db()`, before
      `mcp.run(...)`.

## 2. Regression tests

- [x] 2.1 Unit test: `warm_up_in_background()` returns immediately
      (doesn't block), and the model ends up loaded shortly after
      (poll/join with a timeout) — using the real embedder, since this
      module has no mock seam and the load itself is what's being
      tested.
- [x] 2.2 Unit test: calling `warm_up_in_background()` concurrently with
      a real `generate_embedding()` call doesn't trigger two separate
      loads — assert the model object is the same singleton instance
      either way (`_Embedder` only ever holds one `_model`).
- [x] 2.3 Confirm `run_stdio`/`run_http` call the warm-up function
      (e.g. via monkeypatching `embedder.warm_up_in_background` and
      asserting it was called — these functions call `mcp.run()` which
      blocks, so the test can't run them fully; verify the call happens
      before that point via a fake `mcp.run` too, or via `inspect`/
      source-level check if easier).

## 3. Verification

- [x] 3.1 Run `uv run pytest` — full suite passes.
- [x] 3.2 Run `uv run ruff check src tests` — no new findings.
