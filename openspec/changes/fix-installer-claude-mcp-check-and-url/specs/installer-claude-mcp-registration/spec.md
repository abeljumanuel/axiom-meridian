## ADDED Requirements

### Requirement: Detecting an existing Claude Code registration matches the real `claude mcp list` output format
`scripts/install.sh`'s `setup_claude_code()` SHALL detect an existing `meridian` registration by matching `claude mcp list`'s actual plain-text output format (`name: command - status`, unquoted), and SHALL NOT attempt to re-add a registration that already exists.

#### Scenario: Meridian already registered
- **WHEN** `claude mcp list` includes a line starting with `meridian:`
- **THEN** `setup_claude_code()` does not call `claude mcp add` and does not print a "Could not add to Claude Code" failure

#### Scenario: Meridian not yet registered
- **WHEN** `claude mcp list` includes no line starting with `meridian:`
- **THEN** `setup_claude_code()` proceeds to call `claude mcp add` as before

### Requirement: A venv mismatch in an existing registration is surfaced, not silently ignored or falsely claimed
When Meridian is already registered in Claude Code, `setup_claude_code()` SHALL compare the registered command against this install's venv `bin/` directory and SHALL warn with the exact remediation commands only when they genuinely differ — not when the registration uses an equivalent invocation of the same venv.

#### Scenario: Existing registration uses the same venv via a different invocation
- **WHEN** the existing registration invokes `$BIN_DIR/python -m meridian mcp` (same venv as this install, `python -m` style) rather than `$BIN_DIR/meridian mcp` (the native entry point)
- **THEN** no mismatch warning is printed

#### Scenario: Existing registration points at a different venv
- **WHEN** the existing registration's command does not contain this install's `$BIN_DIR`
- **THEN** a warning is printed naming the currently-registered command and the exact `claude mcp remove`/`claude mcp add` commands to switch it to this install
