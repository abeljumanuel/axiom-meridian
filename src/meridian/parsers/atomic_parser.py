"""Parser for atomic format — blocks starting with ## RN-XXX-NNN or ## LL-XXX-NNN."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedBlock:
    code: str
    scope: str | None
    category: str | None
    severity: str | None
    applies_to: str | None
    tags: list[str]
    source: str | None
    text: str
    file_path: str
    file_offset: int
    byte_length: int


# Matches ## RN-XXX-NNN or ## LL-XXX-NNN at the start of a line
_BLOCK_HEADER_RE = re.compile(r"^## (RN|LL)-[A-Z]+-\d+", re.MULTILINE)
# Matches **Campo:** valor (single-line fields)
_FIELD_RE = re.compile(r"\*\*([^*]+):\*\*\s*(.+)")


def parse(filepath: str) -> tuple[list[ParsedBlock], list[str]]:
    """
    Parse an atomic markdown file into blocks.

    Returns (blocks, warnings).
    """
    path = Path(filepath)
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8")

    blocks: list[ParsedBlock] = []
    warnings: list[str] = []

    matches = list(_BLOCK_HEADER_RE.finditer(text))

    for i, match in enumerate(matches):
        # Calculate byte offsets in the original bytes
        char_start = match.start()
        char_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        # Convert char positions to byte positions
        byte_start = len(text[:char_start].encode("utf-8"))

        block_text = text[char_start:char_end]
        block_bytes = block_text.encode("utf-8")
        byte_length = len(block_bytes)

        # Verify positional read
        verification = raw_bytes[byte_start : byte_start + byte_length]
        if verification.decode("utf-8") != block_text:
            warnings.append(
                f"Offset verification failed for block at char {char_start}"
            )

        # Extract code from header line
        header_line = block_text.split("\n", 1)[0].strip()
        code = header_line.replace("## ", "").strip()

        # Parse fields
        scope: str | None = None
        category: str | None = None
        severity: str | None = None
        applies_to: str | None = None
        tags: list[str] = []
        source: str | None = None
        rule_text: str = ""

        # Split block into lines for field parsing
        lines = block_text.split("\n")

        i_line = 1  # Skip header line
        while i_line < len(lines):
            line = lines[i_line]
            field_match = _FIELD_RE.match(line)
            if field_match:
                field_name = field_match.group(1).strip()
                field_value = field_match.group(2).strip()

                if field_name == "Scope":
                    scope = field_value
                elif field_name == "Categoría":
                    category = field_value
                elif field_name == "Severidad":
                    severity = field_value
                elif field_name == "Aplica a":
                    applies_to = field_value
                elif field_name == "Tags":
                    tags = [t.strip() for t in field_value.split(",")]
                elif field_name == "Fuente":
                    source = field_value
                elif field_name in ("Regla", "Qué pasó"):
                    # Multi-line field: capture rest of block
                    rule_lines = [field_value]
                    i_line += 1
                    while i_line < len(lines):
                        next_line = lines[i_line]
                        # Stop if we hit another field or empty line followed by field
                        if _FIELD_RE.match(next_line):
                            i_line -= 1
                            break
                        rule_lines.append(next_line)
                        i_line += 1
                    rule_text = "\n".join(rule_lines).rstrip()
                else:
                    # Unknown field, store as-is? For now just track
                    pass
            i_line += 1

        # Check for missing fields and report warnings
        if scope is None:
            warnings.append(f"Block {code}: missing 'Scope' field")
        if category is None:
            warnings.append(f"Block {code}: missing 'Categoría' field")
        if severity is None:
            warnings.append(f"Block {code}: missing 'Severidad' field")
        if applies_to is None:
            warnings.append(f"Block {code}: missing 'Aplica a' field")
        if not tags:
            warnings.append(f"Block {code}: missing or empty 'Tags' field")
        if source is None:
            warnings.append(f"Block {code}: missing 'Fuente' field")
        if not rule_text:
            warnings.append(f"Block {code}: missing 'Regla' or 'Qué pasó' field")

        blocks.append(
            ParsedBlock(
                code=code,
                scope=scope,
                category=category,
                severity=severity,
                applies_to=applies_to,
                tags=tags,
                source=source,
                text=rule_text,
                file_path=str(path),
                file_offset=byte_start,
                byte_length=byte_length,
            )
        )

    return blocks, warnings
