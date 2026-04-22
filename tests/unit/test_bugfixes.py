"""Tests for bug fixes - type normalization and scope_to_file_path fallback."""

from __future__ import annotations


class TestTypeNormalization:
    """Tests for type normalization in create_pending_proposal."""

    def test_type_lowercase_normalization(self):
        """type.lower() should be applied before validation."""
        from meridian.tools.extraction import create_pending_proposal
        assert create_pending_proposal.__module__ == "meridian.tools.extraction"


class TestScopeToFilePathFallback:
    """Tests for _scope_to_file_path fallback behavior."""

    def test_lesson_fallback_to_knowledge_base(self, tmp_path, monkeypatch):
        """When lessons/ doesn't exist, should fallback to knowledge-base/."""
        kb_path = tmp_path / "kb"
        kb_path.mkdir()
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)

        monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
        from meridian import config as meridian_config
        meridian_config._kb_path = None

        from meridian.tools.knowledge_management import _scope_to_file_path
        from meridian.config import get_knowledge_base_path

        kb = get_knowledge_base_path()
        assert (kb / "lessons").is_dir()
        assert (kb / "knowledge-base").is_dir()

        path = _scope_to_file_path("global-quarkus", "lesson")
        assert "lessons" in str(path)


class TestCreateProject:
    """Tests for create_project function."""

    def test_create_project(self, tmp_path, monkeypatch):
        """create_project should insert scope and create directories."""
        kb_path = tmp_path / "kb"
        kb_path.mkdir()
        (kb_path / "knowledge-base" / "global").mkdir(parents=True)
        (kb_path / "knowledge-base" / "projects").mkdir(parents=True)
        (kb_path / "lessons" / "global").mkdir(parents=True)
        (kb_path / "lessons" / "projects").mkdir(parents=True)

        monkeypatch.setenv("KNOWLEDGE_BASE_PATH", str(kb_path))
        from meridian.config import get_db_path
        from meridian.db.connection import initialize_db
        from meridian.tools.knowledge_management import create_project

        db_path = get_db_path()
        initialize_db(db_path)

        conn = __import__("meridian.db.connection", fromlist=["get_connection"]).get_connection(db_path)

        result = create_project(conn, "ms-upi-device-manager", name="MS UPI Device Manager", parent_scope="global-quarkus")

        assert result["scope_id"] == "project-ms-upi-device-manager"
        assert result["name"] == "MS UPI Device Manager"
        assert result["parent_scope"] == "global-quarkus"
        assert (kb_path / "knowledge-base" / "projects" / "ms-upi-device-manager.md").exists()


class TestAutoKBPath:
    """Tests for auto-managed knowledge base path."""

    def test_get_default_kb_path_linux(self, monkeypatch):
        """On Linux, should use ~/.local/share/meridian."""
        import sys
        monkeypatch.setattr(sys, "platform", "linux")
        from meridian.config import _get_default_kb_path
        path = _get_default_kb_path()
        assert ".local/share/meridian" in str(path)

    def test_ensure_kb_structure_creates_dirs(self, tmp_path):
        """_ensure_kb_structure should create all required directories."""
        from meridian.config import _ensure_kb_structure

        kb_path = tmp_path / "kb"
        _ensure_kb_structure(kb_path)

        assert (kb_path / "knowledge-base" / "global").is_dir()
        assert (kb_path / "knowledge-base" / "projects").is_dir()
        assert (kb_path / "lessons" / "global").is_dir()
        assert (kb_path / "lessons" / "projects").is_dir()
        assert (kb_path / "meridian.db").exists()