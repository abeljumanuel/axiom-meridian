## 1. Parser fix

- [x] 1.1 Update `_BLOCK_HEADER_RE` in `src/meridian/parsers/atomic_parser.py` to
      `r"^## (RN|LL)-(?:[A-Z0-9]+-)?\d+"`, making the `{TECH}-` segment
      optional as a single unit.
- [x] 1.2 Update the "no atomic blocks found" warning text in `parse()` to
      state the `{TECH}` segment is optional (`## RN-<TECH>-<NNN>` or
      `## RN-<NNN>`).

## 2. MCP tool manifest (OpenAPI-equivalent for this server)

- [x] 2.1 Update the `mode` parameter's `Field(description=...)` on
      `index_rules_from_markdown` and `index_lessons_from_markdown` in
      `src/meridian/server.py` — this is what an MCP client reads from
      `tools/list`, and it only described the `{TECH}`-mandatory form.
- [x] 2.2 Confirm `get_rule_template`/`get_lesson_template`'s docstrings
      (canonical write-side template) intentionally need no change — new
      content still always uses `RN-{TECH}-NNN`.

## 3. Regression test

- [x] 3.1 Add `test_header_regex_accepts_plain_codes` to
      `tests/unit/test_atomic_parser.py`, following the existing
      `test_header_regex_accepts_digits_in_tech_segment` pattern: a
      `tmp_path` fixture with a `## RN-086` block, asserting `parse()`
      returns exactly one block with `code == "RN-086"`.

## 4. Verification

- [x] 4.1 Run `uv run pytest tests/unit/test_atomic_parser.py` — all pass,
      including the new test and the existing `{TECH}`-segment cases.
- [x] 4.2 Run `uv run ruff check src tests` — no new lint findings.
