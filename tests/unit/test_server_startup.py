"""Unit tests for server.py's run_stdio/run_http startup sequencing
(Hallazgo 1 follow-up: embedder warm-up must start before mcp.run()
blocks, without requiring a real DB or a real model load)."""

from __future__ import annotations

from meridian import server


def test_run_stdio_warms_up_embedder_before_serving(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(server, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(
        server.embedder, "warm_up_in_background", lambda: calls.append("warm_up")
    )
    monkeypatch.setattr(
        server.mcp, "run", lambda **kwargs: calls.append("mcp.run")
    )

    server.run_stdio()

    assert calls == ["init_db", "warm_up", "mcp.run"]


def test_run_http_warms_up_embedder_before_serving(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(server, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(
        server.embedder, "warm_up_in_background", lambda: calls.append("warm_up")
    )
    monkeypatch.setattr(
        server, "generate_session_token", lambda: "fake-token"
    )
    monkeypatch.setattr(
        server.mcp, "run", lambda **kwargs: calls.append("mcp.run")
    )

    server.run_http(port=9999)

    assert calls == ["init_db", "warm_up", "mcp.run"]
