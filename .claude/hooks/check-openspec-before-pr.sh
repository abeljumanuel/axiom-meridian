#!/usr/bin/env bash
# PreToolUse hook (Bash, filtered to `gh pr create*` via settings.json's "if").
# Blocks opening a PR when src/ or tests/ changed but no openspec/changes/**
# entry is part of the same diff against the base branch.

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')

case "$command" in
  *"gh pr create"*) ;;
  *) exit 0 ;;
esac

base="main"
git fetch origin "$base" --quiet 2>/dev/null

changed=$(git diff --name-only "origin/${base}...HEAD" 2>/dev/null)
if [ -z "$changed" ]; then
  changed=$(git diff --name-only "${base}...HEAD" 2>/dev/null)
fi

code_changed=$(printf '%s\n' "$changed" | grep -E '^(src|tests)/' || true)
doc_changed=$(printf '%s\n' "$changed" | grep -E '^openspec/changes/' || true)

if [ -n "$code_changed" ] && [ -z "$doc_changed" ]; then
  reason="Code changed under src/ or tests/ but no openspec/changes/** entry is part of this diff. Create or update an openspec change (openspec new change <name>, or continue an existing one under openspec/changes/) documenting this change before opening the PR."
  jq -n --arg reason "$reason" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
fi

exit 0
