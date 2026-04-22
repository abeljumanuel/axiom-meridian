# Delta Spec: Bug #1 — Add UPDATE Proposal Type Support

## Summary

Support UPDATE proposal type to modify existing rules/lessons via the pending_proposals workflow. UPDATE proposals replace atomic blocks in .md files instead of appending new ones.

---

## ADDED Requirements

### Requirement: UPDATE Proposal Creation

`create_pending_proposal()` MUST accept `type="update"` when `target_id` references an existing rule or lesson. The system SHALL validate target existence before persisting the proposal.

#### Scenario: Valid UPDATE Rule Proposal

- GIVEN an existing rule with code `RN-001-001` in scope `global-java`
- WHEN a client calls `create_pending_proposal(type="update", target_id="RN-001-001", ...)`
- THEN the proposal is persisted with `status="pending"` and `target_id="RN-001-001"`

#### Scenario: UPDATE Proposal Rejects Invalid Target

- GIVEN no rule or lesson with ID `NONEXISTENT-001`
- WHEN a client calls `create_pending_proposal(type="update", target_id="NONEXISTENT-001", ...)`
- THEN a `ValueError` is raised indicating the target does not exist

#### Scenario: UPDATE Proposal Rejects Missing target_id

- GIVEN a valid scope `global-java`
- WHEN a client calls `create_pending_proposal(type="update", suggested_scope_id="global-java", ...)` without `target_id`
- THEN a `ValueError` is raised indicating `target_id` is required for UPDATE proposals

---

### Requirement: UPDATE Proposal Approval

`approve_proposal()` MUST replace the existing atomic block in the target .md file when processing an UPDATE proposal. The system SHALL use UPDATE SQL and record `"UPDATED"` in history tables.

#### Scenario: Approve UPDATE Rule Proposal

- GIVEN a pending UPDATE proposal with `target_id="RN-001-001"`
- WHEN `approve_proposal(proposal_id)` is called
- THEN the existing rule is updated via UPDATE SQL (not INSERT)
- AND the .md file atomic block is replaced (not appended)
- AND `rule_history` records `change_type="UPDATED"`

#### Scenario: Approve UPDATE Lesson Proposal

- GIVEN a pending UPDATE proposal with `type="update"`, `target_id="LL-001-001"`, `target_type="lesson"`
- WHEN `approve_proposal(proposal_id)` is called
- THEN the existing lesson is updated via UPDATE SQL
- AND the .md file atomic block is replaced
- AND `lesson_history` records `change_type="UPDATED"`

---

## MODIFIED Requirements

### Requirement: `create_pending_proposal()` Function Signature

(Full replacement of existing requirement)

The function MUST accept three proposal types: `"rule"`, `"lesson"`, and `"update"`. For `"update"` type, `target_id` MUST be provided and MUST reference an existing rule or lesson.

#### Scenario: Existing Rule and Lesson Creation (unchanged)

- GIVEN valid scope `global-java` and `type="rule"`
- WHEN `create_pending_proposal(type="rule", ...)` is called
- THEN the proposal is created with type `"rule"` (no change)

#### Scenario: Existing Lesson Creation (unchanged)

- GIVEN valid scope `global-java` and `type="lesson"`
- WHEN `create_pending_proposal(type="lesson", ...)` is called
- THEN the proposal is created with type `"lesson"` (no change)

(Previously: Only accepted "rule" and "lesson" types)

---

### Requirement: `approve_proposal()` Type Handling

(Full replacement of existing requirement)

The function MUST handle three proposal types: `"rule"`, `"lesson"`, and `"update"`. For `"update"` type, the function MUST fetch the target using `target_id`, replace its atomic block in the .md file, and use UPDATE SQL.

#### Scenario: Approve RULE Proposal (unchanged)

- GIVEN a pending proposal with `type="rule"`
- WHEN `approve_proposal(proposal_id)` is called
- THEN the atomic block is appended to the .md file (no change)

#### Scenario: Approve LESSON Proposal (unchanged)

- GIVEN a pending proposal with `type="lesson"`
- WHEN `approve_proposal(proposal_id)` is called
- THEN the atomic block is appended to the .md file (no change)

#### Scenario: Approve UPDATE Proposal (new)

- GIVEN a pending proposal with `type="update"` and `target_id`
- WHEN `approve_proposal(proposal_id)` is called
- THEN the atomic block at the target's `file_offset` is replaced
- AND the database row is updated (not inserted)

(Previously: Only handled "rule" and "lesson" types; raised `ValueError` for UPDATE)

---

## NON-FUNCTIONAL REQUIREMENTS

| Aspect | Requirement |
|--------|------------|
| **Performance** | UPDATE approval completes in < 100ms for typical atomic blocks (< 4KB) |
| **Backward Compatibility** | Existing `"rule"` and `"lesson"` proposals behave identically; no breaking changes |
| **Atomicity** | File write + DB update occur within a single transaction |
| **Rollback** | Failed approval leaves proposal in `pending` status (not `approved`) |

---

## DATABASE SCHEMA CHANGES

```sql
-- Add target_id column to pending_proposals
ALTER TABLE pending_proposals ADD COLUMN target_id TEXT REFERENCES rules(id);

-- No other schema changes required
```

**Rationale**: `target_id` stores the ID of the rule/lesson being updated. FK constraint ensures referential integrity.

---

## EDGE CASES

| Scenario | Expected Behavior |
|----------|------------------|
| `target_id` references a deprecated rule | Allow UPDATE; deprecated status preserved |
| Target .md file missing | Raise `FileNotFoundError`; proposal remains pending |
| Target has no `file_path`/`file_offset` | Raise `ValueError` with descriptive message |
| Concurrent UPDATE to same target | SQLite WAL mode handles locking; last write wins |
| UPDATE proposal with empty `proposed_text` | Allow; atomic block replaces with empty content |
| `target_type` not specified | Infer from target_id prefix (`RN-` = rule, `LL-` = lesson) |

---

## API / FUNCTION SIGNATURE CHANGES

### `create_pending_proposal()`

```python
def create_pending_proposal(
    conn: sqlite3.Connection,
    type: str,           # Now accepts: "rule" | "lesson" | "update"
    proposed_text: str,
    suggested_scope_id: str,
    target_id: str | None = None,  # NEW: Required when type="update"
    target_type: str | None = None,  # NEW: "rule" or "lesson" (optional, inferred)
    suggested_attributes: list[dict[str, str]] | None = None,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> str:
```

**Validation Rules**:
1. If `type="update"`, `target_id` MUST NOT be None
2. If `target_id` is provided, it MUST exist in `rules` OR `lessons`
3. If `target_type` is provided, it MUST match the target's actual type

### `approve_proposal()`

**Internal Changes** (no signature change):
- Detect `type="update"` proposals
- Fetch target using `target_id` (not `scope_id` for file path)
- Replace atomic block at existing `file_offset` (not append)
- Use `UPDATE` SQL (not `INSERT`)
- Record `change_type="UPDATED"` in history

---

## TEST COVERAGE

| Scenario | Test Location |
|----------|-------------|
| Valid UPDATE rule proposal | `test_proposals_flow.py::test_create_update_proposal` |
| UPDATE proposal rejects invalid target | `test_proposals_flow.py::test_create_update_proposal_invalid_target` |
| UPDATE proposal rejects missing target_id | `test_proposals_flow.py::test_create_update_proposal_missing_target_id` |
| Approve UPDATE rule proposal | `test_proposals_flow.py::test_approve_update_proposal` |
| Approve UPDATE lesson proposal | `test_proposals_flow.py::test_approve_update_lesson_proposal` |
| History records UPDATED | `test_proposals_flow.py::test_update_proposal_history` |