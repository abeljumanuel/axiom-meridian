## Why

Re-running `scripts/install.sh` over an existing installation prompts
"Virtual environment already exists at $VENV_DIR / Recreate it? [y/N]".
Answering "N" (the default, and the correct choice when you just want to
keep your existing venv) aborts the entire installer immediately, with no
error message explaining why. Reported by a user who had to "improvisar"
(work around it) to get past reinstallation.

## What Changes

- Fix `setup_venv()` in `scripts/install.sh`: the bare `return` in the
  declined-recreate branch inherits the exit status of the `[[ $REPLY =~
  ^[Yy]$ ]]` test that guards it — which is 1 (false) precisely in that
  branch, because that's why we're in the `else` — and `set -e` (line 22)
  kills the script the instant `setup_venv` (called as a plain statement
  at line 583, not inside a conditional) returns non-zero. Change it to
  `return 0`: declining to recreate the venv is a normal, successful
  outcome (keep the existing venv and continue), not an error.
- Audited every other bare `return` in `install.sh` and `uninstall.sh` (19
  total) for the same class of bug: reached via an `else`/negated branch
  of a condition that evaluated false immediately before the `return`.
  Confirmed this is the *only* instance — every other occurrence is
  reached through a `then` branch (or after a command like `log_info`
  that itself returns 0) where the guarding condition was true, so `$?`
  is already 0 there. No other fix needed.

## Capabilities

### New Capabilities
- `installer-venv-setup`: the contract for `scripts/install.sh`'s
  `setup_venv()` step — what must happen, and what must *not* abort the
  installer, when an existing venv is found at `$VENV_DIR`.

### Modified Capabilities
(none — `install.sh`/`uninstall.sh` have no existing `openspec/specs/`
entry for this)

## Impact

- `scripts/install.sh` — one line (`setup_venv`'s declined-recreate branch).
- No other files. No schema/migration/MCP-tool changes.
- Fixes reinstalling over an existing `~/.meridian` (or custom
  `INSTALL_DIR`) when the user wants to keep their existing venv.
