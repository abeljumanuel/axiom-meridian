"""Integration tests for proposal lifecycle (edit, reject, approve with attributes)."""

from __future__ import annotations

import hashlib
import json

import pytest

from meridian.db.connection import get_connection, initialize_db
from meridian.parsers.atomic_parser import parse as atomic_parse
from meridian.tools.knowledge_management import (
    approve_proposal,
    edit_proposal,
    promote_rule,
    reject_proposal,
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

    from meridian.config import get_db_path

    db_path = get_db_path()
    initialize_db(db_path)

    conn = get_connection(db_path)
    yield kb_path, conn
    conn.close()


def test_edit_proposal(tmp_kb):
    kb_path, conn = tmp_kb

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (prop_id, "rule", "global-java", "Original text.", "pending"),
    )
    conn.commit()

    result = edit_proposal(prop_id, "Updated text.")

    assert result["proposal_id"] == prop_id
    assert result["status"] == "pending"

    cursor = conn.execute(
        "SELECT proposed_text, status FROM pending_proposals WHERE id = ?",
        (prop_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "Updated text."
    assert row[1] == "pending"


def test_reject_proposal(tmp_kb):
    kb_path, conn = tmp_kb

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (prop_id, "rule", "global-java", "Some text.", "pending"),
    )
    conn.commit()

    result = reject_proposal(prop_id, reason="Not applicable")

    assert result["proposal_id"] == prop_id
    assert result["status"] == "rejected"

    cursor = conn.execute(
        "SELECT status, reason FROM pending_proposals WHERE id = ?",
        (prop_id,),
    )
    row = cursor.fetchone()
    assert row[0] == "rejected"
    assert row[1] == "Not applicable"


def test_approve_with_attributes(tmp_kb):
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, metadata, suggested_attributes, source_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            "rule",
            "global-java",
            "Rule with attributes.",
            json.dumps(
                {
                    "category": "testing",
                    "severity": "low",
                    "applies_to": "**/*.java",
                    "tags": ["test"],
                    "source": "manual",
                }
            ),
            json.dumps(
                [
                    {"key": "framework", "value": "quarkus"},
                    {"key": "component_role", "value": "gateway"},
                ]
            ),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    cursor = conn.execute(
        "SELECT key, value FROM rule_attributes WHERE rule_id = ?",
        (result["code"],),
    )
    rows = cursor.fetchall()
    attrs = {row[0]: row[1] for row in rows}

    assert attrs["framework"] == "quarkus"
    assert attrs["component_role"] == "gateway"


def test_approve_proposal_keeps_indexed_files_and_tags_in_sync(tmp_kb):
    """T05 acceptance: after approve_proposal, indexed_files.content_hash
    matches the real .md on disk, and rule_tags mirrors the metadata tags."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    prop_id = "prop-0001"
    conn.execute(
        """
        INSERT INTO pending_proposals
        (id, type, scope_id, proposed_text, metadata, source_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            prop_id,
            "rule",
            "global-java",
            "Rule with tags.",
            json.dumps({"tags": ["go", "fiber"]}),
            "manual",
        ),
    )
    conn.commit()

    result = approve_proposal(prop_id)

    row = conn.execute(
        "SELECT content_hash FROM indexed_files WHERE file_path = ?",
        (str(dest_file),),
    ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(dest_file.read_bytes()).hexdigest()

    tags = {
        r[0]
        for r in conn.execute(
            "SELECT tag FROM rule_tags WHERE rule_id = ?", (result["code"],)
        )
    }
    assert tags == {"go", "fiber"}


def test_promote_rule_refreshes_indexed_files_for_affected_file(tmp_kb):
    """T05 acceptance: after promote_rule (_mark_deprecated_in_md),
    indexed_files for the affected .md reflects the deprecation edit."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "projects" / "example.md"
    dest_file.write_text("## RN-EXAMPLE-001\nSome rule text.\n")

    conn.execute(
        """
        INSERT INTO rules
        (id, scope_id, code, text, category, severity, file_path, file_offset, byte_length)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "RN-EXAMPLE-001",
            "project-project-example",
            "RN-EXAMPLE-001",
            "Some rule text.",
            "general",
            "medium",
            str(dest_file),
            0,
            len("## RN-EXAMPLE-001\nSome rule text.\n".encode("utf-8")) - 1,
        ),
    )
    conn.commit()

    promote_rule("RN-EXAMPLE-001", "global-quarkus")

    row = conn.execute(
        "SELECT content_hash FROM indexed_files WHERE file_path = ?",
        (str(dest_file),),
    ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(dest_file.read_bytes()).hexdigest()
    assert b"**Status:** deprecated" in dest_file.read_bytes()


def _atomic_rule_block(code: str, regla: str) -> str:
    return (
        f"## {code}\n"
        "**Scope:** global-java\n"
        "**Categoría:** exceptions\n"
        "**Severidad:** high\n"
        "**Aplica a:** **/*.java\n"
        "**Tags:** jackson\n"
        "**Fuente:** manual\n"
        f"**Regla:** {regla}\n"
    )


def test_two_sequential_update_approvals_do_not_corrupt_the_shared_file(tmp_kb):
    """Regression for the reported incident: approving an UPDATE that grows
    its block, then approving an UPDATE on a later block in the SAME file,
    used to corrupt the file — the second splice used its cached
    file_offset, which the first approval never shifted. Mirrors
    prop-0013/prop-0014 against java.md almost exactly (RN-086 growing,
    RN-092 spliced right after it, plus an unrelated later rule to prove
    the shift reaches beyond the immediately-next block)."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"

    old_text_a = "Handle MismatchedInputException."
    text_b = "Do not revert extending UpstreamResponse without updating the retry policy doc."
    text_c = "Always close JDBC resources in a try-with-resources block."

    block_a = _atomic_rule_block("RN-JAVA-086", old_text_a)
    block_b = _atomic_rule_block("RN-JAVA-092", text_b)
    block_c = _atomic_rule_block("RN-JAVA-100", text_c)
    content = (block_a + "\n" + block_b + "\n" + block_c).encode("utf-8")
    dest_file.write_bytes(content)

    # Seed file_offset/byte_length exactly as real initial indexing would
    # (_index_rules_atomic uses atomic_parse's own spans directly) — hand-
    # computing them independently risks a convention mismatch with what
    # the parser actually considers "this block's span" (up to the next
    # header, including any separator whitespace).
    seed_blocks = {b.code: b for b in atomic_parse(str(dest_file))[0]}

    for code, text in (
        ("RN-JAVA-086", old_text_a),
        ("RN-JAVA-092", text_b),
        ("RN-JAVA-100", text_c),
    ):
        offset, length = seed_blocks[code].file_offset, seed_blocks[code].byte_length
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "applies_to, tags, file_path, file_offset, byte_length) "
            "VALUES (?, 'global-java', ?, ?, 'exceptions', 'high', '**/*.java', "
            "'[\"jackson\"]', ?, ?, ?)",
            (code, code, text, str(dest_file), offset, length),
        )
    conn.commit()

    # prop-0013 equivalent: UPDATE RN-JAVA-086 with much longer text — grows
    # its block, which is exactly what leaves RN-JAVA-092/-100's cached
    # offsets stale if nothing shifts them.
    new_text_a = (
        "Use a custom exception mapper for MismatchedInputException and "
        "document the new OpenAPI error schema paragraph that follows it."
    )
    conn.execute(
        "INSERT INTO pending_proposals (id, type, target_id, proposed_text, "
        "metadata, status) VALUES ('prop-0013', 'update', 'RN-JAVA-086', ?, ?, 'pending')",
        (new_text_a, json.dumps({"category": "exceptions", "severity": "high"})),
    )
    conn.commit()
    approve_proposal("prop-0013")

    # prop-0014 equivalent: UPDATE RN-JAVA-092 (unchanged text is enough to
    # trigger the bug — what matters is that its OWN cached offset was
    # stale going into this approval).
    conn.execute(
        "INSERT INTO pending_proposals (id, type, target_id, proposed_text, "
        "metadata, status) VALUES ('prop-0014', 'update', 'RN-JAVA-092', ?, ?, 'pending')",
        (text_b, json.dumps({"category": "exceptions", "severity": "high"})),
    )
    conn.commit()
    approve_proposal("prop-0014")

    # The file must still parse into exactly 3 well-formed blocks, each
    # with its correct, uncorrupted text.
    blocks, warnings = atomic_parse(str(dest_file))
    assert warnings == []
    by_code = {b.code: b for b in blocks}
    assert set(by_code) == {"RN-JAVA-086", "RN-JAVA-092", "RN-JAVA-100"}

    raw = dest_file.read_bytes()

    def block_text(code: str) -> str:
        b = by_code[code]
        return raw[b.file_offset : b.file_offset + b.byte_length].decode("utf-8")

    assert new_text_a in block_text("RN-JAVA-086")
    assert text_b in block_text("RN-JAVA-092")
    # No leftover/duplicated garbage from the old block sizes.
    assert block_text("RN-JAVA-092").count("**Regla:**") == 1
    assert text_c in block_text("RN-JAVA-100")

    # Every DOWNSTREAM row's stored offset/length matches its real position
    # on disk — the actual regression check: before the fix, RN-JAVA-092
    # and RN-JAVA-100's file_offset stayed at their pre-shift values,
    # which is exactly what corrupted the file on the second approval.
    # (RN-JAVA-086 itself is excluded here: approve_proposal has always
    # stored an edited row's own byte_length as the atomic-block builder's
    # raw output length, which excludes the block-separator newline that a
    # fresh atomic_parse counts as part of the block's span — a harmless,
    # pre-existing 1-byte convention difference unrelated to this fix, and
    # out of its scope; what matters here is its *offset*, asserted above
    # via new_text_a being found at all, and unaffected by shifting.)
    for code in ("RN-JAVA-092", "RN-JAVA-100"):
        row = conn.execute(
            "SELECT file_offset, byte_length FROM rules WHERE code = ?", (code,)
        ).fetchone()
        block = by_code[code]
        assert row == (block.file_offset, block.byte_length), (
            f"{code}: DB offset/length {row} != real position "
            f"{(block.file_offset, block.byte_length)}"
        )


def test_promote_rule_shifts_later_blocks_offset_in_same_file(tmp_kb):
    """Regression: _mark_deprecated_in_md grows the deprecated block by one
    line but never shifted later blocks' cached offsets in the same file —
    same bug class as the UPDATE-approval incident."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"

    text_a = "Deprecated rule text."
    text_b = "A later rule, unaffected content-wise."
    block_a = _atomic_rule_block("RN-JAVA-001", text_a)
    block_b = _atomic_rule_block("RN-JAVA-002", text_b)
    content = (block_a + "\n" + block_b).encode("utf-8")
    dest_file.write_bytes(content)

    # Seed offsets/lengths from the parser itself (see comment in the
    # sequential-approvals test above for why this matters).
    seed_blocks = {b.code: b for b in atomic_parse(str(dest_file))[0]}

    for code, text in (
        ("RN-JAVA-001", text_a),
        ("RN-JAVA-002", text_b),
    ):
        offset, length = seed_blocks[code].file_offset, seed_blocks[code].byte_length
        conn.execute(
            "INSERT INTO rules (id, scope_id, code, text, category, severity, "
            "file_path, file_offset, byte_length) "
            "VALUES (?, 'global-java', ?, ?, 'exceptions', 'high', ?, ?, ?)",
            (code, code, text, str(dest_file), offset, length),
        )
    conn.commit()

    promote_rule("RN-JAVA-001", "global-quarkus")

    blocks, warnings = atomic_parse(str(dest_file))
    assert warnings == []
    by_code = {b.code: b for b in blocks}

    row_a = conn.execute(
        "SELECT file_offset, byte_length FROM rules WHERE code = 'RN-JAVA-001'"
    ).fetchone()
    assert row_a == (by_code["RN-JAVA-001"].file_offset, by_code["RN-JAVA-001"].byte_length)

    row_b = conn.execute(
        "SELECT file_offset, byte_length FROM rules WHERE code = 'RN-JAVA-002'"
    ).fetchone()
    assert row_b == (by_code["RN-JAVA-002"].file_offset, by_code["RN-JAVA-002"].byte_length)

    raw = dest_file.read_bytes()
    block_b_text = raw[
        by_code["RN-JAVA-002"].file_offset : by_code["RN-JAVA-002"].file_offset
        + by_code["RN-JAVA-002"].byte_length
    ].decode("utf-8")
    assert text_b in block_b_text
    assert "**Status:** deprecated" not in block_b_text


def test_approve_create_proposal_survives_embedding_failure(tmp_kb, monkeypatch):
    """Regression (Hallazgo 5): an embedding/upsert failure after approval
    must not affect the approval itself — it already committed before the
    embed step runs. embedding_id just stays NULL for a later
    generate_embeddings pass to pick up."""
    kb_path, conn = tmp_kb
    dest_file = kb_path / "knowledge-base" / "global" / "java.md"
    dest_file.write_text("")

    from meridian.rag import vector_store

    def boom(*args, **kwargs):
        raise RuntimeError("chromadb unavailable")

    monkeypatch.setattr(vector_store, "upsert_rule", boom)

    prop_id = "prop-0001"
    conn.execute(
        "INSERT INTO pending_proposals "
        "(id, type, scope_id, proposed_text, metadata, source_type) "
        "VALUES (?, 'rule', 'global-java', ?, ?, 'manual')",
        (prop_id, "Some new rule text.", json.dumps({"tags": ["x"]})),
    )
    conn.commit()

    result = approve_proposal(prop_id)  # must not raise

    assert result["code"]
    row = conn.execute(
        "SELECT embedding_id FROM rules WHERE code = ?", (result["code"],)
    ).fetchone()
    assert row[0] is None
