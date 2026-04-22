# Design: Bug #1 — Add UPDATE Proposal Type Support

## Technical Approach

Extend the pending_proposals workflow to handle UPDATE proposals that replace existing rules/lessons. The flow follows the existing pattern: `create_pending_proposal()` validates → `approve_proposal()` executes. UPDATE proposals replace the atomic block in the .md file rather than appending, using UPDATE SQL rather than INSERT, and record `"UPDATED"` in history.

## Architecture Decisions

### Decision: Schema Extension for target_id

**Choice**: Add `target_id TEXT` column to `pending_proposals` table with FK constraints to `rules(id)` and `lessons(id)`
**Alternatives considered**: 
- Separate `rule_update_proposals` and `lesson_update_proposals` tables (rejected — over-normalizes a single use case)
- Store as JSON `{type, id}` (rejected — harder to query, FK integrity lost)
**Rationale**: Single column keeps UPDATE proposals in same table. FK constraint ensures invalid targets are rejected at insertion time.

### Decision: target_type Inference

**Choice**: Infer `target_type` from `target_id` prefix: `RN-*` → rule, `LL-*` → lesson
**Alternatives considered**: 
- Require explicit `target_type` parameter (rejected — redundancy, error-prone)
- Query rules/lessons tables to determine type (rejected — extra query, prefix is authoritative)
**Rationale**: Code prefix convention is already established. `_scope_to_file_path()` uses same pattern.

### Decision: Atomic Block Replacement

**Choice**: Use byte-level slice replacement (same technique as `_mark_deprecated_in_md()`)
**Alternatives considered**: 
- Full file rewrite (rejected — lossy for concurrent edits)
- Temporary file + rename (rejected — complexity without benefit for single block)
**Rationale**: In-place replacement preserves file offsets for other blocks. SQLite WAL handles concurrent access.

### Decision: File/DB Atomicity

**Choice**: SQLite transaction wraps file write + DB update
**Alternatives considered**: 
- Best-effort rollback on failure (rejected — partial state possible)
- Separate file and DB transactions (rejected — can diverge)
**Rationale**: SQLite transactions are ACID. File write is part of the same logical operation.

## Data Flow

```
Client
  │
  ▼
create_pending_proposal(type="update", target_id="RN-001-001")
  │
  ├─ Validate target_id exists in rules (or lessons)
  ├─ Validate scope from target's scope_id
  └─ Insert into pending_proposals(target_id, type="update")
        │
        ▼
Client approves via approve_proposal(proposal_id)
  │
  ├─ Fetch proposal and target rule/lesson
  ├─ Read existing .md file bytes
  ├─ Build new atomic block
  ├─ BEGIN TRANSACTION
  │   ├─ Replace bytes at target.file_offset
  │   ├─ UPDATE rules SET ... WHERE id=target_id
  │   └─ INSERT INTO rule_history(change_type="UPDATED", ...)
  ├─ UPDATE pending_proposals SET status="approved"
  └─ COMMIT
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/meridian/db/schema.sql` | Modify | Add `target_id TEXT` column to `pending_proposals` |
| `src/meridian/tools/extraction.py` | Modify | Accept `type="update"`, validate `target_id`, infer `target_type` |
| `src/meridian/tools/knowledge_management.py` | Modify | Handle `type="update"` in `approve_proposal()`: fetch target, replace block, UPDATE SQL, record history |
| `tests/integration/test_proposals_flow.py` | Modify | Add UPDATE proposal tests |

## Implementation Details

### extraction.py: `create_pending_proposal()` changes

```python
def create_pending_proposal(
    conn: sqlite3.Connection,
    type: str,                          # Now accepts: "rule" | "lesson" | "update"
    proposed_text: str,
    suggested_scope_id: str,
    target_id: str | None = None,        # NEW: required when type="update"
    target_type: str | None = None,      # NEW: inferred from target_id prefix
    suggested_attributes: list | None = None,
    source_type: str | None = None,
    source_ref: str | None = None,
) -> str:
    # Validation for UPDATE type
    if type == "update":
        if target_id is None:
            raise ValueError("target_id is required for UPDATE proposals")
        # Infer target_type from ID prefix
        if target_id.startswith("RN-"):
            target_type = "rule"
            table, pk = "rules", target_id
        elif target_id.startswith("LL-"):
            target_type = "lesson"
            table, pk = "lessons", target_id
        else:
            raise ValueError(f"Invalid target_id format: {target_id}")
        # Verify target exists
        cursor = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (pk,))
        if cursor.fetchone() is None:
            raise ValueError(f"Target '{target_id}' does not exist")
    # ... existing validation for scope ...
    # ... INSERT with target_id column ...
```

### knowledge_management.py: `approve_proposal()` changes

```python
def approve_proposal(proposal_id: str) -> dict:
    # ... existing proposal fetch and validation ...
    
    prop_type = proposal["type"]
    
    if prop_type == "update":
        target_id = proposal["target_id"]
        # Determine target table and type
        if target_id.startswith("RN-"):
            target_table = "rules"
            hist_table = "rule_history"
            block_builder = _build_rule_atomic_block
        else:
            target_table = "lessons"
            hist_table = "lesson_history"
            block_builder = _build_lesson_atomic_block
        
        # Fetch target using target_id
        cursor = conn.execute(f"SELECT * FROM {target_table} WHERE id = ?", (target_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Target '{target_id}' not found")
        columns = [d[0] for d in cursor.description]
        target = dict(zip(columns, row))
        
        # Get file path and offset from target
        scope_id = target["scope_id"]
        dest_path = Path(target["file_path"])
        old_offset = target["file_offset"]
        old_length = target["byte_length"]
        
        # Read existing block bytes
        raw_bytes = dest_path.read_bytes()
        old_block_bytes = raw_bytes[old_offset : old_offset + old_length]
        
        # Build new block text
        block_text = block_builder(target_id, scope_id, proposed_text, metadata)
        new_block_bytes = block_text.encode("utf-8")
        new_length = len(new_block_bytes)
        
        # Atomic file replacement
        new_bytes = raw_bytes[:old_offset] + new_block_bytes + raw_bytes[old_offset + old_length:]
        dest_path.write_bytes(new_bytes)
        
        # Transaction: UPDATE target + record history
        conn.execute(f"""
            UPDATE {target_table}
            SET text = ?, ... , file_offset = ?, byte_length = ?
            WHERE id = ?
        """, (...))
        
        hist_id = next_sequential_id(conn, hist_table, "rh")
        conn.execute(f"""
            INSERT INTO {hist_table} (id, rule_id/lesson_id, change_type, previous_text, new_text)
            VALUES (?, ?, 'UPDATED', ?, ?)
        """, (hist_id, target_id, old_block_bytes.decode(), proposed_text))
    else:
        # ... existing rule/lesson logic (append, INSERT) ...
```

## Interfaces / Contracts

### New function signature

| Parameter | Type | Required for UPDATE | Description |
|-----------|------|---------------------|-------------|
| `target_id` | `str \| None` | Yes | ID of rule/lesson to update |
| `target_type` | `str \| None` | No | Inferred from `target_id` prefix |

### Return value (unchanged)

```python
{
    "proposal_id": str,
    "code": str,           # For UPDATE: same as target_id
    "scope_id": str,
    "file_path": str,
    "file_offset": int,
    "byte_length": int,
}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `create_pending_proposal` UPDATE validation | Direct call with valid/invalid target_id |
| Unit | `approve_proposal` UPDATE flow | Mock file I/O, verify file bytes replaced |
| Integration | Full UPDATE workflow | Test with real DB + temp .md file |

**Key test cases**:
- `test_create_update_proposal` — valid UPDATE proposal created
- `test_create_update_proposal_invalid_target` — raises ValueError
- `test_create_update_proposal_missing_target_id` — raises ValueError  
- `test_approve_update_proposal` — file replaced, history recorded
- `test_update_proposal_history` — history contains `change_type="UPDATED"`

## Migration / Rollback

**Migration**: 
- Run `ALTER TABLE pending_proposals ADD COLUMN target_id TEXT REFERENCES rules(id)` (or allow NULL with separate FK tracking)
- No data migration needed (existing proposals have `target_id=NULL`)

**Rollback**:
1. Revert schema: `ALTER TABLE pending_proposals DROP COLUMN target_id`
2. Revert code changes
3. Restore .md files from backup if corrupted

## Open Questions

- [ ] Should `target_id` FK be to both `rules` and `lessons`, or just one table per `target_type`?
- [ ] Handle deprecated targets: allow UPDATE or reject? (Spec says allow — preserve deprecated status)
- [ ] What if target's `file_path`/`file_offset` is NULL? Require target to have been indexed before update.