## ADDED Requirements

### Requirement: Attribution columns exist on all actor-relevant tables
The system SHALL have a nullable `actor_id TEXT` column on `pending_proposals`, `rule_history`, `lesson_history`, and `access_log`.

#### Scenario: Columns exist after migration
- **WHEN** the database schema is inspected after migration `006_actor_identity.sql` has run
- **THEN** `pending_proposals`, `rule_history`, `lesson_history`, and `access_log` each have an `actor_id` column that accepts `NULL`

#### Scenario: Rows written before this change remain valid
- **WHEN** a pre-existing `pending_proposals`/`rule_history`/`lesson_history`/`access_log` row (written before the migration) is read after migration
- **THEN** its `actor_id` is `NULL` and the row is otherwise unchanged

### Requirement: Actor resolves locally with zero configuration by default
The system SHALL provide `resolve_actor()`, which, when `MERIDIAN_MODE` is unset or `"local"`, SHALL return the OS login name (`getpass.getuser()`) without requiring any credential, token, or additional configuration.

#### Scenario: Default mode resolves the OS user
- **WHEN** `resolve_actor()` is called with `MERIDIAN_MODE` unset
- **THEN** it returns the value of `getpass.getuser()` and raises no error

#### Scenario: Explicit local mode behaves the same as unset
- **WHEN** `MERIDIAN_MODE=local` is set and `resolve_actor()` is called
- **THEN** it returns the same value as when `MERIDIAN_MODE` is unset

### Requirement: Shared mode is recognized but not implemented
The system SHALL read `MERIDIAN_MODE="shared"` as a distinct, recognized value, and `resolve_actor()` SHALL raise `NotImplementedError` with a message indicating shared mode is not yet implemented, rather than silently falling back to local resolution or crashing with an unrelated error.

#### Scenario: Shared mode raises a clear error
- **WHEN** `MERIDIAN_MODE=shared` is set and `resolve_actor()` is called
- **THEN** it raises `NotImplementedError` and the message mentions `MERIDIAN_MODE` or "shared"

#### Scenario: An unrecognized mode value is rejected
- **WHEN** `MERIDIAN_MODE` is set to a value other than `"local"` or `"shared"`
- **THEN** `resolve_actor()` (or the mode-reading helper it uses) raises `ValueError` naming the invalid value

### Requirement: Local mode does not change existing access-control behavior
In `MERIDIAN_MODE="local"` (or unset), `check_access` SHALL behave identically to its current behavior based solely on `MERIDIAN_ACCESS_LEVEL`; the resolved actor SHALL be used only for attribution in the new `actor_id` columns and SHALL NOT affect whether a tool call is allowed or denied.

#### Scenario: Access decisions are unaffected by the actor
- **WHEN** the same tool call is made twice under `MERIDIAN_MODE=local` with `MERIDIAN_ACCESS_LEVEL` held constant, differing only in the OS user running the process
- **THEN** `check_access` produces the same allow/deny result both times

### Requirement: Write paths persist the resolved actor
`_security_pattern`'s call to `log_tool_access`, `create_pending_proposal`, and `approve_proposal`'s `rule_history`/`lesson_history` insert branches SHALL persist the result of `resolve_actor()` into each row's `actor_id`.

#### Scenario: A tool call is attributed in access_log
- **WHEN** any MCP tool is invoked successfully, denied, or erroring, under `MERIDIAN_MODE=local`
- **THEN** the resulting `access_log` row's `actor_id` equals `resolve_actor()`'s value at call time

#### Scenario: A proposal is attributed on creation
- **WHEN** `create_pending_proposal` is called
- **THEN** the created `pending_proposals` row's `actor_id` equals `resolve_actor()`'s value at call time

#### Scenario: Approving a proposal attributes the resulting history row
- **WHEN** any proposal type is approved via `approve_proposal`
- **THEN** the resulting `rule_history`/`lesson_history` row's `actor_id` equals `resolve_actor()`'s value at approval time, independent of the `actor_id` recorded on the originating proposal
