## Why

Flagged in the same installer audit as
`fix-installer-seed-overwrites-existing-kb` (Hallazgo 4c/"dos venvs" in
the user's incident log). Two independent issues in `scripts/install.sh`:

1. **`setup_claude_code()`'s "already configured" check never matches.**
   `claude mcp list` prints plain `name: command - status` lines, not
   JSON — verified directly (`claude mcp list` → `meridian:
   /path/.../bin/python -m meridian mcp - ✔ Connected`, no quotes around
   the name anywhere). The check does `grep -q '"meridian"'` (quoted),
   which never matches this output. Effect verified empirically: a
   second `claude mcp add` for a name that already exists fails with
   exit 1 ("MCP server ... already exists in user config"), so on every
   re-run of `install.sh` where Claude Code is already configured, the
   broken check falls through to `claude mcp add`, which fails, printing
   a confusing "Could not add to Claude Code. Add manually: ..." warning
   — even though Claude Code was already working. This is the direct
   mechanism behind the "dos venvs" confusion: a user seeing that warning
   on a supposedly-successful reinstall has no accurate signal of
   whether Claude Code is actually using the venv this run just set up.

2. **The remote-install URL in `print_usage()` points at a repo that
   doesn't exist.** `curl -fsSL
   https://raw.githubusercontent.com/axiom-juma/meridian/main/...` — the
   real remote is `abeljumanuel/axiom-meridian` (confirmed via `git
   remote -v`), which is what the script's own top-of-file usage comment
   already says (line 8) — just not what `print_usage()` (the `-h`/help
   output) says.

Also noted while reading `print_usage()`: it tells Windows users to "run
scripts/install.ps1 in PowerShell instead" — no such file exists in the
repo. Flagged for the team but **not fixed here** — fixing the
broken/missing URL is a one-line correction to match text that already
exists correctly elsewhere in the same file; writing or removing a
Windows installer is a different-shaped decision out of scope for this
change.

## What Changes

- `setup_claude_code()`: replace the broken `grep -q '"meridian"'` with
  `grep '^meridian:'` against `claude mcp list` output (matching the
  real, verified output format). When already configured, additionally
  compare the existing registration's command against this install's
  `$BIN_DIR` (the venv's `bin/` directory, not the exact command string —
  an existing registration may legitimately invoke `python -m meridian
  mcp` instead of the native `meridian` entry point from the *same*
  venv) and warn with the exact remediation commands if they differ,
  instead of staying silent about a real venv mismatch or falsely
  claiming one.
- `print_usage()`: fix the remote-install URL to match the correct one
  already in the file's top comment.

## Capabilities

### New Capabilities
- `installer-claude-mcp-registration`: the contract for how
  `scripts/install.sh` detects an existing Claude Code Meridian
  registration and what it tells the user when re-running against one.

### Modified Capabilities
(none)

## Impact

- `scripts/install.sh` — `setup_claude_code()`, `print_usage()`.
- No schema/data changes. No effect on a first-time install (nothing
  registered yet, behaves exactly as before). Changes behavior only when
  re-running `install.sh` against an already-configured Claude Code.
