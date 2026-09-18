"""Sequential ID generators for rules, lessons, and generic tables.

IDs are allocated from `id_counters`, an atomically-incremented table, instead
of scanning the target table with `SELECT MAX(id) LIKE 'prefix-%'` on every
call (reporte-rendimiento.md §3.2 — that scan is O(table size) and runs on
the critical path of all 26 MCP tools). `seed_id_counters` backfills this
table's starting values from the real data already present, run once by the
002 migration (see db/migrations.py).
"""

import sqlite3

_GENERIC_ID_TABLES: list[tuple[str, str, str]] = [
    # (table, id_column, counter_name == id prefix)
    ("access_log", "id", "al"),
    ("pending_proposals", "id", "prop"),
    ("rule_history", "id", "rh"),
    ("lesson_history", "id", "lh"),
    ("pr_audits", "id", "audit"),
    ("planning_checks", "id", "check"),
]

_CODE_TABLES: list[tuple[str, str, str]] = [
    # (table, code_column, code_prefix) — codes look like "RN-JAVA-005"
    ("rules", "code", "RN"),
    ("lessons", "code", "LL"),
]


def _extract_segment(scope_id: str) -> str:
    """Extract the tech/project segment from a scope_id."""
    if scope_id == "global":
        return "GLOBAL"
    if scope_id.startswith("project-"):
        return scope_id.split("-")[1].upper()
    return scope_id.rsplit("-", 1)[-1].upper()


def _next_counter_value(conn: sqlite3.Connection, name: str) -> int:
    """Atomically allocate and return the next integer for `name`.

    Initializes the counter at 1 on first use. Uses UPDATE ... RETURNING so
    the read-increment-write is a single atomic statement.
    """
    conn.execute(
        "INSERT INTO id_counters (name, next) VALUES (?, 1) "
        "ON CONFLICT(name) DO NOTHING",
        (name,),
    )
    cursor = conn.execute(
        "UPDATE id_counters SET next = next + 1 WHERE name = ? RETURNING next - 1",
        (name,),
    )
    return cursor.fetchone()[0]


def next_rule_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """Generate the next rule code for a scope (format: RN-{TECH}-NNN)."""
    segment = _extract_segment(scope_id)
    next_num = _next_counter_value(conn, f"RN-{segment}")
    return f"RN-{segment}-{next_num:03d}"


def next_lesson_code(conn: sqlite3.Connection, scope_id: str) -> str:
    """Generate the next lesson code for a scope (format: LL-{TECH}-NNN)."""
    segment = _extract_segment(scope_id)
    next_num = _next_counter_value(conn, f"LL-{segment}")
    return f"LL-{segment}-{next_num:03d}"


def next_sequential_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    """Generate the next sequential ID for a generic table (format: {prefix}-NNNN)."""
    next_num = _next_counter_value(conn, prefix)
    return f"{prefix}-{next_num:04d}"


def _max_generic_suffix(
    conn: sqlite3.Connection, table: str, column: str, prefix: str
) -> int:
    cursor = conn.execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ?",  # noqa: S608
        (f"{prefix}-%",),
    )
    max_num = 0
    for (value,) in cursor.fetchall():
        try:
            num = int(value.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        max_num = max(max_num, num)
    return max_num


def _max_code_suffix_by_segment(
    conn: sqlite3.Connection, table: str, column: str, code_prefix: str
) -> dict[str, int]:
    """Return {segment: max_numeric_suffix} for codes like 'RN-JAVA-005'."""
    cursor = conn.execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ?",  # noqa: S608
        (f"{code_prefix}-%",),
    )
    maxima: dict[str, int] = {}
    for (value,) in cursor.fetchall():
        parts = value.split("-")
        if len(parts) != 3:
            continue
        _, segment, suffix = parts
        try:
            num = int(suffix)
        except ValueError:
            continue
        maxima[segment] = max(maxima.get(segment, 0), num)
    return maxima


def seed_id_counters(conn: sqlite3.Connection) -> None:
    """Seed id_counters from the real numeric maxima already present.

    Uses the actual numeric suffix (not lexicographic MAX, which breaks past
    999/9999 padding — reporte-rendimiento.md §3.3), so existing IDs never
    collide with newly generated ones. Idempotent: never lowers a counter
    that is already ahead (ON CONFLICT ... MAX(next, excluded.next)), and a
    no-op on an empty/fresh database.
    """
    for table, column, prefix in _GENERIC_ID_TABLES:
        max_num = _max_generic_suffix(conn, table, column, prefix)
        if max_num:
            conn.execute(
                "INSERT INTO id_counters (name, next) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET next = MAX(next, excluded.next)",
                (prefix, max_num + 1),
            )

    for table, column, code_prefix in _CODE_TABLES:
        for segment, max_num in _max_code_suffix_by_segment(
            conn, table, column, code_prefix
        ).items():
            conn.execute(
                "INSERT INTO id_counters (name, next) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET next = MAX(next, excluded.next)",
                (f"{code_prefix}-{segment}", max_num + 1),
            )
