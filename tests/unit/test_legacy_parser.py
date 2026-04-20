"""Tests for legacy_parser.py."""

from meridian.parsers.legacy_parser import LegacyBlock, parse


def test_parse_lessons_format(tmp_path):
    content = """## Phase 1 — Contracts Layer

### Issue 1.1: Timeout Handling
- **Problem**: Missing timeout caused thread starvation.
- **Resolution**: Added explicit timeouts.
"""
    filepath = tmp_path / "lessons.md"
    filepath.write_text(content)
    blocks = parse(str(filepath), doc_type="lessons")
    assert len(blocks) == 1
    assert isinstance(blocks[0], LegacyBlock)
    assert blocks[0].title == "Issue 1.1: Timeout Handling"
    assert blocks[0].section == "Phase 1 — Contracts Layer"
    assert blocks[0].fields["Problem"] == "Missing timeout caused thread starvation."
    assert blocks[0].fields["Resolution"] == "Added explicit timeouts."


def test_skip_verification_sections(tmp_path):
    content = """## Phase 0

### Verification: Phase 0
- **Check**: something

### Issue 1.1: Real Issue
- **Problem**: real problem
"""
    filepath = tmp_path / "lessons.md"
    filepath.write_text(content)
    blocks = parse(str(filepath), doc_type="lessons")
    assert len(blocks) == 1
    assert blocks[0].title == "Issue 1.1: Real Issue"


def test_skip_skill_suggestions(tmp_path):
    content = """## Skills

### /pr-implement
- **Description**: implement PR

### Issue 1.1: Real Issue
- **Problem**: real problem
"""
    filepath = tmp_path / "lessons.md"
    filepath.write_text(content)
    blocks = parse(str(filepath), doc_type="lessons")
    assert len(blocks) == 1
    assert blocks[0].title == "Issue 1.1: Real Issue"


def test_multiple_blocks(tmp_path):
    content = """## Phase 1

### Issue 1.1: First
- **Problem**: p1

### Issue 1.2: Second
- **Problem**: p2

### Issue 1.3: Third
- **Problem**: p3
"""
    filepath = tmp_path / "lessons.md"
    filepath.write_text(content)
    blocks = parse(str(filepath), doc_type="lessons")
    assert len(blocks) == 3
    for i, b in enumerate(blocks):
        assert b.file_offset >= 0
        assert b.byte_length > 0
        # Verify offsets are unique and ordered
        if i > 0:
            assert b.file_offset > blocks[i - 1].file_offset


def test_positional_read_legacy(tmp_path):
    content = """## Phase 1

### Issue 1.1: Timeout Handling
- **Problem**: Missing timeout caused thread starvation.
- **Resolution**: Added explicit timeouts.
"""
    filepath = tmp_path / "lessons.md"
    filepath.write_text(content)
    blocks = parse(str(filepath), doc_type="lessons")
    assert len(blocks) == 1

    raw_bytes = filepath.read_bytes()
    b = blocks[0]
    chunk = raw_bytes[b.file_offset : b.file_offset + b.byte_length]
    assert chunk.decode("utf-8") == b.raw_text
