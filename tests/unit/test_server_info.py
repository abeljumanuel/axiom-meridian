"""Unit tests for tools/server_info.py (Hallazgo 7)."""

from meridian.tools.server_info import build_server_info_response


def test_same_commit_is_not_stale():
    startup = {"version": "0.1.0", "source_dir": "/repo", "commit": "abc123", "commit_date": "2026-09-30", "dirty": False}
    current = {"commit": "abc123", "dirty": False}

    result = build_server_info_response(startup, current, "2026-09-30T14:00:00Z")

    assert result["stale"] is False
    assert result["note"] is None
    assert result["commit_at_startup"] == "abc123"
    assert result["commit_now"] == "abc123"
    assert result["version"] == "0.1.0"
    assert result["started_at"] == "2026-09-30T14:00:00Z"


def test_different_commit_is_stale():
    startup = {"version": "0.1.0", "source_dir": "/repo", "commit": "abc123", "commit_date": "2026-09-30", "dirty": False}
    current = {"commit": "def456", "dirty": False}

    result = build_server_info_response(startup, current, "2026-09-30T14:00:00Z")

    assert result["stale"] is True
    assert result["note"] is not None
    assert "restart" in result["note"].lower()


def test_unknown_startup_commit_is_never_stale():
    """No basis for comparison (e.g. a non-git install) must never claim
    staleness — that would be a false positive, not a safe default."""
    startup = {"version": "0.1.0", "source_dir": None, "commit": None, "commit_date": None, "dirty": None}
    current = {"commit": None, "dirty": None}

    result = build_server_info_response(startup, current, "2026-09-30T14:00:00Z")

    assert result["stale"] is False
    assert result["note"] is None


def test_unknown_current_commit_is_never_stale():
    startup = {"version": "0.1.0", "source_dir": "/repo", "commit": "abc123", "commit_date": "2026-09-30", "dirty": False}
    current = {"commit": None, "dirty": None}

    result = build_server_info_response(startup, current, "2026-09-30T14:00:00Z")

    assert result["stale"] is False
