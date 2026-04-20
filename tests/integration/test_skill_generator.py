"""Integration tests for skill generator."""

from __future__ import annotations

import json

import pytest
import yaml

from meridian.db.connection import get_connection, initialize_db
from meridian.utils.skill_generator import generate_project_skills


@pytest.fixture
def tmp_kb(tmp_path, monkeypatch):
    """Create a temporary knowledge base with an initialised DB."""
    kb_path = tmp_path / "kb"
    kb_path.mkdir()
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)

    monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def _seed_rules(conn) -> None:
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, status, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-001",
            "global-java",
            "RN-JAVA-001",
            "All code must be synchronous/imperative.",
            "architecture",
            "critical",
            "active",
            json.dumps(["test"]),
        ),
    )
    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, status, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-002",
            "global-java",
            "RN-JAVA-002",
            "Use structured JSON logging.",
            "logging",
            "high",
            "active",
            json.dumps(["test"]),
        ),
    )
    conn.commit()


def test_skill_md_has_yaml_frontmatter(tmp_kb, tmp_path):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    project_path = tmp_path / "project"
    project_path.mkdir()

    result = generate_project_skills(conn, "global-java", project_path)
    skill_md_path = result["skill_md"]
    content = skill_md_path.read_text(encoding="utf-8")

    assert content.startswith("---")
    parts = content.split("---", 2)
    assert len(parts) >= 3
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["name"] == "meridian-global-java"
    assert frontmatter["metadata"]["auto_invoke"] is True
    assert "query_rules" in frontmatter["metadata"]["allowed_tools"]


def test_agents_md_has_auto_invoke(tmp_kb, tmp_path):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    project_path = tmp_path / "project"
    project_path.mkdir()

    generate_project_skills(conn, "global-java", project_path)
    agents_path = project_path / "AGENTS.md"
    content = agents_path.read_text(encoding="utf-8")

    assert "## Auto-invoke Skills (Meridian)" in content
    assert "| Implementing any new feature | `meridian-global-java` |" in content
    assert "| Before submitting a PR | `meridian-global-java` |" in content
    assert "| Receiving Tech Lead feedback | `meridian-global-java` |" in content


def test_references_rules_has_text(tmp_kb, tmp_path):
    kb_path, conn = tmp_kb
    _seed_rules(conn)

    project_path = tmp_path / "project"
    project_path.mkdir()

    result = generate_project_skills(conn, "global-java", project_path)
    rules_md_path = result["rules_md"]
    content = rules_md_path.read_text(encoding="utf-8")

    assert "## RN-JAVA-001" in content
    assert "All code must be synchronous/imperative." in content
    assert "## RN-JAVA-002" in content
    assert "Use structured JSON logging." in content
