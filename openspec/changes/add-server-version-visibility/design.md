## Context

Diagnostic/observability feature, not a correctness bug fix like the
rest of this incident's follow-up changes — included because the
reporting user's own workaround (comparing `ps` start time against file
mtimes by hand) is exactly the kind of manual correlation a tool should
do instead.

## Goals / Non-Goals

**Goals:**
- `meridian version` shows enough to identify exactly which commit's
  code is running, for a git-clone (editable) install.
- An MCP client can ask a running server "is your code stale relative to
  disk" without shell access to the host.

**Non-Goals:**
- Auto-restarting or hot-reloading the server when disk code changes.
  Out of scope — this is visibility, not a process-supervision feature.
- Making `__version__` itself dynamic (e.g. derived from git describe at
  build time via setuptools-scm or similar). That's a real alternative
  for a *packaged* release, but this project ships primarily via
  `pip install -e .` from a git clone (`scripts/install.sh`), where the
  git commit itself is already the more precise and more available
  signal — no build-time tooling required.
- Exposing this for non-git installs beyond "gracefully report nothing
  and don't crash." A wheel/sdist install has no commit to report; that
  is an accurate, not a broken, answer.

## Decisions

**Compute "commit now" by shelling out to `git`, not by parsing `.git`
internals directly.**

Rejected alternative: read `.git/HEAD` and the ref file it points to
by hand, to avoid a subprocess and a hard dependency on `git` being
installed. Rejected because a dirty-working-tree check (`git status
--porcelain`) has no reasonable hand-rolled equivalent short of
re-implementing a meaningful chunk of git's index/worktree diffing —
and every install this project documents already requires `git` (it's
how the repo was cloned in the first place per `scripts/install.sh`'s
own instructions). Subprocess calls are wrapped with a timeout and broad
exception handling so a missing/broken `git` degrades to "no commit
info," never a crash.

**Capture the startup snapshot once, at `server.py` import time, as a
module-level constant — not lazily on first tool call.**

A lazy "first call wins" snapshot would, on a freshly-restarted server
whose first real tool call happens to be `get_server_info` itself after
a `git pull`, record the *new* commit as "at startup" — defeating the
entire point (the snapshot must reflect what the process's imported
Python bytecode actually corresponds to, not whatever happened to be on
disk when someone first asked). Import-time capture ties the snapshot to
process start as closely as Python allows.

**`get_server_info` takes no parameters and isn't project-scoped.**

Server/process identity has nothing to do with any particular project or
scope — matching how `list_pending_proposals` etc. already treat
`project_id` as optional, but going further since there's no project
dimension here at all. `_security_pattern` is called with `project_id=None`,
same as any other non-project tool.

## Risks / Trade-offs

[`git` subprocess calls add a small latency to `meridian version` and to
every `get_server_info` call] → accepted: each call is `git rev-parse`/
`git log -1`/`git status --porcelain` against a local repo, all fast
(milliseconds), and `get_server_info` is a diagnostic tool, not one
called in a hot path.

[Two processes could start at the exact same on-disk commit, one then
observes a later `git pull`, but a third process started *during* that
pull could capture an inconsistent/mid-write git state] → accepted,
extremely narrow window, and `git`'s own atomicity (HEAD updates last)
means the practical failure mode is "briefly reports the pre-pull
commit," never a corrupt read.

## Migration Plan

Pure addition, no schema/data changes, no effect on any existing tool.
Deploy = merge + restart (to pick up the new tool at all, same as any
other server.py change).
