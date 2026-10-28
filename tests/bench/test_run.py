"""Bench run over the real in-process pipeline with fakes only, plus classification and the ops route."""

from __future__ import annotations

import argparse
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.opsstatus import ops_status_router
from friday.bench import runner as RUN
from friday.bench import rules as R
from friday.bench import scenarios as S
from friday.bench.cli import add_parser, run_command

TOKEN = "b" * 20


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for n in ("FRIDAY_MODE", "FRIDAY_PROFILE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FRIDAY_LLM_PROVIDER",
              "FRIDAY_OPS_BENCH_ENABLED", "FRIDAY_OPS_BENCH_FILE", "FRIDAY_OPS_STATUS_TOKEN"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.chdir("/")  # no .env to pick up


def _args(argv):
    p = argparse.ArgumentParser()
    add_parser(p.add_subparsers(dest="cmd", required=True))
    return p.parse_args(argv)


def test_classification():
    sc = S.parse({"scenarios": [{"id": "x", "category": "c", "capability": "email", "messages": ["m"],
                                 "expected_today": "needs connector", "rules": ["not_flat_refusal", "has_link"]}]})[0]
    honest = R.Reply(["Gmail abhi set up nahi hai, email paste kijiye."])
    assert RUN.classify(sc, honest, RUN.evaluate(sc, honest)) == RUN.NEEDS
    flat = R.Reply(["Main theek se samajh nahi payi."])
    assert RUN.classify(sc, flat, RUN.evaluate(sc, flat)) == RUN.FAIL
    linked = R.Reply(["Gmail: https://example.test/connect"])
    assert RUN.classify(sc, linked, RUN.evaluate(sc, linked)) == RUN.PASS


def test_scoreboard_math():
    mk = lambda i, cat, st, rules: RUN.Result(i, cat, "web", "works", st, ["m"], "r", [], [{"rule": r, "detail": ""} for r in rules])  # noqa: E731
    rep = RUN.build_report([mk("a", "x", RUN.PASS, []), mk("b", "x", RUN.FAIL, ["r1", "r2"]), mk("c", "y", RUN.NEEDS, ["r1"])], mode="fake")
    sb = rep["scoreboard"]
    assert (sb["total"], sb["pass"], sb["fail"], sb["needs_connector"]) == (3, 1, 1, 1)
    assert sb["by_category"]["x"]["total"] == 2 and sb["top_failing_rules"][0] == ("r1", 2)
    text = RUN.render(rep)
    assert text.index("TOTAL 3") < text.index("[PASS] a") and "FAILED RULE r2" in text


def test_fake_bench_run_writes_report(tmp_path, capsys):
    out = tmp_path / "bench"
    args = _args(["bench", "run", "--fake", "--scenario", "gmail_check", "--scenario", "interview_tomorrow", "--out", str(out)])
    assert run_command(args) == 0
    data = json.loads((out / "last.json").read_text(encoding="utf-8"))
    assert data["mode"] == "fake" and data["scoreboard"]["total"] == 2
    ids = {r["id"] for r in data["results"]}
    assert ids == {"gmail_check", "interview_tomorrow"}
    assert all(r["reply"] for r in data["results"])  # the real pipeline answered both
    txt = (out / "last.txt").read_text(encoding="utf-8")
    assert txt.startswith("FRIDAY INSTINCT-PARITY BENCHMARK") and "TOTAL 2" in txt and "reply:" in txt


def test_unknown_scenario_and_list(capsys):
    assert run_command(_args(["bench", "run", "--fake", "--scenario", "nope"])) == 2
    assert run_command(_args(["bench", "list"])) == 0
    assert "gmail_check" in capsys.readouterr().out


def test_pipeline_error_is_a_fail_not_a_crash(tmp_path):
    async def broken(**kw):
        raise RuntimeError("boom")

    sc = S.load()[:1]
    rep = __import__("asyncio").run(RUN.run(sc, fake=True, world_factory=broken))
    assert rep["scoreboard"]["fail"] == 1 and rep["results"][0]["failed"][0]["rule"] == "pipeline_error"


def _client():
    app = FastAPI()
    app.include_router(ops_status_router(), prefix="/ops-status")
    return TestClient(app)


def test_bench_route_auth_and_switch(tmp_path, monkeypatch):
    f = tmp_path / "last.txt"
    f.write_text("FRIDAY INSTINCT-PARITY BENCHMARK\nTOTAL 1", encoding="utf-8")
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", TOKEN)
    monkeypatch.setenv("FRIDAY_OPS_BENCH_FILE", str(f))
    c = _client()
    assert c.get(f"/ops-status/{TOKEN}/bench").status_code == 404  # switch off
    monkeypatch.setenv("FRIDAY_OPS_BENCH_ENABLED", "true")
    assert c.get(f"/ops-status/{'x' * 20}/bench").status_code == 404  # wrong token
    r = c.get(f"/ops-status/{TOKEN}/bench")
    assert r.status_code == 200 and r.text.startswith("FRIDAY INSTINCT-PARITY BENCHMARK")
    f.unlink()
    assert "no report yet" in c.get(f"/ops-status/{TOKEN}/bench").text
    monkeypatch.delenv("FRIDAY_OPS_STATUS_TOKEN")
    assert c.get(f"/ops-status/{TOKEN}/bench").status_code == 404
