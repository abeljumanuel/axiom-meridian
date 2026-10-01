## ADDED Requirements

### Requirement: A rule or lesson can be deprecated without a scope change
The system SHALL provide a `deprecate_rule(rule_id, reason, superseded_by=None)` tool that deprecates a rule or lesson (by `RN-`/`LL-` id) independently of `promote_rule`, and SHALL NOT require or perform any scope change as part of deprecation.

#### Scenario: Deprecating a rule that stays in its original scope
- **WHEN** `deprecate_rule` is called with the id of an active rule and a reason, and the resulting proposal is approved
- **THEN** the rule's `status` becomes `deprecated` and its `scope_id` is unchanged from before the call

#### Scenario: Deprecation does not take effect before approval
- **WHEN** `deprecate_rule` is called
- **THEN** the target rule's `status` remains `active` until the resulting proposal is approved via `approve_proposal`

### Requirement: Deprecation proposals carry a reason and an optional replacement reference
The system SHALL persist the `reason` given to `deprecate_rule` on the resulting `pending_proposals` row, and SHALL accept an optional `superseded_by` value without requiring it.

#### Scenario: Reason is stored on the pending proposal
- **WHEN** `deprecate_rule(rule_id="RN-077", reason="No longer applies after the v2 rewrite")` is called
- **THEN** the created `pending_proposals` row has `reason` equal to the given text

#### Scenario: Deprecating without a replacement is accepted
- **WHEN** `deprecate_rule` is called without a `superseded_by` argument
- **THEN** the proposal is created successfully and, once approved, the resulting `rule_history`/`lesson_history` row has `superseded_by` set to `NULL`

### Requirement: Approving a deprecation updates SQLite, the source .md file, and history together
When a `type="deprecate"` proposal is approved, the system SHALL, within a single transaction, set the target's `status` to `deprecated`, mark the corresponding block in its source `.md` file, and insert a `rule_history`/`lesson_history` row with `change_type='DEPRECATED'` carrying the proposal's `reason` and `superseded_by`.

#### Scenario: Full atomic effect of an approved deprecation
- **WHEN** a `type="deprecate"` proposal for `RN-077` is approved
- **THEN** `rules.status` for `RN-077` becomes `deprecated`, its source `.md` block is marked deprecated, and a new `rule_history` row exists with `change_type='DEPRECATED'`, the proposal's `reason`, and its `superseded_by` (or `NULL` if none was given)

### Requirement: Rule/lesson timelines surface deprecations from both deprecate_rule and promote_rule
`get_rule_audit_log`'s `deprecated_rules` output SHALL include rules deprecated via `deprecate_rule` (`change_type='DEPRECATED'`) and rules deprecated via `promote_rule` (`change_type='PROMOTED'`), each with whatever `superseded_by`/`reason` information is available for that row.

#### Scenario: A rule deprecated via promote_rule appears in the timeline
- **WHEN** a rule is deprecated by calling `promote_rule` and `get_rule_audit_log` is then called for its scope
- **THEN** the rule appears in the response's `deprecated_rules` list

#### Scenario: A rule deprecated via deprecate_rule appears with a structured replacement reference
- **WHEN** a rule is deprecated via `deprecate_rule` with `superseded_by="RN-090"`, and `get_rule_audit_log` is called for its scope
- **THEN** the rule appears in `deprecated_rules` with `superseded_by` equal to `"RN-090"`

### Requirement: Deprecated rules and lessons are removed from the semantic search index
When a rule or lesson becomes `deprecated` (via an approved `deprecate_rule` proposal or via `promote_rule`), the system SHALL remove its entry from the corresponding ChromaDB collection and clear its `embedding_id`, as a best-effort step that SHALL NOT cause the deprecation itself to fail if it errors.

#### Scenario: Embedding removed when a deprecate proposal is approved
- **WHEN** a `type="deprecate"` proposal for an already-embedded rule is approved
- **THEN** the rule's id no longer appears in `vector_store.search_rules` results, and its `embedding_id` is `NULL`

#### Scenario: Embedding removed when promote_rule deprecates a rule
- **WHEN** `promote_rule` is called on an already-embedded rule
- **THEN** the original rule's id no longer appears in `vector_store.search_rules` results, and its `embedding_id` is `NULL`

#### Scenario: A failure removing the embedding does not block the deprecation
- **WHEN** removing a rule's entry from the vector store raises an exception (e.g. the vector store is unavailable)
- **THEN** the deprecation still completes (`status='deprecated'`, `.md` marked, history recorded) and the failure is logged rather than raised

### Requirement: generate_embeddings purges embeddings left behind by earlier deprecations
`generate_embeddings` SHALL, in addition to embedding rows with a `NULL` `embedding_id`, remove the vector-store entry and clear `embedding_id` for any row where `status='deprecated'` and `embedding_id` is not `NULL`, and SHALL report the number of rows purged.

#### Scenario: Backfill purge of a pre-existing deprecated-but-embedded rule
- **WHEN** a rule has `status='deprecated'` and a non-`NULL` `embedding_id` (deprecated before this capability existed), and `generate_embeddings` is run
- **THEN** the rule's entry is removed from the vector store, its `embedding_id` becomes `NULL`, and the call's result includes it in a `purged` count

### Requirement: query_rules and query_lessons support an explicit toggle to include deprecated content
`query_rules` and `query_lessons` SHALL accept an `include_deprecated` parameter defaulting to `False`. When `False`, both the SQL-filtered path and the semantic (`query_text`) path SHALL exclude deprecated rules/lessons. When `True`, the SQL-filtered path SHALL include deprecated rows alongside active ones.

#### Scenario: Default call excludes deprecated rules from both query paths
- **WHEN** `query_rules(project_id=..., )` is called without `include_deprecated` (plain filter) and again with a `query_text` (semantic search), for a scope containing a deprecated rule
- **THEN** neither call's results include the deprecated rule

#### Scenario: include_deprecated=True surfaces deprecated rules via the SQL path
- **WHEN** `query_rules(project_id=..., include_deprecated=True)` is called (no `query_text`) for a scope containing a deprecated rule
- **THEN** the deprecated rule is included in the results

#### Scenario: include_deprecated=True does not revive entries already removed from the semantic index
- **WHEN** `query_rules(project_id=..., query_text=..., include_deprecated=True)` is called for a scope containing a rule deprecated after this capability shipped (and thus already removed from the vector store)
- **THEN** that rule is not returned by the semantic search path, and this is expected behavior, not an error — deprecated content in semantic search remains reachable only via `get_rule_context`/`get_rule_timeline`
