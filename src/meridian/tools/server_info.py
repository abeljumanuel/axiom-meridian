"""Server process info — version/commit visibility (Hallazgo 7)."""

from __future__ import annotations


def build_server_info_response(
    startup_info: dict, current_info: dict, started_at: str
) -> dict:
    """Combine the commit captured at server startup with a fresh read of
    it now, and decide whether the running process's code is stale
    relative to what's on disk.

    `stale` is only ever True when both commits are known and differ —
    a non-git install (commit is None on either side) has no basis for
    comparison and is reported as not stale, not as an error.
    """
    startup_commit = startup_info.get("commit")
    current_commit = current_info.get("commit")
    stale = (
        startup_commit is not None
        and current_commit is not None
        and startup_commit != current_commit
    )

    return {
        "version": startup_info.get("version"),
        "started_at": started_at,
        "source_dir": startup_info.get("source_dir"),
        "commit_at_startup": startup_commit,
        "commit_at_startup_date": startup_info.get("commit_date"),
        "commit_now": current_commit,
        "dirty": current_info.get("dirty"),
        "stale": stale,
        "note": (
            "Code on disk has changed since this server process started "
            "— restart to pick it up."
            if stale
            else None
        ),
    }
