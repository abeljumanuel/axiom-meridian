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


def _extract_block_bytes(
    text: str, raw_bytes: bytes, char_start: int, char_end: int
) -> tuple[str, int, int, str | None]:
    """Slice one block out of *text* and locate its byte range in *raw_bytes*.

    Char and byte offsets diverge once the file has non-ASCII content, so the
    byte range is recomputed by encoding rather than assumed equal to char
    positions. Returns (block_text, byte_start, byte_length, offset_warning).
    """
    byte_start = len(text[:char_start].encode("utf-8"))
    block_text = text[char_start:char_end]
    byte_length = len(block_text.encode("utf-8"))

    verification = raw_bytes[byte_start : byte_start + byte_length]
    offset_warning = None
    if verification.decode("utf-8") != block_text:
        offset_warning = f"Offset verification failed for block at char {char_start}"

    return block_text, byte_start, byte_length, offset_warning


def _parse_block_fields(block_text: str) -> dict:
    """Tokenize a block's ``**Field:** value`` lines into their known fields.

    The ``Regla``/``Qué pasó`` field is multi-line: it runs until the next
    ``**Field:**`` header, so it is captured by scanning ahead rather than by
    the single-line regex used for every other field.
    """
    fields: dict = {
        "scope": None,
        "category": None,
        "severity": None,
        "applies_to": None,
        "tags": [],
        "source": None,
        "text": "",
    }
    lines = block_text.split("\n")

    i_line = 1  # skip header line
    while i_line < len(lines):
        line = lines[i_line]
        field_match = _FIELD_RE.match(line)
        if field_match:
            field_name = field_match.group(1).strip()
            field_value = field_match.group(2).strip()

            if field_name == "Scope":
                fields["scope"] = field_value
            elif field_name == "Categoría":
                fields["category"] = field_value
            elif field_name == "Severidad":
                fields["severity"] = field_value
            elif field_name == "Aplica a":
                fields["applies_to"] = field_value
            elif field_name == "Tags":
                fields["tags"] = [t.strip() for t in field_value.split(",")]
            elif field_name == "Fuente":
                fields["source"] = field_value
            elif field_name in ("Regla", "Qué pasó"):
                rule_lines = [field_value]
                i_line += 1
                while i_line < len(lines):
                    next_line = lines[i_line]
                    if _FIELD_RE.match(next_line):
                        i_line -= 1
                        break
                    rule_lines.append(next_line)
                    i_line += 1
                fields["text"] = "\n".join(rule_lines).rstrip()
        i_line += 1

    return fields


def _missing_field_warnings(code: str, fields: dict) -> list[str]:
    """Warn about atomic fields absent from a parsed block."""
    warnings = []
    if fields["scope"] is None:
        warnings.append(f"Block {code}: missing 'Scope' field")
    if fields["category"] is None:
        warnings.append(f"Block {code}: missing 'Categoría' field")
    if fields["severity"] is None:
        warnings.append(f"Block {code}: missing 'Severidad' field")
    if fields["applies_to"] is None:
        warnings.append(f"Block {code}: missing 'Aplica a' field")
    if not fields["tags"]:
        warnings.append(f"Block {code}: missing or empty 'Tags' field")
    if fields["source"] is None:
        warnings.append(f"Block {code}: missing 'Fuente' field")
    if not fields["text"]:
        warnings.append(f"Block {code}: missing 'Regla' or 'Qué pasó' field")
    return warnings


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
        char_start = match.start()
        char_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        block_text, byte_start, byte_length, offset_warning = _extract_block_bytes(
            text, raw_bytes, char_start, char_end
        )
        if offset_warning:
            warnings.append(offset_warning)

        header_line = block_text.split("\n", 1)[0].strip()
        code = header_line.replace("## ", "").strip()

        fields = _parse_block_fields(block_text)
        warnings.extend(_missing_field_warnings(code, fields))

        blocks.append(
            ParsedBlock(
                code=code,
                scope=fields["scope"],
                category=fields["category"],
                severity=fields["severity"],
                applies_to=fields["applies_to"],
                tags=fields["tags"],
                source=fields["source"],
                text=fields["text"],
                file_path=str(path),
                file_offset=byte_start,
                byte_length=byte_length,
            )
        )

    return blocks, warnings
