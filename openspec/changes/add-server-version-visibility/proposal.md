## Why

Reported (Hallazgo 7): after `git pull`-ing a fix, an already-running
`meridian mcp` process kept behaving like the old code — expected, since
this is an editable install (`pip install -e .`) and Python doesn't
hot-reload a running process, but there was no way to *detect* this
short of comparing `ps`'s process start time against `stat`'s file
mtimes by hand (what the reporting user actually did).

Confirmed against the code: `meridian version`
(`__main__.py::_cmd_version`) prints only `f"Axiom Meridian
v{__version__}"`, where `__version__` is a static string in
`meridian/__init__.py` ("0.1.0") that isn't bumped per-commit — across
every fix landed in this incident's own follow-up session, it never
changed. It carries no git commit information, so there is no way to
tell, from its output alone, which commit's code is actually running.
No MCP tool or resource exposes any server/version info at all.

## What Changes

- New `utils/version_info.py::get_version_info()`: returns the package
  version plus (when running from a git clone — true for every install
  this project's `install.sh` produces, since it's always editable) the
  current commit, commit date, and a dirty-working-tree flag. Returns
  `None` for the git fields when there's no `.git` (e.g. a built wheel)
  or `git` isn't available — never raises.
- `meridian version` (CLI): print the commit/date/dirty info alongside
  the existing version line, when available.
- New MCP tool `get_server_info` (access level: read, no params): returns
  the version/commit captured once when the server process started,
  **and** a fresh read of the commit on disk right now, with an explicit
  `stale` flag (and human-readable note) when they differ — directly
  answering "is the code on disk newer than what this running process
  loaded" without manual `ps`/`stat` comparison.
- New `tools/server_info.py::build_server_info_response()`: the pure,
  directly-testable logic behind the tool (startup snapshot in, current
  snapshot in, response dict out) — following this codebase's existing
  layering (`server.py` stays a thin `_security_pattern` wrapper; real
  logic lives in `tools/`).

## Capabilities

### New Capabilities
- `server-version-visibility`: the contract for what `meridian version`
  and the `get_server_info` tool report, and when a running process is
  considered to have stale (on-disk-changed-since-startup) code.

### Modified Capabilities
(none)

## Impact

- `src/meridian/utils/version_info.py` (new).
- `src/meridian/tools/server_info.py` (new).
- `src/meridian/__main__.py` — `_cmd_version`.
- `src/meridian/server.py` — new `get_server_info` tool, module-level
  startup snapshot captured at import time.
- `src/meridian/utils/security.py` — `TOOL_ACCESS_LEVELS["get_server_info"]
  = "read"`.
- No schema/migration changes. No effect on any existing tool's behavior
  or return shape.
