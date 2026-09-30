"""Git commit/version info for the running process.

Lets `meridian version` and the `get_server_info` MCP tool answer "which
commit's code is actually running" for an editable install — Python
doesn't hot-reload a running process, so a `git pull` after the server
started leaves it silently serving the old code until restarted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from meridian import __version__


def _repo_root() -> Path | None:
    """Walk up from this file to find a .git directory.

    Only present for an editable install from a git clone (what
    scripts/install.sh always produces) — a wheel/sdist install has no
    .git anywhere above its installed location, and callers must handle
    that (this returns None, never raises).
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _git(*args: str, cwd: Path) -> str | None:
    """Run a git command, returning stripped stdout or None on any
    failure (non-zero exit, git not installed, timeout, ...)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_version_info() -> dict:
    """Return {"version", "source_dir", "commit", "commit_date", "dirty"}.

    The git fields are None when this isn't running from a git clone, or
    git itself isn't available — never raises either way.
    """
    root = _repo_root()
    info: dict = {
        "version": __version__,
        "source_dir": str(root) if root else None,
        "commit": None,
        "commit_date": None,
        "dirty": None,
    }
    if root is None:
        return info

    commit = _git("rev-parse", "--short", "HEAD", cwd=root)
    if commit is None:
        return info

    info["commit"] = commit
    info["commit_date"] = _git("log", "-1", "--format=%cI", cwd=root)
    status = _git("status", "--porcelain", cwd=root)
    info["dirty"] = bool(status) if status is not None else None
    return info
