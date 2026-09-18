"""E2E test: migrations 001+002+003 applied in sequence to a populated
"field" database — one that predates this session's work entirely (no
id_counters, no indexed_files/rule_tags/lesson_tags, lessons missing the
001 columns) — and verifies the end state is fully consistent: no data
loss, no ID collisions, correct tag/index backfill, and normal read/write
tool usage works afterward.

See plan-rendimiento.md T10.
"""

from __future__ import annotations

import json
import sqlite3

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.knowledge_consumption import query_rules
from meridian.tools.knowledge_management import approve_proposal

# Schema as it looked before migrations 001/002/003 existed: no id_counters,
# no indexed_files/rule_tags/lesson_tags, lessons missing source_type/
# source_ref/created_at/updated_at. Trimmed to what this test needs.
_LEGACY_SCHEMA = """
CREATE TABLE scopes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
  parent_id TEXT REFERENCES scopes(id)
);
CREATE TABLE scope_attributes (
  scope_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (scope_id, key)
);
CREATE TABLE rules (
  id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
  text TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
  applies_to TEXT, tags TEXT, status TEXT DEFAULT 'active',
  source_type TEXT, source_ref TEXT, file_path TEXT, file_offset INTEGER,
  byte_length INTEGER, originated_lesson_id TEXT, embedding_id TEXT,
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE rule_attributes (
  rule_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (rule_id, key)
);
CREATE TABLE rule_history (
  id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, change_type TEXT NOT NULL,
  previous_text TEXT, new_text TEXT, reason TEXT, triggered_by TEXT,
  changed_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE lesson_history (
  id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL, change_type TEXT NOT NULL,
  previous_text TEXT, new_text TEXT, reason TEXT, triggered_by TEXT,
  changed_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE lessons (
  id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
  project TEXT, date_occurred TEXT, severity TEXT, area_affected TEXT,
  what_happened TEXT, impact TEXT, root_cause TEXT, resolution TEXT,
  tags TEXT, originated_rule_id TEXT, status TEXT DEFAULT 'active',
  file_path TEXT, file_offset INTEGER, byte_length INTEGER, embedding_id TEXT
);
CREATE TABLE rule_lesson_links (
  rule_id TEXT NOT NULL, lesson_id TEXT NOT NULL, link_type TEXT NOT NULL,
  PRIMARY KEY (rule_id, lesson_id)
);
CREATE TABLE project_scope_resolution (
  project_id TEXT PRIMARY KEY, resolved_scopes TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE pr_audits (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, pr_ref TEXT, diff_hash TEXT,
  rules_evaluated INTEGER, violations_found TEXT, feedback_analyzed TEXT,
  rule_version_snapshot TEXT, audited_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE planning_checks (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, feature_description TEXT,
  conflicts_found TEXT, rules_involved TEXT, checked_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE pending_proposals (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, scope_id TEXT, target_id TEXT,
  proposed_text TEXT NOT NULL, metadata TEXT, suggested_attributes TEXT,
  source_type TEXT, source_ref TEXT, status TEXT DEFAULT 'pending',
  reason TEXT, legacy_original TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE access_log (
  id TEXT PRIMARY KEY, timestamp TEXT DEFAULT (datetime('now')),
  tool_name TEXT NOT NULL, access_level TEXT NOT NULL, project_id TEXT,
  parameters TEXT, result TEXT NOT NULL, transport TEXT
);
"""


def test_field_database_migrates_cleanly_end_to_end(tmp_path, monkeypatch):
    kb_path = tmp_path / "kb"
    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
    for d in (
        "knowledge-base/global",
        "knowledge-base/projects",
        "lessons/global",
        "lessons/projects",
    ):
        (kb_path / d).mkdir(parents=True)

    db_path = kb_path / "meridian.db"
    raw = sqlite3.connect(str(db_path))
    raw.executescript(_LEGACY_SCHEMA)

    raw.execute(
        "INSERT INTO scopes VALUES ('global', 'global', 'Global', NULL)"
    )
    raw.execute(
        "INSERT INTO scopes VALUES ('global-java', 'global', 'Global Java', 'global')"
    )

    # Realistic pre-existing data: rules with a real file behind them,
    # existing history, an access_log with a high-numbered id (padding
    # boundary), and a pending proposal.
    java_md = kb_path / "knowledge-base" / "global" / "java.md"
    block1 = "## RN-JAVA-001\n**Regla:** Use records for DTOs.\n"
    block2 = "## RN-JAVA-002\n**Regla:** Avoid checked exceptions.\n"
    java_md.write_text(block1 + "\n" + block2)
    offset2 = len(block1.encode("utf-8")) + 1

    raw.execute(
        "INSERT INTO rules (id, scope_id, code, text, category, severity, "
        "tags, file_path, file_offset, byte_length) VALUES "
        "('RN-JAVA-001', 'global-java', 'RN-JAVA-001', 'Use records for DTOs.', "
        "'style', 'medium', ?, ?, 0, ?)",
        (json.dumps(["records", "dto"]), str(java_md), len(block1.encode("utf-8"))),
    )
    raw.execute(
        "INSERT INTO rules (id, scope_id, code, text, category, severity, "
        "tags, file_path, file_offset, byte_length) VALUES "
        "('RN-JAVA-002', 'global-java', 'RN-JAVA-002', 'Avoid checked exceptions.', "
        "'style', 'medium', ?, ?, ?, ?)",
        (
            json.dumps([]),
            str(java_md),
            offset2,
            len(block2.encode("utf-8")),
        ),
    )
    raw.execute(
        "INSERT INTO rule_history (id, rule_id, change_type, new_text) "
        "VALUES ('rh-0001', 'RN-JAVA-001', 'CREATED', 'Use records for DTOs.')"
    )

    lessons_md = kb_path / "lessons" / "global" / "general.md"
    lesson_block = "## LL-GLOBAL-001\n**Qué pasó:** Deploy failed silently.\n"
    lessons_md.write_text(lesson_block)
    raw.execute(
        "INSERT INTO lessons (id, scope_id, code, what_happened, tags, "
        "file_path, file_offset, byte_length) VALUES "
        "('LL-GLOBAL-001', 'global', 'LL-GLOBAL-001', 'Deploy failed silently.', "
        "?, ?, 0, ?)",
        (json.dumps(["deploy", "ci"]), str(lessons_md), len(lesson_block.encode("utf-8"))),
    )

    # access_log already at a 4-digit boundary — the seed must continue
    # from the real numeric max, not collide.
    raw.execute(
        "INSERT INTO access_log (id, tool_name, access_level, result) "
        "VALUES ('al-9999', 'query_rules', 'read', 'success')"
    )

    raw.execute(
        "INSERT INTO pending_proposals (id, type, scope_id, proposed_text, metadata, status) "
        "VALUES ('prop-0001', 'rule', 'global-java', 'New rule.', '{}', 'pending')"
    )

    raw.commit()
    raw.close()

    # --- Run the full migration chain (001 -> 002 -> 003) ---
    initialize_db(db_path)

    conn = get_connection(db_path)
    try:
        # 1. No data lost.
        assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM pending_proposals").fetchone()[0] == 1
        )

        # 2. Migration 001: lessons has the new columns.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(lessons)")}
        assert {"source_type", "source_ref", "created_at", "updated_at"} <= columns

        # 3. Migration 002: id_counters seeded from real data, no collisions.
        from meridian.utils.id_generator import next_rule_code, next_sequential_id

        new_rule_code = next_rule_code(conn, "global-java")
        assert new_rule_code == "RN-JAVA-003"  # continues after 001/002

        new_log_id = next_sequential_id(conn, "access_log", "al")
        assert new_log_id == "al-10000"  # continues past the 9999 boundary

        existing_codes = {
            row[0] for row in conn.execute("SELECT code FROM rules")
        }
        assert new_rule_code not in existing_codes

        # 4. Migration 003: tags backfilled exactly, indexed_files populated.
        rule_tags = {
            row[0]
            for row in conn.execute(
                "SELECT tag FROM rule_tags WHERE rule_id = 'RN-JAVA-001'"
            )
        }
        assert rule_tags == {"records", "dto"}
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM rule_tags WHERE rule_id = 'RN-JAVA-002'"
            ).fetchone()[0]
            == 0
        )

        lesson_tags = {
            row[0]
            for row in conn.execute(
                "SELECT tag FROM lesson_tags WHERE lesson_id = 'LL-GLOBAL-001'"
            )
        }
        assert lesson_tags == {"deploy", "ci"}

        indexed = {
            row[0] for row in conn.execute("SELECT file_path FROM indexed_files")
        }
        assert str(java_md) in indexed
        assert str(lessons_md) in indexed

        # 5. Normal tool usage works post-migration: reads serve correct
        # text, writes (approve_proposal) still work and keep the index in
        # sync going forward.
        conn.commit()
        result = query_rules("global-java", detail="full")
        data = json.loads(result)
        by_code = {r["code"]: r for r in data}
        assert by_code["RN-JAVA-001"]["text"] == "Use records for DTOs."
        assert "error" not in by_code["RN-JAVA-001"]

        # next_rule_code above already consumed RN-JAVA-003 as a probe;
        # a real approval must get the next one, never repeat a code.
        approved = approve_proposal("prop-0001")
        assert approved["code"] == "RN-JAVA-004"
        assert approved["code"] not in existing_codes | {new_rule_code}
    finally:
        conn.close()
