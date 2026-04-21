# ADR-002: Dynamic Context Attributes for Scopes and Rules

**Status:** Accepted  
**Date:** 2026-04-11  
**Product:** Axiom Meridian  
**Author:** Axiom JUMA  
**Deciders:** abeljuanmanuel  
**Supersedes:** Proposed static `framework` / `component_role` columns (never implemented)

---

## Context

During scaffolding design, the initial proposal was to add fixed columns to `scopes` and `rules` to capture framework-level and architectural context:

```sql
-- Proposed (rejected)
scopes(
  ...,
  framework,       -- "quarkus" | "spring-boot" | "nestjs" | "go-fiber"
  component_role   -- "gateway" | "last-mile" | "middleware"
)
```

This approach was challenged on the grounds that a team's technology stack is not static. A project that runs Quarkus today may migrate to Spring Boot tomorrow. A new architectural pattern — Temporal workflows, event sourcing processors, AI inference workers — may emerge that was never anticipated at design time. Fixed columns require `ALTER TABLE` to accommodate change, which violates the spirit of a system designed to evolve alongside the team's knowledge.

### Core requirement

Meridian must be capable of understanding:

- **Framework/runtime context:** Quarkus vs Spring Boot vs NestJS vs Go Fiber vs Go Gin — so that rules specific to one framework are not applied to another.
- **Architectural component role:** API Gateway, last-mile connection, middleware, internal worker, scheduler, event processor — so that rules relevant to a gateway (e.g. auth, rate limiting, routing) are not surfaced for a background worker.
- **Any future context dimension** that is not yet known at the time of this writing.

The system must accommodate all of these without schema changes.

---

## Decision

Replace proposed fixed columns with two dynamic attribute tables — one for scopes, one for rules.

### Schema

```sql
-- Dynamic attributes for scopes
scope_attributes (
  scope_id   TEXT NOT NULL REFERENCES scopes(id) ON DELETE CASCADE,
  key        TEXT NOT NULL,   -- e.g. "framework", "component_role", "runtime_version"
  value      TEXT NOT NULL,   -- e.g. "quarkus", "gateway", "java-21"
  PRIMARY KEY (scope_id, key)
)

-- Dynamic attributes for rules
rule_attributes (
  rule_id    TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  key        TEXT NOT NULL,   -- e.g. "framework", "component_role"
  value      TEXT NOT NULL,   -- e.g. "spring-boot", "last-mile"
  PRIMARY KEY (rule_id, key)
)

-- Indexes for query performance
CREATE INDEX idx_scope_attributes_key_value ON scope_attributes(key, value);
CREATE INDEX idx_rule_attributes_key_value  ON rule_attributes(key, value);
```

### Semantics

**A rule with no `rule_attributes` entries applies to all contexts.** This is the default and the common case — most rules are framework-agnostic.

**A rule with one or more `rule_attributes` entries applies only when the target scope has matching attributes.** A rule with `framework = quarkus` is only surfaced when the resolved scope has `framework = quarkus` in its `scope_attributes`.

**Multi-attribute rules use AND logic.** A rule with both `framework = quarkus` and `component_role = gateway` only applies to scopes that satisfy both conditions.

### Initial attribute vocabulary (non-exhaustive)

The following keys are the starting vocabulary. New keys can be added at any time without schema changes.

| Key | Example values | Dimension |
|---|---|---|
| `framework` | `quarkus`, `spring-boot`, `nestjs`, `go-fiber`, `go-gin`, `flutter` | Runtime/framework |
| `component_role` | `gateway`, `last-mile`, `middleware`, `worker`, `scheduler`, `event-processor` | Architectural role |
| `runtime_version` | `java-21`, `node-20`, `go-1.22`, `dart-3` | Runtime version |
| `team` | `payments`, `onboarding`, `platform` | Organizational |
| `deployment_target` | `cloud`, `on-premise`, `edge` | Infrastructure |

This vocabulary lives in documentation only — the schema enforces no constraint on key names.

### Scope hierarchy — extended example

```
GLOBAL
├── global                          (no attributes)
├── global-java                     framework: java
│   ├── global-quarkus              framework: quarkus
│   └── global-spring-boot          framework: spring-boot
├── global-nestjs                   framework: nestjs
└── global-go                       framework: go
    ├── global-go-fiber             framework: go-fiber
    └── global-go-gin               framework: go-gin

PROJECT
├── project-example                  framework: quarkus
│                                   component_role: gateway
│                                   runtime_version: java-21
├── other-project-example                      framework: nestjs
│                                   component_role: last-mile
└── ledger                          framework: flutter
                                    component_role: mobile-client
```

### Impact on `query_rules()`

The scope resolution pipeline gains one additional step:

```
1. Resolve scope hierarchy for project_id
   → [project, global-quarkus, global-java, global]

2. Load scope_attributes for the project scope
   → {framework: "quarkus", component_role: "gateway"}

3. For each candidate rule:
   a. If rule has no rule_attributes → INCLUDE (applies to all)
   b. If rule has rule_attributes → INCLUDE only if all attributes
      match the project's scope_attributes
      (unrecognized keys in rule_attributes → conservative INCLUDE)

4. Serialize and return (format: json | toon per ADR-001)
```

Step 3b uses conservative inclusion for unknown keys — if Meridian encounters a `rule_attribute` key it hasn't seen before, it includes the rule rather than silently dropping it. This prevents knowledge loss from vocabulary drift.

### Impact on `extract_rules_from_transcript()`

When the LLM analyzes a transcript and proposes a new rule, the `pending_proposals` payload includes a suggested `rule_attributes` array:

```json
{
  "type": "rule",
  "scope_id": "global-quarkus",
  "proposed_text": "...",
  "suggested_attributes": [
    { "key": "framework", "value": "quarkus" },
    { "key": "component_role", "value": "gateway" }
  ],
  "source_type": "transcript",
  "source_ref": "tech-review-2026-03-15"
}
```

The user reviews and adjusts `suggested_attributes` before approving via `approve_proposal()`. Meridian never writes attributes without explicit approval — consistent with Principle 2 of the spec.

### Impact on `pending_proposals` schema

```sql
pending_proposals (
  id, type, scope_id, proposed_text, metadata,
  source_type, source_ref, status, reason, created_at,
  suggested_attributes  -- JSON array of {key, value} pairs (nullable)
)
```

---

## Lifecycle: updating attributes when the stack changes

When a project migrates frameworks (e.g. Quarkus → Spring Boot):

```sql
-- Update the scope attribute — no ALTER TABLE, no data loss
UPDATE scope_attributes
SET value = 'spring-boot'
WHERE scope_id = 'project-example' AND key = 'framework';
```

Rules previously scoped to `framework = quarkus` will no longer match `project-example` — they will not be surfaced in `query_rules()`. Rules scoped to `framework = spring-boot` will now be surfaced. Rules with no `rule_attributes` continue to apply regardless.

The `rule_history` table captures when rules are added, modified, or deprecated as a consequence of a migration, preserving the audit trail of why certain rules stopped applying.

---

## Consequences

### Positive

- Stack migrations require a single `UPDATE` on `scope_attributes`. No schema changes.
- New context dimensions (new frameworks, new architectural patterns, organizational attributes) require only `INSERT` on `scope_attributes` or `rule_attributes`. No schema changes.
- The attribute model is self-documenting in the data — `list(scope_attributes)` for a project gives a complete picture of its context.
- Conservative inclusion on unknown keys prevents silent knowledge loss.
- Aligns with Meridian's Principle 4 (scope resolution before every query) — attributes are resolved as part of that step.

### Negative / Trade-offs

- `query_rules()` is slightly more complex — it now joins `scope_attributes` and `rule_attributes` as part of filtering. Mitigated by indexes on `(key, value)`.
- Free-form keys mean vocabulary can diverge across projects if not governed. Mitigated by maintaining the vocabulary table in documentation and surfacing it in the README.
- Multi-attribute AND logic may over-filter in edge cases (a rule requiring `framework=quarkus` AND `component_role=gateway` won't apply to a quarkus worker). This is intentional — specificity is explicit.

---

## Alternatives considered

**Fixed enum columns (`framework TEXT CHECK IN (...)`)** — rejected. Requires schema migration for every new framework or role. Couples the schema to a specific moment in time.

**JSON blob in `scopes.metadata`** — rejected. Not queryable efficiently without parsing. Loses the ability to index on `(key, value)` pairs. Makes `query_rules()` filtering require full table scans or application-level logic.

**No attribute filtering (rely on scope hierarchy only)** — rejected. Scope hierarchy captures technology lineage but not architectural role. A `global-quarkus` scope cannot distinguish a Gateway rule from a Worker rule without an additional dimension.

---

## Related decisions

- ADR-001: Response Serialization Format — `query_rules()` pipeline, serialization step.
- `rule_version_snapshot` in `pr_audits` (pending ADR) — audit integrity across rule and attribute changes.
- `get_rule_audit_log()` tool (pending ADR) — transversal audit including attribute-filtered deprecations.
- Testing strategy (pending ADR) — scope resolver tests must cover attribute filtering logic.
