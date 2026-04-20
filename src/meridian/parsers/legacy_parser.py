"""Parser for legacy format — sections with ### headings and bullet fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LegacyBlock:
    title: str
    section: str
    fields: dict[str, str]
    raw_text: str
    file_path: str
    file_offset: int
    byte_length: int


# Matches ### headings
_BLOCK_HEADER_RE = re.compile(r"^### (.+)$", re.MULTILINE)
# Matches ## section headings
_SECTION_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)
# Matches field lines: - **Campo**: valor or **Campo:** valor
_FIELD_RE = re.compile(r"(?:^\s*-\s*)?\*\*([^*]+)\*\*[:\s]+(.+)$")


def _should_skip_heading(heading: str) -> bool:
    """Return True if the heading indicates a section to skip."""
    heading_lower = heading.lower()
    if "verification:" in heading_lower:
        return True
    if "skill suggestions" in heading_lower:
        return True
    if heading.startswith("/"):
        return True
    return False


def parse(filepath: str, doc_type: str) -> list[LegacyBlock]:
    """
    Parse a legacy markdown file into blocks.

    Args:
        filepath: Path to the markdown file.
        doc_type: "rules" or "lessons".

    Returns:
        List of LegacyBlock instances.
    """
    path = Path(filepath)
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8")

    blocks: list[LegacyBlock] = []

    # Find all section headers (## ) to track current section
    section_matches = list(_SECTION_HEADER_RE.finditer(text))

    # Find all block headers (### )
    block_matches = list(_BLOCK_HEADER_RE.finditer(text))

    for i, match in enumerate(block_matches):
        char_start = match.start()
        char_end = block_matches[i + 1].start() if i + 1 < len(block_matches) else len(text)

        # Convert char positions to byte positions
        byte_start = len(text[:char_start].encode("utf-8"))
        byte_length = len(text[char_start:char_end].encode("utf-8"))

        block_text = text[char_start:char_end]

        # Extract title from heading
        heading = match.group(1).strip()

        # Skip verification, skill suggestions, and slash-prefixed headings
        if _should_skip_heading(heading):
            continue

        # Find current section
        current_section = ""
        for sec_match in section_matches:
            if sec_match.start() < char_start:
                current_section = sec_match.group(1).strip()
            else:
                break

        # Parse fields from block text
        fields: dict[str, str] = {}
        lines = block_text.split("\n")
        for line in lines[1:]:  # Skip heading line
            field_match = _FIELD_RE.match(line)
            if field_match:
                field_name = field_match.group(1).strip()
                field_value = field_match.group(2).strip()
                fields[field_name] = field_value

        blocks.append(
            LegacyBlock(
                title=heading,
                section=current_section,
                fields=fields,
                raw_text=block_text,
                file_path=str(path),
                file_offset=byte_start,
                byte_length=byte_length,
            )
        )

    return blocks
