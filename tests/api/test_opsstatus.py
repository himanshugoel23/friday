from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.opsstatus import ops_status_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ops_status_router(), prefix="/ops-status")
    return TestClient(app)


def test_off_without_token(monkeypatch):
    monkeypatch.delenv("FRIDAY_OPS_STATUS_TOKEN", raising=False)
    assert _client().get("/ops-status/anything-at-all-1234").status_code == 404


def test_wrong_and_right_token(monkeypatch, tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("commit abc\nOK\n")
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", "t" * 20)
    monkeypatch.setenv("FRIDAY_OPS_STATUS_FILE", str(f))
    c = _client()
    assert c.get("/ops-status/" + "x" * 20).status_code == 404
    r = c.get("/ops-status/" + "t" * 20)
    assert r.status_code == 200 and "commit abc" in r.text


def test_no_report_yet(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", "t" * 20)
    monkeypatch.setenv("FRIDAY_OPS_STATUS_FILE", str(tmp_path / "missing.txt"))
    assert "no report yet" in _client().get("/ops-status/" + "t" * 20).text


def test_logs_route_needs_the_token_too(monkeypatch, tmp_path):
    f = tmp_path / "logs.txt"
    f.write_text("line one\n")
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", "t" * 20)
    monkeypatch.setenv("FRIDAY_OPS_LOGS_FILE", str(f))
    c = _client()
    assert c.get("/ops-status/" + "x" * 20 + "/logs").status_code == 404
    assert "line one" in c.get("/ops-status/" + "t" * 20 + "/logs").text
