# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Axiom Meridian is an MCP (Model Context Protocol) server that indexes institutional knowledge — technical rules (`RN-*`) and lessons learned (`LL-*`) — stored in Markdown files, and serves only the slices relevant to a project. **Markdown files are the single source of truth; SQLite is only an index/state layer.** Never invert that relationship: tools must not generate knowledge content that doesn't trace back to a `.md` file.

## Commands

```bash
uv sync --extra dev                      # install deps (Python 3.11+, uv required)
uv run pytest                            # run all tests
uv run pytest tests/unit                 # unit tests only
uv run pytest tests/integration/test_proposals_flow.py::test_name   # single test
uv run ruff check src tests             # lint (line-length 100, py311)
```

Running the server / CLI (entry point is `python -m meridian`):

```bash
uv run python -m meridian mcp            # MCP server over stdio
uv run python -m meridian serve 8080     # HTTP/SSE transport (prints a session token)
uv run python -m meridian db init        # initialize SQLite schema
uv run python -m meridian query rules --project <id>
uv run python -m meridian proposals list --status pending
uv run python -m meridian migrate rules <file.md> --scope <scope_id>
```

`scripts/install.sh` / `scripts/uninstall.sh` handle end-user installation and MCP client registration. The README warns against configuring MCP clients with `uv run` (PATH issues) — use the venv Python path directly.

## Environment variables

- `KNOWLEDGE_BASE_PATH` — root of the knowledge base (auto-created in an OS-specific default if unset; on macOS `~/Library/Application Support/meridian`). The SQLite DB lives at `$KNOWLEDGE_BASE_PATH/meridian.db`, ChromaDB at `$KNOWLEDGE_BASE_PATH/chroma`.
- `MERIDIAN_ACCESS_LEVEL` — `read` | `analyze` (default) | `write`. Gates every tool via `TOOL_ACCESS_LEVELS` in `utils/security.py`.
- `MERIDIAN_PROJECT_PATH` — target project for `generate_project_skills`.

Tests isolate themselves by `monkeypatch.setenv("KNOWLEDGE_BASE_PATH", tmp_path)` and creating the four required subdirs (`knowledge-base/{global,projects}`, `lessons/{global,projects}`) — see the `tmp_kb` fixture pattern in `tests/integration/`.

## Architecture

### Layers

- `server.py` — FastMCP tool registration. Every `@mcp.tool()` is a thin wrapper that delegates to `_security_pattern(tool_name, params, project_id, impl)`, which does: sequential log ID → `check_access()` → run impl → write `access_log` row. New tools must follow this exact pattern and be added to `TOOL_ACCESS_LEVELS` in `utils/security.py`.
- `tools/` — implementations: `knowledge_management` (index, proposal lifecycle, promote, embeddings), `knowledge_consumption` (queries, context, timeline, audit log), `audit_flows` (PR audit, feedback, feature checks), `extraction` (transcript → proposals), `knowledge_templates` (canonical block templates).
- `parsers/` — `atomic_parser` for canonical `## RN-XXX-NNN` / `## LL-XXX-NNN` blocks; `legacy_parser` for old `###` files (legacy content only ever becomes `pending_proposals`, never direct rows).
- `rag/` — optional semantic search: `embedder` (lazy-loaded sentence-transformers `BAAI/bge-small-en-v1.5`, 384-dim, auto cuda/mps/cpu) + `vector_store` (ChromaDB, collections `meridian_rules` / `meridian_lessons`). Queries fall back to plain SQL when ChromaDB has no documents.
- `db/schema.sql` — full schema with seed scopes; `db/connection.py` opens connections (WAL mode) and initializes the schema.

### Key invariants

**Indexed reads with per-file freshness (ADR-005).** `detail="full"` queries serve text from SQLite (`rules.text` / `lessons.what_happened`), never by re-reading the `.md` file per row. Freshness is checked once per *distinct file* (not per row) via `utils/read_index.check_files_fresh`: `indexed_files(file_path, mtime, content_hash)` is compared against the file's current `stat()`; mtime match is a fast path (no read), a mismatch falls back to a sha256 comparison. A stale or unindexed file yields `text: None, error: "STALE_INDEX"` for every row backed by it — the error still appears per row in the serialized payload (ADR-001 unchanged), but the *granularity* of staleness detection is per-file now, not per-row-offset. `file_path`/`file_offset`/`byte_length` still exist on each row, but only as write-path metadata (`approve_proposal`'s update path, `_mark_deprecated_in_md`) — the read path never touches them. **`write_block`** (`utils/read_index.py`) is the single place any knowledge `.md` file's bytes are written; it writes the file and updates `indexed_files` in the same call, so the index can't drift from disk. Any code that rewrites a block in the middle of a file changes its length and silently invalidates the *write-path* offsets of all later blocks in that file (known weakness — re-index required); this no longer affects reads, since those come from SQLite.

**Scope hierarchy.** Scopes form a parent chain (e.g. `project-x → global-quarkus → global-java → global`). `utils/scope_resolver.resolve_scope_hierarchy` walks `scopes.parent_id`; queries include all scopes in the chain, ordered most-specific first. Project IDs are normalized to `project-<id>`. Per ADR-002, `rule_attributes` / `scope_attributes` add dynamic AND-matched filtering with *conservative inclusion*: a rule with no attributes, or whose attribute key is absent on the project, is always included.

**Proposal lifecycle.** Extraction and legacy migration never write rules directly — they create `pending_proposals`. `approve_proposal` is the single choke point that (1) appends or rewrites the atomic block in the `.md` file, (2) inserts/updates the `rules`/`lessons` row, (3) appends to `rule_history`/`lesson_history`, and (4) marks the proposal approved. `update`-type proposals carry a `target_id` (`RN-*`/`LL-*`) and rewrite an existing block in place.

**Privacy.** `utils/privacy.strip_private_tags` is applied to all inbound text before persistence (Layer 2 guarantee) — keep this on any new write path.

**IDs.** Human-readable sequential IDs are allocated from the `id_counters(name, next)` table via an atomic `UPDATE ... RETURNING` (`utils/id_generator.py`), not by scanning the target table: rules `RN-{TECH}-NNN`, lessons `LL-{TECH}-NNN`, generic tables `prefix-NNNN`. The `{TECH}` segment derives from the scope ID. `seed_id_counters()` backfills counters from real data (numeric max, not lexicographic — see ADR-004) and only ever runs once, from migration `002_id_counters.sql`.

**Migrations.** `db/migrations.py` discovers `NNN_*.sql` files under `db/migrations/`, applies those newer than `PRAGMA user_version`, and backs up the database file first. `initialize_db()` runs it unconditionally on every startup, on both fresh and existing databases. A migration needing logic beyond plain SQL (data backfill, per-row computation) dispatches to Python by migration number in `migrations.py::_apply_migration` — see `seed_id_counters` (002) and `backfill_read_index` (003) for the pattern.

**Serialization.** Per ADR-001, query tools return strings, serialized via `utils/serializers.serialize` supporting `json` and `toon` (compact tabular) formats; `toon` needs an explicit field list.

**Tag filtering.** `query_rules`/`query_lessons` filter tags via `rule_tags`/`lesson_tags` (normalized, one row per tag) with *exact* equality, not substring — `tags="go"` no longer matches a rule tagged only `"golang"` (ADR-005; was `tags LIKE '%go%'` before). The legacy `tags` JSON column on `rules`/`lessons` still exists and is still written, but is no longer read for filtering. `utils/read_index.sync_tags` is the only writer of `rule_tags`/`lesson_tags` — call it from any new write path that sets tags.

### Atomic block format

Field labels inside blocks are in Spanish and are load-bearing for both parsers and block builders (`**Scope:**`, `**Categoría:**`, `**Severidad:**`, `**Aplica a:**`, `**Tags:**`, `**Fuente:**`, `**Regla:**` for rules; `**Qué pasó:**`, `**Impacto:**`, `**Causa raíz:**`, `**Resolución:**` etc. for lessons). Changing a label requires touching `atomic_parser.py`, `_build_*_atomic_block` in `knowledge_management.py`, `_extract_lesson_fields`, and the templates in `knowledge_templates.py` together.

### Design docs

`meridian-prd-v1.md` (product spec), `meridian-implementation-plan.md`, `ADR-001` (serialization), `ADR-002` (dynamic attributes), `ADR-003` (legacy scope inference), `ADR-004` (id_counters + N+1 fix, Phase 1 of the performance remediation), `ADR-005` (indexed read path, Phase 2) at the repo root document intent behind the above invariants.
