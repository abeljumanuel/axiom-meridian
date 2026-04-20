# Audit Report Format Guide

This directory contains audit reports generated from real-world testing sessions. To maximize their value and enable Meridian MCP to extract knowledge automatically, all reports must follow the format described below.

## Structure

```markdown
# Report Title

**Date:** YYYY-MM-DD
**Version:** x.y.z
**Type:** installation | functional | security | performance
**Complements:** (optional reference to related report)

---

## Executive Summary

2-3 paragraphs describing what was tested and the top-level findings.

---

## Issues

### ISSUE-NNN — Short Title

**Severity:** critical | high | medium | low
**Component:** file or module affected
**Symptom:** What the user saw
**Root Cause:** Why it happened
**Fix Applied:** What was done
**Fix Structural:** What should be done in the codebase

```

---

## Knowledge Extracted

The following blocks are in Meridian atomic format and can be indexed directly
via `index_rules_from_markdown` or `index_lessons_from_markdown`.

### Rules

## RN-XXX-NNN
**Scope:** project-meridian
**Categoría:** category
**Severidad:** critical|high|medium|low
**Aplica a:** glob pattern
**Tags:** comma, separated, tags
**Fuente:** report-name
**Regla:** Rule text in imperative form.

### Lessons

## LL-XXX-NNN
**Scope:** project-meridian
**Proyecto:** meridian
**Fecha:** YYYY-MM-DD
**Severidad del impacto:** critical|high|medium|low
**Área afectada:** area
**Tags:** comma, separated, tags
**Qué pasó:** Description of the incident.
**Impacto:** Business/technical impact.
**Causa raíz:** Root cause.
**Resolución:** How it was fixed.
**Originó regla:** RN-XXX-NNN
```

## Indexing a Report into Meridian

```bash
export KNOWLEDGE_BASE_PATH=~/meridian-kb
export MERIDIAN_ACCESS_LEVEL=write

# Index rules from the report
cd /path/to/meridian
uv run --python 3.11 python -m meridian index-rules \
  changes/report-name.md \
  --scope project-meridian

# Index lessons from the report
uv run --python 3.11 python -m meridian index-lessons \
  changes/report-name.md \
  --scope project-meridian
```

## Design Principles

1. **Atomic Knowledge:** Every issue must produce at least one rule or lesson in the "Knowledge Extracted" section.
2. **Traceability:** Every rule/lesson must reference its source report.
3. **Actionability:** Rules must be written in imperative form ("Do X", "Never Y"). Lessons must describe what happened, why, and how it was fixed.
4. **Machine-Readable:** The "Knowledge Extracted" section uses the exact Meridian atomic format so it can be parsed by `atomic_parser.py` without modification.
