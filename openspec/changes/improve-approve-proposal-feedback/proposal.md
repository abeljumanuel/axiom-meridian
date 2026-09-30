## Why

Follow-up from the reporting team after verifying
`fix-approve-proposal-stale-embeddings` and
`fix-approve-update-stale-offsets`: two residual gaps they flagged as
still observable, both already-known, already-documented trade-offs
(not regressions) — but worth closing where cheap to do so:

1. **`approve_proposal`'s return value says nothing about whether
   embedding succeeded.** `_embed_and_upsert_after_approve` runs after
   commit and swallows its own exceptions by design (an embedding
   failure must never fail the approval) — but the caller currently has
   no way to know, from the tool's own response, whether the new/updated
   row is actually searchable via `query_text` yet, short of separately
   calling `get_rule_context`/`query_rules` or watching server logs.
2. **`_splice_atomic_block` always normalizes the separator before the
   next block to exactly one `\n`,** regardless of what was there before
   (a blank line, i.e. two newlines, in the common case). Confirmed
   harmless (`atomic_parse` reads either form identically — verified via
   the existing regression tests), but changes formatting the user
   didn't ask to change.

Two other items from the same follow-up (a client-visible MCP-level
warning for `query_rules`'s "some rules aren't embedded yet" case, and
file locking across concurrent `meridian` processes) are **explicitly
not in this change** — see design.md for why each needs its own
investigation/design pass rather than a quick fix here.

## What Changes

- `_embed_and_upsert_after_approve` returns `bool` (`True` on successful
  embed+upsert, `False` on any failure) instead of `None`.
- `_approve_create_proposal` and `_approve_update_proposal` include the
  result as `"embedded": bool` in their returned dict — additive only,
  no existing field changes.
- `_splice_atomic_block` counts the trailing newlines on the *old*
  block's text (already available — it already reads and returns
  `old_block_text`) and reproduces that same count at the end of the new
  block, instead of unconditionally collapsing to one. Floors at 1 (a
  separator must exist) for the unexpected case of an old block with
  none.

## Capabilities

### New Capabilities
- `approve-proposal-response-feedback`: the contract for what
  `approve_proposal`'s response tells the caller about embedding status,
  and what `_splice_atomic_block` preserves about the original file's
  block-separator formatting.

### Modified Capabilities
(none — `atomic-block-offset-integrity` and
`approve-proposal-embedding-sync`, the related capabilities from the two
prior changes this builds on, were never archived into
`openspec/specs/` yet, so there is no main spec to target a delta
against; this adds its own capability instead, consistent with how
every change so far in this incident's follow-up has been recorded)

## Impact

- `src/meridian/tools/knowledge_management.py` —
  `_embed_and_upsert_after_approve`, `_approve_create_proposal`,
  `_approve_update_proposal`, `_splice_atomic_block`.
- No schema/migration changes. No existing return field removed or
  changed in meaning — `embedded` is additive.
- `shift_offsets_after`'s delta computation (`new_length - old_length`)
  is unaffected: both lengths are still measured the same way, just with
  the new block's trailing-newline count matching the old one's instead
  of being fixed at 1.
