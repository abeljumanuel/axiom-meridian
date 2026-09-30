## ADDED Requirements

### Requirement: `approve_proposal` reports whether the row was embedded
`approve_proposal`'s response SHALL include an `embedded` boolean field reflecting whether embedding and upserting the just-approved row into the vector store succeeded, without this field's value affecting whether the approval itself is reported as successful.

#### Scenario: Embedding succeeds
- **WHEN** a proposal is approved and its row is successfully embedded and upserted into the vector store
- **THEN** the response includes `"embedded": true`

#### Scenario: Embedding fails
- **WHEN** a proposal is approved but embedding or upserting the row raises an exception
- **THEN** the response still reports the approval's normal fields (it does not raise), and includes `"embedded": false`

### Requirement: Splicing a block preserves the original separator's newline count
When `approve_proposal`'s update path replaces an existing block's bytes in place, the system SHALL end the replacement with the same number of trailing newlines the original block ended with (minimum 1), instead of a fixed single newline.

#### Scenario: Original block was followed by a blank line
- **WHEN** the block being replaced originally ended with two newlines (a blank-line separator before the next header)
- **THEN** the replacement block also ends with two newlines

#### Scenario: Original block was followed immediately by the next header (no blank line)
- **WHEN** the block being replaced originally ended with exactly one newline
- **THEN** the replacement block also ends with exactly one newline
