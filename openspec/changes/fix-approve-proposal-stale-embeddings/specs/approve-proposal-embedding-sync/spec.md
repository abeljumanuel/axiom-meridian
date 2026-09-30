## ADDED Requirements

### Requirement: Approving a new rule or lesson embeds it into the vector store
After `approve_proposal` successfully creates a new rule or lesson, the system SHALL embed its text and upsert it into the corresponding ChromaDB collection, and SHALL set its `embedding_id`, without this step affecting whether the approval itself succeeded.

#### Scenario: A newly-approved rule is immediately findable via semantic search
- **WHEN** a `type="rule"` proposal is approved via `approve_proposal`
- **THEN** the new rule's code appears in `vector_store.search_rules` results for a semantically-related query, without any separate `generate_embeddings` call

#### Scenario: Embedding failure does not affect the approval
- **WHEN** embedding or upserting a newly-approved row raises an exception (e.g. the vector store is unavailable)
- **THEN** `approve_proposal` still returns successfully with the row committed to `rules`/`lessons`, and the row's `embedding_id` remains `NULL` for a later `generate_embeddings` pass

### Requirement: Approving an UPDATE proposal refreshes the existing vector-store entry
After `approve_proposal` successfully applies a `type="update"` proposal, the system SHALL re-embed the target's new text and upsert it into the vector store under the same id, replacing whatever was stored there before, without this step affecting whether the approval itself succeeded.

#### Scenario: An updated rule no longer serves stale tags/text via semantic search
- **WHEN** a `type="update"` proposal changes a rule's text and tags, and is approved
- **THEN** a subsequent semantic search returning that rule's id serves the new text and new tags, not the pre-update ones

### Requirement: Pending (un-embedded) rows are logged, not silently omitted, during semantic search
When `query_rules` or `query_lessons` runs a `query_text` (semantic) search, the system SHALL log a warning naming the count of active rows in the queried scopes whose `embedding_id` is still `NULL`, if any, instead of omitting them from results with no signal.

#### Scenario: Some active rules in scope are not yet embedded
- **WHEN** `query_rules(query_text=...)` runs and one or more active rules in the resolved scopes have `embedding_id IS NULL`
- **THEN** a warning is logged naming how many, and the semantic search still returns whatever embedded results match (unchanged behavior otherwise)
