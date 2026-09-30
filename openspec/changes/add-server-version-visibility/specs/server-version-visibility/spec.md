## ADDED Requirements

### Requirement: `meridian version` reports the running commit for a git-clone install
`meridian version` SHALL print the package version, and, when run from a git clone, SHALL also print the current commit (short SHA), its commit date, and whether the working tree is dirty. When not run from a git clone (e.g. a built wheel) or `git` is unavailable, it SHALL print only the package version without error.

#### Scenario: Running from a git clone
- **WHEN** `meridian version` runs from an editable install cloned from git
- **THEN** its output includes the package version and the current commit's short SHA

#### Scenario: Running from a non-git install
- **WHEN** `meridian version` runs from an install with no `.git` directory reachable from the package's own file location
- **THEN** it prints the package version and exits successfully, with no commit information and no error

### Requirement: `get_server_info` reports whether the running process's code is stale relative to disk
The `get_server_info` MCP tool SHALL return the version and commit captured once when the server process started, a freshly-read commit as of the call, and an explicit `stale` flag that is true only when both commits are known and differ.

#### Scenario: Server has not changed since startup
- **WHEN** `get_server_info` is called and the on-disk commit matches the commit captured at server startup
- **THEN** the response's `stale` field is `false`

#### Scenario: Code on disk changed after the server started (e.g. a `git pull` with no restart)
- **WHEN** `get_server_info` is called and the on-disk commit differs from the commit captured at server startup
- **THEN** the response's `stale` field is `true` and includes a note that a restart is needed to pick up the change

#### Scenario: Non-git install
- **WHEN** `get_server_info` is called on an install with no git commit information available at all
- **THEN** `stale` is `false` (no basis for comparison), and the commit fields are `null` rather than causing an error
