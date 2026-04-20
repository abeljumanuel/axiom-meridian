# ADR-001: Response Serialization Format for MCP Tool Outputs

**Status:** Accepted  
**Date:** 2026-04-11  
**Product:** Axiom Meridian  
**Author:** Axiom JUMA  
**Deciders:** abeljuanmanuel  

---

## Context

Meridian exposes knowledge (rules, lessons) as structured data through MCP tools consumed primarily by LLMs (Claude Code, Claude Desktop). Every token in a tool response has a cost — both economic and contextual. The serialization format of those responses directly determines how efficiently an LLM can consume the knowledge Meridian provides.

The two tools most affected are `query_rules()` and `query_lessons()`. Both return arrays of uniform objects — each element shares the same set of fields (`code`, `text`, `severity`, `category`, `scope_id`, `tags`, `source_ref`, `applies_to`). This structural uniformity is a design property of Meridian's atomic format, not an accident.

The question is: what format should these uniform arrays take when delivered to an LLM consumer?

### Formats evaluated

| Format | Token cost (relative) | LLM comprehension | Structural contract |
|---|---|---|---|
| JSON pretty | Highest | High | Implicit |
| JSON compact | Medium-high | High | Implicit |
| YAML | Medium | High | Implicit |
| **TOON** | **Lowest (−40% vs JSON)** | **Higher than JSON** | **Explicit via `[N]{fields}` header** |

TOON (Token-Oriented Object Notation — [github.com/toon-format/toon](https://github.com/toon-format/toon)) is a compact, lossless encoding of the JSON data model. It combines YAML-style indentation for nested objects with CSV-style tabular layout for uniform arrays. Its benchmarks report 76.4% LLM comprehension accuracy vs 75.0% for JSON, using 39.9% fewer tokens on mixed-structure datasets.

TOON's `[N]{fields}` header is particularly relevant for Meridian: it gives the consuming LLM an explicit count and field contract before reading row data, which aligns with how Meridian's atomic rule format already declares its structure.

### Structural fit analysis

Meridian's rule objects are maximally uniform — every rule in a scope resolution result has identical fields. This is TOON's optimal case (100% tabular eligibility). The risk TOON documents for semi-uniform or deeply nested data does not apply here.

The two tools where TOON is most impactful:

**`query_rules(project_id, category?, severity?, tags?)`** — returns N rules after scope hierarchy resolution. A typical response for a project audit might contain 15-30 rules. In JSON, each rule repeats its field names. In TOON, field names appear once in the header.

**`query_lessons(project_id, area?, tags?)`** — same structural pattern as rules. Same token efficiency argument applies.

`extract_rules_from_transcript()` and `analyze_pr_feedback()` also pass rule context to the client LLM. TOON would reduce the token cost of that context payload as well.

---

## Decision

### V1 — JSON as default, TOON as opt-in parameter

`query_rules()` and `query_lessons()` accept an optional `format` parameter:

```python
def query_rules(
    project_id: str,
    category: str | None = None,
    severity: str | None = None,
    tags: list[str] | None = None,
    format: Literal["json", "toon"] = "json"   # ← new parameter
) -> str:
    ...
```

**Default is `"json"` in V1.** Rationale: V1 must be stable and predictable. TOON is an emerging format. Keeping JSON as default avoids introducing a parsing risk in the first iteration when the priority is correctness of scope resolution and positional file reading.

**`"toon"` is available in V1 as an explicit opt-in.** Any consumer that knows it wants token efficiency can pass `format="toon"`. The serialization logic is isolated in a single helper function — the scope resolution, SQLite queries, and positional file reads are format-agnostic.

### Implementation constraint

TOON encoding is implemented as a standalone utility:

```
meridian/
└── utils/
    └── serializers.py   ← toon_encode(records, fields) + json_encode(records)
```

No TOON-specific logic leaks into the tool handlers or the SQLite layer. The tools call `serialize(records, format)` as their final step.

### What does not change in V1

- Schema SQLite: no changes. Format is a response concern, not a storage concern.
- Markdown source of truth: unchanged.
- `file_offset` / `byte_length` positional reads: unchanged.
- All other tools (`audit_pr`, `analyze_pr_feedback`, `check_feature_against_rules`, etc.): return plain text or JSON. TOON is only relevant for structured array outputs.

---

## Reference: Evolution Intent

> This section documents the intended evolution of the serialization format. The core decision (JSON default, TOON opt-in) stands unchanged.

When Meridian's usage patterns are understood, the expectation is:

**`format` default changes to `"toon"` for LLM-targeted tools.** Claude Code and OpenCode are the primary consumers of `query_rules()` and `query_lessons()`. Once TOON parsing reliability is validated in practice, the default flips. This is a one-line change in the function signature.

**Context payloads in audit tools use TOON.** `audit_pr()`, `analyze_pr_feedback()`, and `check_feature_against_rules()` pass rule context to the client LLM. Serializing this context as TOON reduces token cost without changing tool signatures.

**RAG and TOON are parallel mechanisms.** Both optimize token efficiency at different layers — TOON at serialization, RAG at retrieval. Both are included in V1. Neither blocks the other.

The external contract of `query_rules()` does not change regardless of which format or retrieval mode is active.

---

## Consequences

### Positive

- Zero coupling: serialization is isolated in `utils/serializers.py`. Changing the default in V2 requires no changes to tool logic, schema, or parsers.
- The `format` parameter is forward-compatible: consumers can adopt TOON incrementally.
- TOON's `[N]{fields}` header gives LLM consumers an explicit count of rules returned — useful for audit reporting ("7 rules evaluated, 2 violated").
- Aligns with Meridian's principle 6: tool signatures are stable across internal mechanism changes.

### Negative / Trade-offs

- JSON default means token efficiency gains from TOON are opt-in. Accepted — correctness and broad client compatibility take priority.
- TOON has no official Python SDK as of April 2026 (the reference implementation is TypeScript). `toon_encode()` must be implemented manually. However, the encoding algorithm for uniform arrays is simple enough to implement in ~30 lines of Python without external dependencies.
- TOON adds a new format to the system that operators must understand. Mitigated by making it opt-in and documenting it in the README.

---

## Alternatives considered

**Always JSON** — rejected. Leaves a known token efficiency gap unaddressed with no migration path.

**Always TOON** — rejected for V1. Introduces parsing risk before the system is validated in production. The format is stable but the Python ecosystem support is immature.

**YAML** — rejected. Saves some tokens over JSON but less than TOON. Adds no structural contract (no `[N]` count or `{fields}` header). No measurable LLM comprehension advantage over JSON for uniform arrays.

---

## Related decisions

- ADR-002: Dynamic Context Attributes — `query_rules()` pipeline, attribute filtering step.
- `rule_version_snapshot` in `pr_audits` — audit integrity across rule changes (implemented in PRD v1.1).
- `get_rule_audit_log()` tool — transversal audit of deprecated and modified rules (implemented in PRD v1.1).
- RAG search via ChromaDB — parallel retrieval mechanism, included in V1 (PRD v1.1 §9).
