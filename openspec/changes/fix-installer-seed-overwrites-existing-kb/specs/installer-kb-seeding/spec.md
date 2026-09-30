## ADDED Requirements

### Requirement: Seeding never overwrites an existing knowledge base file
`scripts/install.sh`'s `seed_knowledge_base()` SHALL check whether the destination path for a bundled example `.md` file already exists before copying to it, and SHALL skip copying and indexing that file — leaving it and its indexed data completely untouched — when the destination already exists, logging a warning that names the skipped file and the reason.

#### Scenario: Destination file already exists
- **WHEN** `seed_knowledge_base()` runs (via `SEED_KB=1` or an affirmative answer to the seed prompt) and a bundled example file's destination path already exists in `$KNOWLEDGE_BASE_PATH`
- **THEN** that file is not copied, its destination's bytes are unchanged, it is not passed to `meridian index`, and a warning naming it is logged

#### Scenario: Destination file does not exist (fresh install)
- **WHEN** `seed_knowledge_base()` runs and a bundled example file's destination path does not yet exist
- **THEN** the file is copied and indexed exactly as before this change
