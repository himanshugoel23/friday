"""`friday serve` must reach Container(settings) and call uvicorn (regression: a function-local
`from ... import Container` elsewhere in main() made the name local and serve crashed with
UnboundLocalError on a real server, 2026-10-28). No network, nothing is served."""

from __future__ import annotations

from friday import cli


def test_serve_builds_container_and_runs_uvicorn(monkeypatch, tmp_path):
    import uvicorn

    monkeypatch.setenv("FRIDAY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/s.db")
    monkeypatch.setenv("FRIDAY_MODE", "simulator")
    called = {}

    def fake_run(app, host=None, port=None, **kw):
        called["app"] = app
        called["port"] = port

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert cli.main(["serve"]) == 0
    assert "app" in called
