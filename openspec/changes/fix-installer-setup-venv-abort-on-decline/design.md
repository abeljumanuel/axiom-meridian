## Context

Single-line bug in a bash installer script, no new dependency or
cross-cutting change. Included because the actual root cause (`return`'s
exit-code inheritance under `set -e`) is a common bash footgun worth
getting right rather than papering over, and because the fix required
auditing 19 other occurrences of the same syntactic pattern to confirm
none of them share the bug.

## Goals / Non-Goals

**Goals:**
- Declining to recreate an existing venv (`Recreate it? [y/N]` → N, the
  default) must let `install.sh` continue normally, reusing the existing
  venv, instead of aborting.

**Non-Goals:**
- Auditing bash scripts elsewhere in the repo for the same pattern
  (`scripts/` only has `install.sh`/`uninstall.sh`; both were audited).
- Changing `set -e` itself, or the `read -p ... [y/N]` confirmation UX.
- Adding a test harness (e.g. bats) for these scripts — none exists today
  and introducing one is out of scope for a one-line fix.

## Decisions

**`return 0` instead of restructuring the if/else.**

Root cause: in
```bash
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$VENV_DIR"
else
    return
fi
```
the `else` branch is only reached when `[[ $REPLY =~ ^[Yy]$ ]]` was
false, i.e. exit status 1. A bare `return` with no operand returns
*that* pending `$?` — bash does not reset `$?` to 0 just because control
entered a branch; only running another command does. Since `return` is
the branch's only statement, `setup_venv` returns 1. `setup_venv` is
called as a plain statement (`scripts/install.sh:583`), not inside an
`if`/`&&`/`||`, so under `set -e` a non-zero return from it is treated
exactly like a failing command and the whole script exits — silently,
with no error message, immediately after the "already exists" warning.

Rejected alternative: wrap the `setup_venv` call site in `setup_venv ||
true` or `if ! setup_venv; then ...`. Rejected because it treats the
symptom at the call site instead of the actual bug (a function that
reports failure for a successful, intended code path), and would leave
the same landmine for the next branch added to this function or copied
elsewhere.

Rejected alternative: reorder to `if [[ ! $REPLY =~ ^[Yy]$ ]]; then
return; else rm -rf ...; fi` (negate the condition so the `return` sits
in a `then` branch, entered when the condition is true). Functionally
equivalent to `return 0`, but changes the diff shape and inverts the
primary/secondary branch order for no benefit — `return 0` is a
one-token fix that states the intent directly ("this is a success exit").

## Risks / Trade-offs

[The same `return`-inherits-`$?` pattern could be reintroduced by a
future edit to any of these functions] → not mitigated by this change
beyond the one-time audit recorded in the proposal; no lint rule
currently catches it (shellcheck's SC2317/SC2251 don't cover this
specific case). Acceptable: out of scope for a one-line bug fix, and no
bash test harness exists yet to encode it as a regression test.

## Migration Plan

Pure script change, no data/schema impact. Deploy = merge; the fix takes
effect the next time someone runs `scripts/install.sh` (or `curl | bash`
from `main`) against an existing installation. Rollback = revert the one
line.
