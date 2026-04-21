# Skill Registry — axiom-meridian

Generated: 2026-04-20
Project: axiom-meridian

## User Skills Trigger Table

| Trigger Context | Skill Name | Location |
|-----------------|------------|----------|
| Creating a pull request / opening a PR | branch-pr | ~/.claude/skills/branch-pr/SKILL.md |
| Writing Go tests, teatest, Bubbletea TUI | go-testing | ~/.claude/skills/go-testing/SKILL.md |
| Creating a GitHub issue / reporting a bug | issue-creation | ~/.claude/skills/issue-creation/SKILL.md |
| "judgment day", adversarial review, "dual review", "juzgar" | judgment-day | ~/.claude/skills/judgment-day/SKILL.md |
| Creating a new AI skill / documenting patterns | skill-creator | ~/.claude/skills/skill-creator/SKILL.md |

## Project Conventions

No project-level CLAUDE.md or agent config found in project root.
Global CLAUDE.md applies (conventional commits, no AI attribution, strict TDD mode).

## Compact Rules

### branch-pr
- Every PR MUST link an issue with `status:approved` label — no exceptions
- Every PR MUST have exactly one `type:*` label
- Branch naming: `type/description` — regex `^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)\/[a-z0-9._-]+$`
- Conventional commits only — no Co-Authored-By or AI attribution in commits
- Automated checks must pass before merge
- Never push directly to main

### go-testing
- Table-driven tests: `tests := []struct{name string; ...}{}` with `t.Run(tt.name, ...)`
- Use `t.Helper()` in assertion helpers
- Golden file tests for snapshot/output testing: write expected to `testdata/*.golden`, compare with `-update` flag
- teatest for Bubbletea TUI: use `teatest.NewTestModel`, send `tea.KeyMsg` events, assert final view
- Use `t.Parallel()` for independent test cases

### issue-creation
- MUST use bug report or feature request template — blank issues are disabled
- Issues auto-get `status:needs-review`; maintainer must add `status:approved` before a PR can open
- Questions go to Discussions, not issues
- Search for duplicates before filing
- Only open a PR after the linked issue has `status:approved`

### judgment-day
- Launch TWO independent blind judge sub-agents in parallel via `delegate` (async, NOT sequential)
- Neither agent knows about the other — no cross-contamination
- Orchestrator synthesizes: Confirmed (both found) → fix immediately; Suspect A/B (one found) → triage; Contradiction (disagree) → flag for manual decision
- Inject skill registry compact rules into BOTH judge prompts and the fix agent prompt
- Re-judge after fixes — escalate if not resolved after 2 iterations
- Orchestrator NEVER reviews code itself — coordinate only

### skill-creator
- Skill lives at `skills/{skill-name}/SKILL.md` (or `~/.claude/skills/{name}/SKILL.md` for global)
- Required frontmatter: `name`, `description` (include `Trigger:` line), `license`, `metadata.author`, `metadata.version`
- Required sections: When to Use, Critical Patterns, Rules
- Compact rules format: 5-15 actionable lines — no motivation, no full examples, no installation steps
- Don't create for trivial or one-off tasks
