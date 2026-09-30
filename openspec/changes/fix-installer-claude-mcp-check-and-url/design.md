## Context

Small, single-function fixes, same shape as the other two installer
changes in this incident's follow-up. Worth a short design note because
the "already configured" check has a real decision point (how to compare
"is this the same venv") that's easy to get subtly wrong — my own first
attempt at the fix did.

## Goals / Non-Goals

**Goals:**
- Re-running `install.sh` when Claude Code already has a `meridian` MCP
  server registered never prints a false "Could not add" failure.
- If the registered command points at a venv other than the one this run
  just set up, say so clearly with the exact fix — don't stay silent
  about it (that's the actual "dos venvs" risk) and don't falsely claim
  a mismatch when it's the same venv invoked a different way.

**Non-Goals:**
- Auto-fixing a detected venv mismatch (removing and re-adding the
  registration) without the user's say-so — printing the two commands is
  enough; this installer doesn't otherwise make unprompted changes to a
  working configuration.
- The Kimi CLI / OpenCode / VSCode "already configured" checks
  (`grep -q '"meridian"' "$config_file"`) — those grep real JSON config
  files, where `"meridian"` genuinely appears quoted as a key. Verified
  this is a different, correct pattern; only the `claude mcp list`
  check (which greps CLI *output*, not a config file) had the bug.
- `scripts/install.ps1` being referenced but not existing — a real gap,
  flagged in the proposal, but deciding whether to write one or remove
  the reference is a different-shaped decision (ship Windows support vs.
  don't claim to) than fixing a wrong URL to match text already correct
  elsewhere in the same file.

## Decisions

**Compare the existing registration against `$BIN_DIR` (the venv's
`bin/` directory), not against the exact `$BIN_DIR/meridian` command.**

First attempt did an exact substring match on `"$BIN_DIR/meridian"`
(the native entry point this installer itself configures) — and failed
its own test: the real registration in the verification environment
invokes `$BIN_DIR/python -m meridian mcp` (same venv, different
invocation style — plausible from a manual setup or an older installer
version), which doesn't contain the substring `$BIN_DIR/meridian` even
though it *is* the same install. That produced a false "different venv"
warning for something that wasn't actually a mismatch. Matching on
`$BIN_DIR` alone (present in both `$BIN_DIR/meridian mcp` and
`$BIN_DIR/python -m meridian mcp`) correctly identifies "same venv"
regardless of which of the two equivalent invocation styles is
registered, and still correctly flags a genuinely different `bin/`
directory as a mismatch. Verified directly against the real `claude mcp
list` output in the environment this was built in, for both the
matching and non-matching cases, plus the not-yet-registered case.

## Risks / Trade-offs

[The mismatch warning's remediation commands assume `-s user` scope,
matching what this installer itself always uses] → if a registration
was added at a different scope (e.g. `-s project`), the suggested
`claude mcp remove -s user meridian` wouldn't find it. Accepted: this
installer has never offered a way to choose scope, so every registration
it could plausibly be comparing against either came from itself (`-s
user`) or from a manual setup the user already knows the scope of.

## Migration Plan

Pure script change, no data/schema impact. Deploy = merge. Takes effect
on the next `install.sh` run; no effect on an install that's already
completed and not re-run.
