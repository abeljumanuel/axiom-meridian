# Tasks: Bug #1 — Add UPDATE Proposal Type Support

## Phase 1: Schema Foundation

- [x] 1.1 Add `target_id TEXT` column to `pending_proposals` in `src/meridian/db/schema.sql` with FK constraint to `rules(id)`
- [x] 1.2 Add FK constraint for `lessons(id)` to `target_id` (or implement conditional FK)

## Phase 2: create_pending_proposal() Implementation

- [x] 2.1 In `src/meridian/tools/extraction.py`, add `type="update"` to accepted proposal types
- [x] 2.2 Add `target_id` parameter (required when type="update")
- [x] 2.3 Add `target_type` parameter (optional, inferred from target_id prefix)
- [x] 2.4 Implement prefix-based type inference: `RN-*` → rule, `LL-*` → lesson
- [x] 2.5 Validate target_id exists in rules OR lessons table
- [x] 2.6 Raise ValueError if target_id missing (type="update") or target doesn't exist

## Phase 3: approve_proposal() UPDATE Logic

- [x] 3.1 In `src/meridian/tools/knowledge_management.py`, detect `type="update"` proposals
- [x] 3.2 Fetch target rule/lesson using `target_id` from proposal
- [x] 3.3 Build new atomic block using `_build_rule_atomic_block` or `_build_lesson_atomic_block`
- [x] 3.4 Implement byte-level slice replacement: read file bytes, replace at `file_offset`, write back
- [x] 3.5 Use UPDATE SQL (not INSERT) to modify target row
- [x] 3.6 Record `change_type="UPDATED"` in history table with old/new text
- [x] 3.7 Wrap file write + DB update in SQLite transaction

## Phase 4: Testing

- [x] 4.1 Write `test_create_update_proposal` - valid UPDATE proposal created
- [x] 4.2 Write `test_create_update_proposal_missing_target_id` - raises ValueError when target_id missing
- [x] 4.3 Write `test_create_update_proposal_invalid_target` - raises ValueError for nonexistent target
- [x] 4.4 Write `test_approve_update_proposal` - file replaced, history recorded
- [x] 4.5 Write `test_update_lesson_proposal` - lesson UPDATE flow works
- [x] 4.6 Write `test_update_proposal_history` - history contains `change_type="UPDATED"`

## Phase 5: Integration Verification

- [x] 5.1 Run full integration test in `tests/integration/test_proposals_flow.py`
- [x] 5.2 Verify backward compatibility - existing rule/lesson proposals work unchanged