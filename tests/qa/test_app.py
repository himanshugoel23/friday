"""The QA page: token auth and expiry, refusal to start, the API flow, notes file. Fakes only."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from friday.qa.app import create_qa_app
from friday.qa.config import APPROVAL_PHRASE
from friday.qa.safety import QaRefused
from tests.qa.conftest import NUMBER, World, make_qa, make_settings

TOKEN = "t" * 32


class Clock:
    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def client(world: World) -> tuple[TestClient, World, Clock]:
    clock = Clock()
    app = create_qa_app(
        world.settings, world.qa, runner=world.runner, token=TOKEN, ttl_hours=1, now=clock
    )
    return TestClient(app), world, clock


def api(path: str, token: str = TOKEN) -> str:
    return f"/qa/api/{token}{path}"


def test_page_needs_the_token(client) -> None:  # noqa: ANN001
    c, _, _ = client
    r = c.get(f"/qa/{TOKEN}/")
    assert r.status_code == 200 and "Friday QA" in r.text
    assert f"/qa/api/{TOKEN}" in r.text and "__API_BASE__" not in r.text
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    for bad in ("nope", TOKEN[:-1], ""):
        assert c.get(f"/qa/{bad}/").status_code == 404
    assert c.get(api("/scenarios", "wrong")).status_code == 404
    assert c.post(api("/run", "wrong"), json={"scenario": "salon_quote"}).status_code == 404


def test_token_expires(client) -> None:  # noqa: ANN001
    c, _, clock = client
    assert c.get(api("/config")).status_code == 200
    clock.t += 3601
    assert c.get(api("/config")).status_code == 404
    assert c.get(f"/qa/{TOKEN}/").status_code == 404


def test_page_refuses_to_start_unless_environment_is_right(tmp_path: Path) -> None:
    for kw in ({"mode": "simulator"}, {"profile": "default"}, {"pilot_allowed_numbers": []}):
        with pytest.raises(QaRefused):
            create_qa_app(make_settings(**kw), make_qa(tmp_path))
    with pytest.raises(QaRefused):
        create_qa_app(make_settings(), make_qa(tmp_path, live=False))


def test_config_shows_only_the_masked_number(client) -> None:  # noqa: ANN001
    c, _, _ = client
    body = c.get(api("/config")).json()
    assert body["number"].endswith("42") and NUMBER not in json.dumps(body)
    assert body["approval_phrase"] == APPROVAL_PHRASE and body["max_calls_per_day"] == 20


def test_scenarios_and_plan(client) -> None:  # noqa: ANN001
    c, _, _ = client
    rows = c.get(api("/scenarios")).json()["scenarios"]
    assert {"salon_quote", "urgent_escalation", "chat_text"} <= {r["id"] for r in rows}
    plan = c.post(api("/plan"), json={"scenario": "vendor_hotel"}).json()
    assert plan["real"] and plan["simulated"] and plan["steps"] and NUMBER not in json.dumps(plan)
    assert c.post(api("/plan"), json={"scenario": "nope"}).status_code == 404


def test_run_requires_the_phrase_and_reports_status(client) -> None:  # noqa: ANN001
    c, w, _ = client
    r = c.post(api("/run"), json={"scenario": "salon_quote", "approval": "yes"})
    assert r.status_code == 403 and r.json()["code"] == "not_approved"
    r = c.post(api("/run"), json={"scenario": "salon_quote", "approval": APPROVAL_PHRASE})
    assert r.status_code == 200
    run_id = r.json()["id"]
    run = c.get(api(f"/run/{run_id}")).json()
    assert run["scenario"] == "salon_quote" and run["real"] and run["simulated"]
    assert c.get(api("/current")).json()["run"]["id"] == run_id
    assert c.get(api("/run/zzzz")).status_code == 404
    assert w.calls.specs == [] or w.calls.specs[0].number == NUMBER


def test_notes_and_verdicts_go_to_notes_jsonl(client) -> None:  # noqa: ANN001
    c, w, _ = client
    assert (
        c.post(
            api("/note"), json={"scenario": "salon_quote", "verdict": "ok", "note": "sounded good"}
        ).status_code
        == 200
    )
    assert (
        c.post(
            api("/note"),
            json={"scenario": "salon_quote", "verdict": "bug", "note": "she said 9876543210"},
        ).status_code
        == 200
    )
    assert (
        c.post(api("/note"), json={"scenario": "salon_quote", "verdict": "bad"}).status_code == 422
    )
    assert c.post(api("/note"), json={"scenario": "nope", "verdict": "ok"}).status_code == 404
    rows = [json.loads(x) for x in (w.qa.path / "notes.jsonl").read_text().splitlines()]
    assert [r["verdict"] for r in rows] == ["ok", "bug"]
    assert "9876543210" not in rows[1]["note"]  # digits are masked on the way in
    assert w.store.verdicts()["salon_quote"]["verdict"] == "bug"


def test_line_decision_and_report(client) -> None:  # noqa: ANN001
    c, w, _ = client
    with w.guard.session("urgent_escalation", "r1"):
        from friday.qa import override

        override.note_pending_line("urgent", "urg.ring.urgent.hinglish")
    assert (
        c.post(
            api("/line"),
            json={"line_id": "urg.ring.urgent.hinglish", "decision": "reject", "note": "too stiff"},
        ).status_code
        == 200
    )
    assert c.post(api("/line"), json={"line_id": "x", "decision": "maybe"}).status_code == 422
    rep = c.get(api("/report")).json()
    assert rep["pending_lines"][0]["decision"] == "reject"
    assert "urg.ring.urgent.hinglish" in c.get(api("/report.txt")).text


def test_notes_file_is_gitignored() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "var/" in (root / ".gitignore").read_text().splitlines()
