"""Sequential ID generators for rules, lessons, and generic tables."""

import sqlite3


def _extract_segment(scope_id: str) -> str:
    """Extract the tech/project segment from a scope_id."""
    if scope_id == "global":
        return "GLOBAL"
    if scope_id.startswith("project-"):
        return scope_id.split("-")[1].upper()
    return scope_id.rsplit("-", 1)[-1].upper()


def next_rule_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """Generate the next rule code for a scope.

    Extracts the tech segment from the scope_id and queries the maximum
    existing rule code with the pattern ``RN-{TECH}-%``. Increments the
    numeric suffix by one, padding to three digits.
    """
    segment = _extract_segment(scope_id)
    cursor = conn.execute(
        "SELECT MAX(code) FROM rules WHERE code LIKE ?",
        (f"RN-{segment}-%",),
    )
    row = cursor.fetchone()
    max_code = row[0] if row else None
    if max_code is None:
        return f"RN-{segment}-001"
    # max_code is like "RN-JAVA-005"; extract the numeric part
    parts = max_code.rsplit("-", 1)
    next_num = int(parts[1]) + 1
    return f"RN-{segment}-{next_num:03d}"


def next_lesson_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """Generate the next lesson code for a scope.

    Works like :func:`next_rule_code` but uses the ``LL-{TECH}-%`` pattern.
    """
    segment = _extract_segment(scope_id)
    cursor = conn.execute(
        "SELECT MAX(code) FROM lessons WHERE code LIKE ?",
        (f"LL-{segment}-%",),
    )
    row = cursor.fetchone()
    max_code = row[0] if row else None
    if max_code is None:
        return f"LL-{segment}-001"
    parts = max_code.rsplit("-", 1)
    next_num = int(parts[1]) + 1
    return f"LL-{segment}-{next_num:03d}"


def next_sequential_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    """Generate the next sequential ID for a generic table.

    Queries the maximum existing ID with the pattern ``{prefix}-%`` and
    increments the numeric suffix, padding to four digits.
    """
    cursor = conn.execute(
        f"SELECT MAX(id) FROM {table} WHERE id LIKE ?",  # noqa: S608
        (f"{prefix}-%",),
    )
    row = cursor.fetchone()
    max_id = row[0] if row else None
    if max_id is None:
        return f"{prefix}-0001"
    parts = max_id.rsplit("-", 1)
    next_num = int(parts[1]) + 1
    return f"{prefix}-{next_num:04d}"
