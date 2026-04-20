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
