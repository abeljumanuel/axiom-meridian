"""Tests for atomic_parser.py."""

from pathlib import Path

from meridian.parsers.atomic_parser import parse


SEED_FILE = "knowledge-base/global/java.md"


def test_parse_seed_file():
    blocks, warnings = parse(SEED_FILE)
    assert len(blocks) == 3


def test_block_codes():
    blocks, _ = parse(SEED_FILE)
    codes = [b.code for b in blocks]
    assert codes == ["RN-JAVA-001", "RN-JAVA-002", "RN-JAVA-003"]


def test_block_scope():
    blocks, _ = parse(SEED_FILE)
    for b in blocks:
        assert b.scope == "global-java"


def test_block_severity():
    blocks, _ = parse(SEED_FILE)
    assert blocks[0].severity == "critical"
    assert blocks[1].severity == "critical"
    assert blocks[2].severity == "high"


def test_block_tags():
    blocks, _ = parse(SEED_FILE)
    assert blocks[1].tags == [
        "slf4j",
        "fluent-api",
        "datadog",
        "structured-logging",
    ]


def test_positional_read():
    blocks, _ = parse(SEED_FILE)
    path = Path(SEED_FILE)
    raw_bytes = path.read_bytes()
    for b in blocks:
        chunk = raw_bytes[b.file_offset : b.file_offset + b.byte_length]
        text = chunk.decode("utf-8")
        assert b.code in text


def test_empty_file(tmp_path):
    empty_file = tmp_path / "empty.md"
    empty_file.write_text("")
    blocks, warnings = parse(str(empty_file))
    assert blocks == []
    assert warnings == []


def test_missing_scope_field(tmp_path):
    content = "## RN-TEST-001\n**Categoría:** test\n**Severidad:** low\n"
    missing_file = tmp_path / "missing.md"
    missing_file.write_text(content)
    blocks, warnings = parse(str(missing_file))
    assert len(blocks) == 1
    assert blocks[0].scope is None
    assert any("missing 'Scope'" in w for w in warnings)


def test_header_regex_accepts_digits_in_tech_segment(tmp_path):
    """Regression (ADR-006, Problem B): id_generator's _extract_segment()
    derives {TECH} from a scope_id with no character-class restriction — a
    scope like 'global-java17' produces codes such as RN-JAVA17-001, which
    the original [A-Z]+-only regex could never match, silently indexing 0
    blocks with no error."""
    content = (
        "## RN-JAVA17-001\n"
        "**Scope:** global-java17\n"
        "**Categoría:** test\n"
        "**Severidad:** low\n"
        "**Aplica a:** **/*.java\n"
        "**Tags:** java17\n"
        "**Fuente:** manual\n"
        "**Regla:** text\n"
    )
    f = tmp_path / "digits.md"
    f.write_text(content)
    blocks, warnings = parse(str(f))
    assert len(blocks) == 1
    assert blocks[0].code == "RN-JAVA17-001"
    assert warnings == []


def test_header_regex_accepts_plain_codes(tmp_path):
    """Regression: the original regex required a {TECH} segment
    (RN-{TECH}-NNN), so the legacy plain-code format RN-NNN/LL-NNN (no
    {TECH}) never matched and was silently dropped — 95 of 105 blocks in a
    migrated KB used this format. {TECH}- must be optional as a whole
    unit, not just its trailing character."""
    content = (
        "## RN-086\n"
        "**Scope:** global\n"
        "**Categoría:** test\n"
        "**Severidad:** low\n"
        "**Aplica a:** **/*\n"
        "**Tags:** legacy\n"
        "**Fuente:** manual\n"
        "**Regla:** text\n"
    )
    f = tmp_path / "plain.md"
    f.write_text(content)
    blocks, warnings = parse(str(f))
    assert len(blocks) == 1
    assert blocks[0].code == "RN-086"
    assert warnings == []


def test_no_blocks_found_warns_on_nonempty_file(tmp_path):
    """Regression (ADR-006, Option B2): a non-empty file that matches zero
    atomic block headers must surface an explicit warning naming the file
    and expected header format, instead of silently returning indexed: 0."""
    f = tmp_path / "malformed.md"
    f.write_text("### Old-style legacy header\nSome text.\n")
    blocks, warnings = parse(str(f))
    assert blocks == []
    assert len(warnings) == 1
    assert str(f) in warnings[0]
    assert "RN-" in warnings[0] and "LL-" in warnings[0]


def test_lesson_block_does_not_swallow_later_fields(tmp_path):
    """Regression (ADR-006, Problem B): _KNOWN_FIELD_NAMES originally only
    listed the 6 rule-only field labels, so the multiline scan for a
    lesson's 'Qué pasó' field never recognised 'Impacto', 'Causa raíz',
    'Resolución', or 'Originó regla' as stop conditions — it swallowed all
    of them into 'Qué pasó', corrupting every indexed LL-* lesson's text."""
    content = (
        "## LL-TEST-001\n"
        "**Scope:** global\n"
        "**Proyecto:** demo\n"
        "**Fecha:** 2026-01-01\n"
        "**Severidad del impacto:** medium\n"
        "**Área afectada:** deployment\n"
        "**Tags:** ci\n"
        "**Qué pasó:** The deploy failed silently.\n"
        "**Impacto:** Two hours of downtime.\n"
        "**Causa raíz:** Missing health check.\n"
        "**Resolución:** Added a readiness probe.\n"
        "**Originó regla:** RN-GLOBAL-099\n"
    )
    f = tmp_path / "lesson.md"
    f.write_text(content)
    blocks, warnings = parse(str(f))
    assert len(blocks) == 1
    assert blocks[0].code == "LL-TEST-001"
    # The bug under test: without the fix, "Impacto"/"Causa raíz"/"Resolución"/
    # "Originó regla" would all be swallowed into this field instead of
    # stopping at "Impacto". Warnings about rule-only fields (Categoría,
    # Aplica a, Fuente) are expected here and unrelated to this fix — the
    # parser doesn't distinguish rule vs. lesson blocks when checking those.
    assert blocks[0].text == "The deploy failed silently."
