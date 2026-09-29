"""SQLite connection and initialization utilities."""

import sqlite3
from pathlib import Path

from meridian.db.migrations import apply_pending_migrations
from meridian.utils.id_generator import seed_id_counters

REQUIRED_KB_DIRS = [
    "knowledge-base/global",
    "knowledge-base/projects",
    "lessons/global",
    "lessons/projects",
]


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open or create the SQLite database and configure pragmas."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db(db_path: Path) -> None:
    """Create the schema if missing, then apply any pending migrations."""
    kb_path = db_path.parent

    missing = [d for d in REQUIRED_KB_DIRS if not (kb_path / d).is_dir()]
    if missing:
        dirs_str = "\n  ".join(missing)
        raise RuntimeError(
            f"KNOWLEDGE_BASE_PATH '{kb_path}' is incomplete.\n"
            f"Missing directories:\n  {dirs_str}\n\n"
            f"Run:\n"
            + "\n".join(f"  mkdir -p '{kb_path / d}'" for d in missing)
        )

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scopes'"
        )
        if cursor.fetchone() is None:
            schema_path = Path(__file__).parent / "schema.sql"
            sql = schema_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()

        apply_pending_migrations(conn, db_path)

        # Reconcile id_counters against the tables' real state on every startup,
        # not only once via migration 002. seed_id_counters only ever raises a
        # counter (ON CONFLICT ... MAX(next, excluded.next)), never lowers one,
        # so this is a no-op when nothing drifted. Any row written through a
        # path that bypassed next_rule_code()/next_sequential_id() — a bulk
        # import, a restored backup, a future bug — would otherwise leave a
        # counter permanently behind the table's actual peak with no other
        # chance to self-heal, causing every later allocation for that name to
        # collide with an existing row (UNIQUE constraint failed).
        seed_id_counters(conn)
        conn.commit()
    finally:
        conn.close()
