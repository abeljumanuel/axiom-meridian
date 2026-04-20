"""SQLite connection and initialization utilities."""

import sqlite3
from pathlib import Path

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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db(db_path: Path) -> None:
    """Initialize the database if the scopes table does not yet exist."""
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
        if cursor.fetchone() is not None:
            return

        schema_path = Path(__file__).parent / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
