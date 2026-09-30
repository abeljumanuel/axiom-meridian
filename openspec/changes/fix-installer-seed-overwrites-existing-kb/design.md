## Context

Single-function fix in a bash installer script, same shape as
`fix-installer-setup-venv-abort-on-decline`. Included mainly to record
why "skip silently-ish (warn, don't overwrite)" was chosen over the
alternatives, since a data-loss bug's fix deserves the reasoning on
record.

## Goals / Non-Goals

**Goals:**
- Re-running `install.sh` (with `SEED_KB=1` or answering "y") over an
  existing KB must never overwrite a file that's already there.

**Non-Goals:**
- Merging or diffing the bundled example against an existing file of the
  same name — out of scope; "don't touch it" is sufficient and far
  simpler than "figure out how to combine them."
- A `--force` flag to intentionally overwrite. Not requested; the manual
  workaround (move the existing file aside, re-run, put it back) already
  covers the rare intentional case without adding a permanently-armed
  footgun to the default path.
- Backing up the existing file before skipping it. There's nothing to
  back up — the fix is to never touch it in the first place, which is
  strictly safer than "touch it, but keep a copy."

## Decisions

**Skip + warn, not prompt-per-file.**

Rejected alternative: prompt the user file-by-file ("`java.md` already
exists, overwrite? [y/N]"). Rejected because `SEED_KB=1` exists
specifically to make this step non-interactive (used by the reporting
user's own `SEED_KB=0 SKIP_MCP=1` invocation, and presumably by CI/
scripted installs); reintroducing a prompt here defeats that, and the
already-existing top-level "seed at all? [y/N]" prompt is where user
intent belongs. A skip-and-log is non-interactive, safe by default, and
still visible in the install output.

Rejected alternative: back up the existing file (e.g. to
`$dest.bak`) before overwriting, instead of skipping. Rejected as more
surprising, not less: the user asked to seed the *example* KB, not to
have their real file silently renamed. Skipping leaves the real file
exactly where it was, under the name every other Meridian tool expects
it at (`file_path` in SQLite, scope resolution, etc.) — a `.bak` sibling
achieves nothing a skip doesn't, while adding a stray file for the user
to notice and clean up later.

## Risks / Trade-offs

[A user who genuinely wants to replace their KB with the bundled
examples now has to do it manually] → acceptable: that's a deliberate,
rare action (starting over), not the common case this function serves
(seeding an *empty* KB on first install), and the manual path (remove or
rename the destination, re-run) is one line.

## Migration Plan

Pure script change, no data/schema impact. Deploy = merge. No effect on
already-completed installs; changes behavior only on the next
`install.sh` run against a KB that already has a same-named file.
