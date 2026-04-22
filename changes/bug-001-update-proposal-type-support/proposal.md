# Proposal: Bug #1 — Add UPDATE Proposal Type Support

## Intent

Fix Bug #1: `approve_proposal` fails with `"Unknown proposal type: UPDATE"` when trying to approve UPDATE proposals. UPDATE proposals are meant to modify existing rules/lessons, not create new ones. This requires schema changes, validation updates, and new approval logic.

## Scope

### In Scope
- Add `target_id` column to `pending_proposals` table (stores ID of rule/lesson being updated)
- Update `create_pending_proposal()` to accept and validate `"update"` as a valid type (require `target_id` when type="update")
- Extend `approve_proposal()` to handle UPDATE type with UPDATE SQL logic and atomic block replacement
- Add tests for the new functionality

### Out of Scope
- UI changes for selecting update targets (deferred to future enhancement)
- Bulk UPDATE operations
- Version history beyond basic change records

## Capabilities

### New Capabilities
- `update-proposal-type`: Support for updating existing rules/lessons via pending_proposals workflow

### Modified Capabilities
- `pending-proposal-workflow`: Extended to support UPDATE proposals with target_id tracking

## Approach

1. **Schema Migration**: Add `target_id TEXT` column to `pending_proposals` table via `ALTER TABLE`
2. **Validation** (`create_pending_proposal`): Accept type="update", require valid `target_id`, verify target exists
3. **Approval Logic** (`approve_proposal`):
   - Detect type="update" proposals
   - Fetch existing rule/lesson using target_id
   - Replace atomic block in .md file (not append)
   - Use UPDATE SQL instead of INSERT
   - Record change type in history table

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/meridian/db/schema.sql` | Modified | Add `target_id TEXT` column to pending_proposals |
| `src/meridian/tools/extraction.py` | Modified | Validate "update" type and target_id in `create_pending_proposal()` |
| `src/meridian/tools/knowledge_management.py` | Modified | Handle UPDATE type in `approve_proposal()` |
| `tests/integration/test_proposals_flow.py` | Modified | Add tests for UPDATE proposal workflow |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Data corruption if target_id is invalid | Medium | Validate target_id exists before approval |
| Atomic block replacement corrupts .md file | Low | Use transactional file write with backup copy |
| Race condition with concurrent approvals | Low | SQLite handles with proper locking |

## Rollback Plan

1. Revert schema: `ALTER TABLE pending_proposals DROP COLUMN target_id`
2. Revert code changes in extraction.py and knowledge_management.py
3. Restore .md files from backup if corruption occurred

## Dependencies

- SQLite ALTER TABLE support (available)
- Existing atomic block parsing in atomic_parser.py

## Success Criteria

- [ ] UPDATE proposals can be created via `create_pending_proposal(type="update", target_id="...")`
- [ ] `approve_proposal()` successfully updates existing rule/lesson
- [ ] Atomic block is replaced (not appended) in .md file
- [ ] History tables record UPDATE change type
- [ ] All new and existing tests pass