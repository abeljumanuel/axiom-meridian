## Why

`scripts/install.sh`'s `seed_knowledge_base()` copies the repo's bundled
example `.md` files (`knowledge-base/global/java.md`,
`knowledge-base/global/clean-code.md`, etc.) into `$KNOWLEDGE_BASE_PATH`
with a plain `cp "$f" "$dest"` — no check for whether `$dest` already
exists, no `-n`/no-clobber, no backup. The repo ships its own example
`knowledge-base/global/java.md` (3 sample rules), and a real KB commonly
has a `java.md` of its own (the java-focused sibling of any Spring/Java
codebase). Re-running `install.sh` over an existing installation — either
with `SEED_KB=1`, or by answering "y" to the seed prompt — silently
overwrites the real file with the bundled sample, with no warning and no
way to undo it. The subsequent reindex call
(`"$BIN_DIR/meridian" index rules "$dest" --scope "$scope"`, mode
defaults to `atomic`) then upserts the DB's `rules` rows for any matching
`code`s too, compounding the damage into SQLite.

Flagged by a user auditing `install.sh` after the stale-offset incident
(`openspec/changes/fix-approve-update-stale-offsets/`) — not executed
against their real KB, confirmed by reading the code and reproducing the
filename collision (the repo's own `knowledge-base/global/java.md`
exists, same name as a plausible real KB file). This is more severe than
that incident: the offset corruption was recoverable because the correct
text still lived in SQLite; an overwritten source file has no fallback.

## What Changes

- `seed_knowledge_base()`: before copying each bundled example file,
  check whether the destination already exists. If it does, skip that
  file (and its reindex) entirely and log a clear warning naming the
  file and why it was skipped, instead of silently overwriting it.
- Files that don't already exist at the destination are seeded exactly
  as before — this only changes behavior for the collision case.
- Regression test: not applicable in this repo's Python test suite
  (`install.sh` has no existing shell test harness — see
  `fix-installer-setup-venv-abort-on-decline`'s design.md for why one
  isn't being introduced here either); verified manually per the
  Verification section of that change's pattern, documented in tasks.md.

Not in scope: adding a `--force`/override flag to intentionally reseed
over existing files. Nobody has asked for that; if it's ever needed, the
manual escape hatch (delete or rename the destination file, then
re-run) already works.

## Capabilities

### New Capabilities
- `installer-kb-seeding`: the contract that seeding the bundled example
  knowledge base never destroys existing data at the destination.

### Modified Capabilities
(none)

## Impact

- `scripts/install.sh` — `seed_knowledge_base()` only.
- No effect on a fresh install (nothing exists at the destination yet,
  so every bundled file seeds exactly as before).
- No effect on `SEED_KB=0` (already skips entirely) or on files the repo
  doesn't bundle (nothing to collide with).
