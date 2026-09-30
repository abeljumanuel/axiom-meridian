"""Unit tests for version_info.py (Hallazgo 7: server version visibility)."""

import subprocess

from meridian import __version__
from meridian.utils.version_info import get_version_info


def test_get_version_info_against_real_repo():
    """Running from this actual git clone, the reported commit must match
    what git itself reports, independently computed."""
    info = get_version_info()

    assert info["version"] == __version__
    assert info["source_dir"] is not None
    assert info["commit"] is not None

    expected_commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert info["commit"] == expected_commit
    assert isinstance(info["dirty"], bool)
    assert info["commit_date"] is not None


def test_get_version_info_no_git_found(monkeypatch, tmp_path):
    """Outside any git clone (e.g. a wheel install), the git fields must
    all be None and nothing must raise."""
    import meridian.utils.version_info as version_info_module

    monkeypatch.setattr(version_info_module, "_repo_root", lambda: None)

    info = version_info_module.get_version_info()

    assert info["version"] == __version__
    assert info["source_dir"] is None
    assert info["commit"] is None
    assert info["commit_date"] is None
    assert info["dirty"] is None


def test_git_helper_returns_none_on_failure(tmp_path):
    """A command that fails (not a git repo) must return None, not raise."""
    from meridian.utils.version_info import _git

    result = _git("rev-parse", "--short", "HEAD", cwd=tmp_path)
    assert result is None


def test_git_helper_returns_none_for_missing_binary(monkeypatch, tmp_path):
    """git itself not being on PATH must degrade to None, not raise."""
    import meridian.utils.version_info as version_info_module

    def fake_run(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(version_info_module.subprocess, "run", fake_run)

    result = version_info_module._git("rev-parse", "HEAD", cwd=tmp_path)
    assert result is None
