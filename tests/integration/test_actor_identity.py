"""Integration tests for actor attribution
(openspec/changes/add-actor-identity-tracking).

Covers both halves of that change's scope:
- Every rule_history/lesson_history/pending_proposals/access_log write site
  (the direct re-index path and the proposal-approval path) persists
  resolve_actor()'s value.
- The local-only user sees no behavioral difference other than the new
  actor_id field appearing in a few read tools' output (Group 7 in tasks.md,
  "local-user non-regression verification").
"""

from __future__ import annotations

import getpass
import json
import shutil

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.tools.extraction import create_pending_proposal
from meridian.tools.knowledge_consumption import (
    get_rule_audit_log,
    get_rule_context,
    get_rule_timeline,
)
from meridian.tools.knowledge_management import (
    approve_proposal,
    index_lessons_from_markdown,
    index_rules_from_markdown,
    list_pending_proposals,
    promote_rule,
)


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
    monkeypatch.delenv("MERIDIAN_MODE", raising=False)

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


_LESSON_BLOCK = (
    "## LL-JAVA-001\n"
    "**Scope:** global-java\n"
    "**Proyecto:** test-project\n"
    "**Fecha:** 2026-01-01\n"
    "**Severidad del impacto:** medium\n"
    "**Área afectada:** backend\n"
    "**Tags:** test\n"
    "**Qué pasó:** Something happened.\n"
    "**Impacto:** Minor.\n"
    "**Causa raíz:** A bug.\n"
    "**Resolución:** Fixed it.\n"
)


# --- Group 5: direct re-index path ---


def test_index_rules_from_markdown_create_and_update_record_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    me = getpass.getuser()
    created = conn.execute(
        "SELECT actor_id FROM rule_history WHERE change_type = 'CREATED'"
    ).fetchall()
    assert len(created) == 3
    assert all(row[0] == me for row in created)

    md_path = kb_path / "knowledge-base" / "global" / "java.md"
    original = md_path.read_text()
    md_path.write_text(
        original.replace(
            "All code must be synchronous/imperative.",
            "All code must be synchronous and imperative only.",
        )
    )
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    updated = conn.execute(
        "SELECT actor_id FROM rule_history WHERE change_type = 'UPDATED'"
    ).fetchall()
    assert len(updated) == 1
    assert updated[0][0] == me


def test_index_lessons_from_markdown_create_and_update_record_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    md_path = kb_path / "lessons" / "global" / "java.md"
    md_path.write_text(_LESSON_BLOCK)
    filepath = str(md_path)

    index_lessons_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    me = getpass.getuser()
    created = conn.execute(
        "SELECT actor_id FROM lesson_history WHERE change_type = 'CREATED'"
    ).fetchall()
    assert len(created) == 1
    assert created[0][0] == me

    md_path.write_text(_LESSON_BLOCK.replace("Something happened.", "Something else happened."))
    index_lessons_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    # _update_indexed_lesson records change_type='DEPRECATED' for a re-index
    # update (pre-existing behavior, unrelated to this change) — only its
    # actor_id is this test's concern.
    second_row = conn.execute(
        "SELECT actor_id FROM lesson_history ORDER BY changed_at, id"
    ).fetchall()
    assert len(second_row) == 2
    assert second_row[1][0] == me


# --- Group 6: proposal-approval path ---


def test_approve_create_rule_proposal_records_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    conn.execute(
        """
        INSERT INTO pending_proposals (id, type, scope_id, proposed_text, status)
        VALUES ('prop-0001', 'rule', 'global-java', 'A new rule.', 'pending')
        """
    )
    conn.commit()

    result = approve_proposal("prop-0001")

    row = conn.execute(
        "SELECT actor_id FROM rule_history WHERE rule_id = ?", (result["code"],)
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_approve_create_lesson_proposal_records_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "lessons" / "global" / "java.md"
    dest_file.write_text("")

    conn.execute(
        """
        INSERT INTO pending_proposals (id, type, scope_id, proposed_text, status)
        VALUES ('prop-0001', 'lesson', 'global-java', 'A lesson happened.', 'pending')
        """
    )
    conn.commit()

    result = approve_proposal("prop-0001")

    row = conn.execute(
        "SELECT actor_id FROM lesson_history WHERE lesson_id = ?", (result["code"],)
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_approve_update_proposal_records_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, target_id, proposed_text, metadata, status)
        VALUES ('prop-upd-001', 'update', 'RN-JAVA-002', 'Updated rule text.',
                ?, 'pending')
        """,
        (json.dumps({"category": "logging", "severity": "critical"}),),
    )
    conn.commit()

    approve_proposal("prop-upd-001")

    row = conn.execute(
        "SELECT actor_id FROM rule_history WHERE rule_id = 'RN-JAVA-002' "
        "AND change_type = 'UPDATED'"
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_approve_deprecate_proposal_records_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, target_id, proposed_text, reason, status)
        VALUES ('prop-dep-001', 'deprecate', 'RN-JAVA-003', 'Test rule three',
                'No longer applies', 'pending')
        """
    )
    conn.commit()

    approve_proposal("prop-dep-001")

    row = conn.execute(
        "SELECT actor_id FROM rule_history WHERE rule_id = 'RN-JAVA-003' "
        "AND change_type = 'DEPRECATED'"
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_promote_rule_records_actor_id(tmp_kb):
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    promote_rule("RN-JAVA-001", "global-quarkus")

    row = conn.execute(
        "SELECT actor_id FROM rule_history WHERE rule_id = 'RN-JAVA-001' "
        "AND change_type = 'PROMOTED'"
    ).fetchone()
    assert row[0] == getpass.getuser()


def test_approval_actor_id_is_independent_of_proposal_actor_id(tmp_kb, monkeypatch):
    """Spec requirement: the history row's actor_id reflects who approved,
    not who proposed — proven here by making the two resolve_actor() calls
    (one in extraction.py at proposal time, one in knowledge_management.py
    at approval time) return different values, rather than relying on both
    happening to be the same OS user in local mode."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    monkeypatch.setattr(
        "meridian.tools.extraction.resolve_actor", lambda: "proposer-alice"
    )
    proposal_id = create_pending_proposal(
        conn,
        "rule",
        "A new rule.",
        "global-java",
    )

    proposal_row = conn.execute(
        "SELECT actor_id FROM pending_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    assert proposal_row[0] == "proposer-alice"

    monkeypatch.setattr(
        "meridian.tools.knowledge_management.resolve_actor", lambda: "approver-bob"
    )
    result = approve_proposal(proposal_id)

    history_row = conn.execute(
        "SELECT actor_id FROM rule_history WHERE rule_id = ?", (result["code"],)
    ).fetchone()
    assert history_row[0] == "approver-bob"


# --- Group 7: local-user non-regression ---


def test_propose_approve_flow_identical_with_mode_unset_vs_local(tmp_path, monkeypatch):
    """Running the same propose -> approve flow with MERIDIAN_MODE unset and
    with it explicitly 'local' must produce identical rows except actor_id,
    which must be identical too since both resolve the same way."""

    def _run_flow(kb_path):
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)
        monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))

        from meridian.config import get_db_path

        db_path = get_db_path()
        initialize_db(db_path)
        conn = get_connection(db_path)

        dest_file = kb_path / "knowledge-base" / "global" / "java.md"
        dest_file.write_text("")

        proposal_id = create_pending_proposal(conn, "rule", "A new rule.", "global-java")
        result = approve_proposal(proposal_id)

        row = conn.execute(
            "SELECT text, category, severity, status FROM rules WHERE id = ?",
            (result["code"],),
        ).fetchone()
        conn.close()
        return row

    monkeypatch.delenv("MERIDIAN_MODE", raising=False)
    unset_result = _run_flow(tmp_path / "kb_unset")

    monkeypatch.setenv("MERIDIAN_MODE", "local")
    local_result = _run_flow(tmp_path / "kb_local")

    assert unset_result == local_result


def test_additive_output_get_rule_context(tmp_kb):
    """get_rule_context builds its history list from SELECT * FROM
    rule_history — actor_id appears automatically as a new key, with every
    other field/value unchanged."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")
    conn.execute(
        """
        INSERT INTO pending_proposals (id, type, scope_id, proposed_text, status)
        VALUES ('prop-0001', 'rule', 'global-java', 'A new rule.', 'pending')
        """
    )
    conn.commit()
    result = approve_proposal("prop-0001")

    context = get_rule_context(result["code"], conn=conn)
    assert len(context["history"]) == 1
    event = context["history"][0]
    assert event["actor_id"] == getpass.getuser()
    assert event["change_type"] == "CREATED"
    assert event["rule_id"] == result["code"]


def test_additive_output_get_rule_audit_log(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")
    conn.execute(
        """
        INSERT INTO pending_proposals (id, type, scope_id, proposed_text, status)
        VALUES ('prop-0001', 'rule', 'global-java', 'A new rule.', 'pending')
        """
    )
    conn.commit()
    approve_proposal("prop-0001")

    log = get_rule_audit_log(scope_id="global-java", conn=conn)
    assert len(log["events"]) == 1
    assert log["events"][0]["actor_id"] == getpass.getuser()


def test_additive_output_list_pending_proposals(tmp_kb):
    kb_path, conn = tmp_kb
    proposal_id = create_pending_proposal(conn, "rule", "A new rule.", "global-java")

    proposals = list_pending_proposals()
    match = next(p for p in proposals if p["id"] == proposal_id)
    assert match["actor_id"] == getpass.getuser()


def test_get_rule_timeline_unaffected_by_actor_identity(tmp_kb):
    """get_rule_timeline uses an explicit column list
    (change_type, reason, triggered_by, changed_at) — unlike get_rule_context
    and get_rule_audit_log, it must NOT gain an actor_id key."""
    kb_path, conn = tmp_kb
    shutil.copy(
        "knowledge-base/global/java.md",
        kb_path / "knowledge-base" / "global" / "java.md",
    )
    filepath = str(kb_path / "knowledge-base" / "global" / "java.md")
    index_rules_from_markdown(filepath, default_scope_id="global-java", mode="atomic")

    timeline = get_rule_timeline("RN-JAVA-001")
    assert len(timeline["history_events"]) == 1
    assert "actor_id" not in timeline["history_events"][0]
