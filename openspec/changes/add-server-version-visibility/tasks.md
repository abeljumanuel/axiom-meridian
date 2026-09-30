## 1. Version info core

- [x] 1.1 `src/meridian/utils/version_info.py`: `get_version_info()` —
      walks up from this file's own path to find a `.git` directory;
      returns `{"version", "source_dir", "commit", "commit_date",
      "dirty"}`, with the git fields `None` when no `.git` is found or
      `git` isn't available/fails. Subprocess calls wrapped with a
      timeout and broad exception handling — never raises.

## 2. CLI

- [x] 2.1 `__main__.py::_cmd_version`: print version plus commit/date/dirty
      when available, matching the existing single-line-ish style.

## 3. MCP tool

- [x] 3.1 `src/meridian/tools/server_info.py`:
      `build_server_info_response(startup_info, current_info,
      started_at)` — pure function, no I/O, computing the `stale` flag
      and note.
- [x] 3.2 `server.py`: capture `_STARTUP_VERSION_INFO =
      version_info.get_version_info()` and `_STARTUP_TIME` at module
      import time; add `get_server_info()` tool (no params) calling
      `server_info.build_server_info_response` with a fresh
      `get_version_info()` call.
- [x] 3.3 `utils/security.py`: add `"get_server_info": "read"` to
      `TOOL_ACCESS_LEVELS`.

## 4. Regression tests

- [x] 4.1 Unit tests for `get_version_info()` against this actual repo
      (a real git clone): version matches `meridian.__version__`,
      commit matches `git rev-parse --short HEAD` computed independently
      in the test, `source_dir` resolves to the repo root, `dirty` is a
      bool.
- [x] 4.2 Unit test for `get_version_info()`'s no-git-found path (e.g.
      monkeypatching the search to a tmp dir with no `.git`) — returns
      `None` for all git fields, doesn't raise.
- [x] 4.3 Unit tests for `build_server_info_response()`: same commit →
      `stale=False`; different commits (both known) → `stale=True` with
      a note; either commit `None` → `stale=False`.

## 5. Verification

- [x] 5.1 Run `uv run pytest` — full suite passes.
- [x] 5.2 Run `uv run ruff check src tests` — no new findings.
- [x] 5.3 Manually run `meridian version` in this repo and confirm the
      printed commit matches `git rev-parse --short HEAD`.
