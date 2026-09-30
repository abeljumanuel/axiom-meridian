## Context

Two small, additive, low-risk fixes bundled together because they touch
the same two functions the previous incident's changes already
modified. The other two items from the same follow-up report are
deliberately excluded — this section is mostly about justifying those
exclusions, since the fixes themselves are straightforward.

## Goals / Non-Goals

**Goals:**
- A caller of `approve_proposal` can tell, from the response alone,
  whether the row is embedded.
- Re-approving an UPDATE that only changes text (not structure) doesn't
  also silently change the file's blank-line formatting around it.

**Non-Goals — and why each is out of THIS change:**

- **A client-visible MCP-level warning for `query_rules`'s
  pending-embeddings case.** FastMCP supports emitting log notifications
  via a `Context` object injected into a tool function, separate from
  the tool's return value — this wouldn't touch ADR-001's plain-array
  contract. But whether an MCP client actually surfaces those
  notifications to the calling agent is untested in this codebase (no
  existing tool uses `Context` at all) and varies by client. Building
  this before confirming it actually reaches the agent risks solving the
  wrong layer of the problem. Needs a throwaway spike (emit one test
  notification, confirm the client the reporting team uses actually
  shows it) before committing to a design here.
- **File locking across concurrent `meridian` processes.** ADR-006
  explicitly scoped this out ("no connection-pool fix inside the server
  process can prevent this anyway [cross-process contention]"); revisiting
  it is reopening a closed architectural decision, not a quick fix. A
  naive lock (a lock file, or a SQLite-table mutex) risks a worse failure
  mode than today's rare race — a stale lock orphaned by a crashed
  process can hang every future writer — and picking the right TTL/
  recovery strategy deserves its own design doc, not a bundled add-on
  here.

## Decisions

**`_embed_and_upsert_after_approve` returns `bool`, not the full
embedding metadata.**

Rejected alternative: return the embedding_id/hash or a richer status
dict. Rejected as speculative — nothing in the current ask needs more
than "did it work," and CLAUDE.md's own guidance is against designing
for hypothetical future callers. `True`/`False` is the minimum that
answers "is this searchable via query_text now."

**Preserve the separator by counting trailing `\n` on `old_block_text`
(already in hand), not by re-parsing the file.**

`_splice_atomic_block` already decodes `old_block_text` from the exact
byte range being replaced — `len(old_block_text) - len(old_block_text.rstrip("\n"))`
gives the exact newline count with no extra I/O or parsing. Floors at 1
because a separator must exist regardless (an old block somehow ending
with zero newlines — shouldn't happen given every block builder always
starts a line with `## `, but the floor costs nothing and avoids ever
producing a glued header as a side effect of this change).

## Risks / Trade-offs

[A future caller of `approve_proposal` might come to depend on
`embedded: false` as an error signal and expect the approval itself to
have failed] → mitigated by the field's name and the tool's own
docstring update: `embedded` is orthogonal to approval success: the
proposal/row write already committed before this is computed. Approval
failure still surfaces the normal way (an exception).

## Migration Plan

Pure code change, additive, no schema/data impact. Deploy = merge +
restart. No effect on any already-approved proposal.
