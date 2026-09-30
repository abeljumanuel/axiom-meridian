## ADDED Requirements

### Requirement: Block header recognition accepts both `{TECH}`-qualified and plain codes
`atomic_parser.parse()` SHALL recognize a line matching `## RN-<id>` or `## LL-<id>` as the start of a new atomic block, where `<id>` is either a `{TECH}-NNN` pair (one or more uppercase letters/digits, a hyphen, then one or more digits) or a bare `NNN` (one or more digits, no `{TECH}` segment). Both forms SHALL be treated identically by the rest of the parser — neither form takes precedence, and both count toward the same block list.

#### Scenario: Header with a `{TECH}` segment
- **WHEN** a file contains a line `## RN-JAVA-042`
- **THEN** `parse()` includes it as a block

#### Scenario: Header with digits in the `{TECH}` segment
- **WHEN** a file contains a line `## RN-JAVA17-003`
- **THEN** `parse()` includes it as a block

#### Scenario: Plain header with no `{TECH}` segment
- **WHEN** a file contains a line `## RN-086` or `## LL-014`
- **THEN** `parse()` includes it as a block

### Requirement: A recognized block's `code` is the full header line
For any line matched as a block header per the rule above, the resulting `ParsedBlock.code` SHALL be that header line's text with the leading `## ` prefix stripped and surrounding whitespace trimmed — unchanged by whether the header used the `{TECH}` form or the plain form.

#### Scenario: Plain-code block's `code` field
- **WHEN** a file contains `## RN-086` followed by its field lines
- **THEN** the resulting block's `code` SHALL equal `"RN-086"`
