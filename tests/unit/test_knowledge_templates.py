"""Unit tests for knowledge_templates module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from meridian.db.connection import get_connection, initialize_db


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    kb_path = tmp_path
    (kb_path / "knowledge-base" / "global").mkdir(parents=True)
    (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
    (kb_path / "lessons" / "global").mkdir(parents=True)
    (kb_path / "lessons" / "projects").mkdir(parents=True)
    db_path = kb_path / "test.db"
    initialize_db(db_path)
    return get_connection(db_path)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = _make_conn(tmp_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Task 2.0: Constants
# ---------------------------------------------------------------------------


def test_rule_template_is_nonempty_string() -> None:
    from meridian.tools import knowledge_templates

    assert isinstance(knowledge_templates.RULE_TEMPLATE, str)
    assert len(knowledge_templates.RULE_TEMPLATE) > 0


def test_rule_template_contains_header() -> None:
    from meridian.tools import knowledge_templates

    assert "## RN-XXX-NNN" in knowledge_templates.RULE_TEMPLATE


def test_rule_template_contains_placeholders() -> None:
    from meridian.tools import knowledge_templates

    for placeholder in ["{scope_id}", "{category}", "{severity}", "{text}"]:
        assert placeholder in knowledge_templates.RULE_TEMPLATE


def test_lesson_template_is_nonempty_string() -> None:
    from meridian.tools import knowledge_templates

    assert isinstance(knowledge_templates.LESSON_TEMPLATE, str)
    assert len(knowledge_templates.LESSON_TEMPLATE) > 0


def test_lesson_template_contains_header() -> None:
    from meridian.tools import knowledge_templates

    assert "## LL-XXX-NNN" in knowledge_templates.LESSON_TEMPLATE


def test_lesson_template_contains_placeholders() -> None:
    from meridian.tools import knowledge_templates

    for placeholder in ["{scope_id}", "{what_happened}", "{resolution}"]:
        assert placeholder in knowledge_templates.LESSON_TEMPLATE


def test_transcription_template_is_nonempty_string() -> None:
    from meridian.tools import knowledge_templates

    assert isinstance(knowledge_templates.TRANSCRIPTION_TEMPLATE, str)
    assert len(knowledge_templates.TRANSCRIPTION_TEMPLATE) > 0


def test_transcription_template_contains_both_headers() -> None:
    from meridian.tools import knowledge_templates

    assert "## RN-XXX-NNN" in knowledge_templates.TRANSCRIPTION_TEMPLATE
    assert "## LL-XXX-NNN" in knowledge_templates.TRANSCRIPTION_TEMPLATE


def test_module_importable_without_error() -> None:
    from meridian.tools import knowledge_templates  # noqa: F401

    assert knowledge_templates is not None


def test_no_circular_import_from_extraction() -> None:
    """knowledge_templates must NOT import from extraction."""
    import sys

    # Remove cached module to force fresh import
    for key in list(sys.modules.keys()):
        if "knowledge_templates" in key or "extraction" in key:
            del sys.modules[key]

    # Import extraction first so it's in sys.modules
    import meridian.tools.extraction  # noqa: F401

    # Now import knowledge_templates — it must not depend on extraction
    import meridian.tools.knowledge_templates as kt

    # Verify extraction is NOT in kt's source imports
    import inspect

    source = inspect.getsource(kt)
    assert "from meridian.tools.extraction" not in source
    assert "import extraction" not in source


# ---------------------------------------------------------------------------
# Task 2.2: build_rule_template_response
# ---------------------------------------------------------------------------


def test_build_rule_template_response_no_project_id_has_base_keys(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    assert "template" in result
    assert "fields" in result
    assert "usage" in result


def test_build_rule_template_response_no_project_id_no_scope_suggestions(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    assert "scope_suggestions" not in result


def test_build_rule_template_response_template_equals_constant(conn) -> None:
    from meridian.tools import knowledge_templates
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    assert result["template"] == knowledge_templates.RULE_TEMPLATE


def test_build_rule_template_response_fields_count(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    assert len(result["fields"]) == 7


def test_build_rule_template_response_fields_have_required_keys(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    for field in result["fields"]:
        assert "name" in field
        assert "required" in field
        assert "description" in field


def test_build_rule_template_response_field_names_order(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response(None, conn)
    names = [f["name"] for f in result["fields"]]
    assert names == ["scope_id", "category", "severity", "applies_to", "tags", "source", "text"]


def test_build_rule_template_response_valid_project_id_has_scope_suggestions(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("project-project-example", conn)
    assert "scope_suggestions" in result
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) > 0


def test_build_rule_template_response_valid_project_id_first_entry_recommended(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("project-project-example", conn)
    suggestions = result["scope_suggestions"]
    assert suggestions[0]["recommended"] is True


def test_build_rule_template_response_valid_project_id_others_not_recommended(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("project-project-example", conn)
    suggestions = result["scope_suggestions"]
    for entry in suggestions[1:]:
        assert entry["recommended"] is False


def test_build_rule_template_response_valid_project_id_entries_have_scope_id(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("project-project-example", conn)
    for entry in result["scope_suggestions"]:
        assert "scope_id" in entry


def test_build_rule_template_response_invalid_project_id_no_exception(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    # Must not raise
    result = build_rule_template_response("nonexistent-project", conn)
    assert result is not None


def test_build_rule_template_response_invalid_project_id_scope_suggestions_is_list(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("nonexistent-project", conn)
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) == 1


def test_build_rule_template_response_invalid_project_id_has_error_key(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("nonexistent-project", conn)
    entry = result["scope_suggestions"][0]
    assert "error" in entry
    assert len(entry["error"]) > 0


def test_build_rule_template_response_invalid_project_id_base_keys_present(conn) -> None:
    from meridian.tools.knowledge_templates import build_rule_template_response

    result = build_rule_template_response("nonexistent-project", conn)
    assert "template" in result
    assert "fields" in result
    assert "usage" in result


# ---------------------------------------------------------------------------
# Task 2.4: build_lesson_template_response
# ---------------------------------------------------------------------------


def test_build_lesson_template_response_no_project_id_has_base_keys(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    assert "template" in result
    assert "fields" in result
    assert "usage" in result


def test_build_lesson_template_response_no_project_id_no_scope_suggestions(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    assert "scope_suggestions" not in result


def test_build_lesson_template_response_template_equals_constant(conn) -> None:
    from meridian.tools import knowledge_templates
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    assert result["template"] == knowledge_templates.LESSON_TEMPLATE


def test_build_lesson_template_response_fields_count(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    assert len(result["fields"]) == 11


def test_build_lesson_template_response_fields_have_required_keys(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    for field in result["fields"]:
        assert "name" in field
        assert "required" in field
        assert "description" in field


def test_build_lesson_template_response_field_names_order(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response(None, conn)
    names = [f["name"] for f in result["fields"]]
    assert names == [
        "scope_id",
        "project",
        "date",
        "severity",
        "area",
        "tags",
        "what_happened",
        "impact",
        "root_cause",
        "resolution",
        "originated_rule",
    ]


def test_build_lesson_template_response_valid_project_id_scope_suggestions_list(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response("project-project-example", conn)
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) > 0
    assert result["scope_suggestions"][0]["recommended"] is True


def test_build_lesson_template_response_invalid_project_id_error_entry(conn) -> None:
    from meridian.tools.knowledge_templates import build_lesson_template_response

    result = build_lesson_template_response("nonexistent-project", conn)
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) == 1
    assert "error" in result["scope_suggestions"][0]
    assert len(result["scope_suggestions"][0]["error"]) > 0


# ---------------------------------------------------------------------------
# Task 2.6: build_transcription_template_response
# ---------------------------------------------------------------------------


def test_build_transcription_template_response_no_project_id_has_base_keys(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "template" in result
    assert "fields" in result
    assert "usage" in result


def test_build_transcription_template_response_no_project_id_no_scope_suggestions(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "scope_suggestions" not in result


def test_build_transcription_template_response_template_contains_both_headers(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "## RN-XXX-NNN" in result["template"]
    assert "## LL-XXX-NNN" in result["template"]


def test_build_transcription_template_response_fields_count(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert len(result["fields"]) == 2


def test_build_transcription_template_response_fields_text_required(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    text_field = next(f for f in result["fields"] if f["name"] == "text")
    assert text_field["required"] is True


def test_build_transcription_template_response_fields_project_id_required(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    pid_field = next(f for f in result["fields"] if f["name"] == "project_id")
    assert pid_field["required"] is True


def test_build_transcription_template_response_usage_mentions_extract_rules(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "extract_rules_from_transcript" in result["usage"]


def test_build_transcription_template_response_usage_mentions_extract_lessons(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "extract_lessons_from_transcript" in result["usage"]


def test_build_transcription_template_response_usage_mentions_create_pending_proposal(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    assert "create_pending_proposal" in result["usage"]


def test_build_transcription_template_response_usage_mentions_human_review(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response(None, conn)
    usage = result["usage"].lower()
    # Must state proposals are queued for human review
    assert "human review" in usage or "human" in usage


def test_build_transcription_template_response_valid_project_id_scope_suggestions_list(
    conn,
) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response("project-project-example", conn)
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) > 0


def test_build_transcription_template_response_invalid_project_id_error_entry(conn) -> None:
    from meridian.tools.knowledge_templates import build_transcription_template_response

    result = build_transcription_template_response("nonexistent-project", conn)
    assert isinstance(result["scope_suggestions"], list)
    assert len(result["scope_suggestions"]) == 1
    assert "error" in result["scope_suggestions"][0]
    assert len(result["scope_suggestions"][0]["error"]) > 0


# ---------------------------------------------------------------------------
# Task 2.8: Alias re-import guard (extraction.py backward compat)
# ---------------------------------------------------------------------------


def test_extraction_rule_template_equals_knowledge_templates_rule_template() -> None:
    from meridian.tools import knowledge_templates
    from meridian.tools.extraction import _RULE_TEMPLATE

    assert _RULE_TEMPLATE == knowledge_templates.RULE_TEMPLATE


def test_extraction_lesson_template_equals_knowledge_templates_lesson_template() -> None:
    from meridian.tools import knowledge_templates
    from meridian.tools.extraction import _LESSON_TEMPLATE

    assert _LESSON_TEMPLATE == knowledge_templates.LESSON_TEMPLATE
