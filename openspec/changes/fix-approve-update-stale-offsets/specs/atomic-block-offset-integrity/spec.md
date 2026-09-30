## ADDED Requirements

### Requirement: Approving an UPDATE proposal keeps every later block's offset accurate
When `approve_proposal` splices a new block into a `.md` file for a `type="update"` proposal and the new block's byte length differs from the old one, the system SHALL shift `file_offset` by that difference, in the same transaction as the write, for every `rules`/`lessons` row whose `file_path` matches the edited file and whose `file_offset` is greater than the edited block's offset.

#### Scenario: A later block's offset survives an earlier block growing
- **WHEN** an UPDATE proposal is approved for a block, and its new text is longer than its old text, and another rule in the same file is positioned after it
- **THEN** that other rule's `file_offset` in the database increases by exactly the byte-length difference, and it still points at that rule's real header position in the file

#### Scenario: A later block's offset survives an earlier block shrinking
- **WHEN** an UPDATE proposal is approved for a block, and its new text is shorter than its old text
- **THEN** every later rule's `file_offset` in the same file decreases by exactly the byte-length difference

#### Scenario: A second UPDATE approval on the same file no longer corrupts it
- **WHEN** two UPDATE proposals are approved sequentially against different blocks in the same file, and the first one changes its block's byte length
- **THEN** the second approval splices its new text at the correct, up-to-date position, and neither block's content is corrupted or has leftover text from a prior version appended to it

### Requirement: Marking a rule deprecated in its source file keeps every later block's offset accurate
When `promote_rule` marks a rule deprecated in its source `.md` file (`_mark_deprecated_in_md`), which grows that block by one line, the system SHALL shift `file_offset` by that growth, in the same transaction as the write, for every `rules`/`lessons` row whose `file_path` matches the edited file and whose `file_offset` is greater than the deprecated block's offset.

#### Scenario: A later block's offset survives a deprecation marker being inserted
- **WHEN** `promote_rule` marks a rule deprecated in a file that has other rules positioned after it
- **THEN** those other rules' `file_offset` values in the database increase by the byte length of the inserted `**Status:** deprecated` line, and each still points at its real header position

### Requirement: A spliced-in block never glues the next header onto its own content
`_splice_atomic_block` SHALL ensure the block text it writes in place of an old block's byte range ends with exactly one newline, so that whatever follows — another block's header, or end of file — starts on its own line.

#### Scenario: A single UPDATE approval on a block followed by another block
- **WHEN** an UPDATE proposal is approved for a block that has another block immediately after it in the file
- **THEN** re-parsing the file finds both blocks as distinct, correctly-bounded blocks — the next header is not appended to the approved block's last line

#### Scenario: An UPDATE approval on the last block in a file
- **WHEN** an UPDATE proposal is approved for the last block in a file (nothing follows it)
- **THEN** the file still ends with the new block's content followed by a single trailing newline
