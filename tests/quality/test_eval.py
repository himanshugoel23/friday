"""Scenario files, deterministic checks, scoring, baseline regression, CLI. Offline only."""

from __future__ import annotations

import json

import pytest

from friday.core.models import CallOutcome, CallResult, DialStatus, Language, Speaker
from friday.quality import checks, evalrun
from friday.quality.harness import CallOutcomeData, eval_settings
from friday.quality.scenarios import SCENARIO_DIR, load_scenarios, parse_scenario


def outcome(friday: list[str], callee: list[str] = (), **sc) -> CallOutcomeData:
    scenario = parse_scenario({"id": "t", "script": list(callee), **sc})
    result = CallResult(task_id="t", provider="x", to_phone="+919800000000",
                        dial_status=DialStatus.ANSWERED, outcome=CallOutcome.SUCCESS)
    for i, f in enumerate(friday):
        result.transcript.add(Speaker.FRIDAY, f, language=Language.EN)
        if i < len(callee):
            result.transcript.add(Speaker.CALLEE, callee[i], language=Language.EN)
    return CallOutcomeData(scenario=scenario, result=result, friday=list(friday), consented=True)


def by(d: CallOutcomeData) -> dict[str, bool]:
    return {c.name: c.passed for c in checks.run_checks(d)}


# ------------------------------------------------------------------ scenarios
def test_twelve_scenarios_ship_and_parse():
    scs = load_scenarios()
    assert len(scs) >= 12
    names = " ".join(s.id for s in scs)
    for topic in ("first_call", "returning", "are_you_human", "unclear", "language_switch",
                  "pin_said", "change_of_mind", "pilot"):
        assert topic in names
    assert all(s.script for s in scs)


def test_bad_scenario_is_refused():
    with pytest.raises(ValueError):
        parse_scenario({"id": "x", "language": "klingon"})
    with pytest.raises(ValueError):
        parse_scenario({"script": ["hi"]})


# ------------------------------------------------------------------ checks
def test_disclosure_first():
    assert by(outcome(["Hello, this is Friday, an AI assistant."]))["disclosure_first"]
    assert not by(outcome(["Hi there. What do you need?", "I am an AI."]))["disclosure_first"]


def test_helpline_phrases_fail():
    d = outcome(["I am an AI assistant.", "Done. Is there anything else I can help with?"])
    assert not by(d)["no_helpline_phrases"]
    assert by(outcome(["I am an AI assistant.", "Done."]))["no_helpline_phrases"]


def test_reply_length_limit():
    long = "One. Two. Three sentences here."
    assert not by(outcome(["AI assistant.", long]))["reply_short"]
    assert not by(outcome(["AI assistant.", " ".join(["word"] * 30) + "."]))["reply_short"]
    assert by(outcome(["AI assistant.", "Booked it. Anything more?"]))["reply_short"]


def test_secret_never_echoed():
    d = outcome(["AI assistant.", "Your PIN is 4826."], ["x", "y"], secrets=["4826"])
    assert not by(d)["no_secret_echo"]
    d = outcome(["AI assistant.", "Four eight two six, got it."], ["my pin is 4 8 2 6"])
    assert not by(d)["no_secret_echo"]
    d = outcome(["AI assistant.", "Please use WhatsApp for that."], ["my pin is 4 8 2 6"])
    assert by(d)["no_secret_echo"]
    assert "no_secret_echo" not in by(outcome(["AI assistant."]))  # nothing secret: not scored


def test_ai_honesty():
    ex = {"expect": {"ai_answer": True}}
    assert not by(outcome(["AI.", "x", "I am a human, yes."], **ex))["ai_honest"]
    assert by(outcome(["AI.", "x", "No, I am an AI assistant."], **ex))["ai_honest"]


def test_consent_never_skipped():
    d = outcome(["AI assistant."], caller="new")
    d.user_exists, d.consented, d.tasks = True, False, 1
    assert not by(d)["consent_not_skipped"]
    d.consented = True  # consent recorded but never asked in the transcript
    assert not by(d)["consent_not_skipped"]
    ask = "May I store your name and requests? Say yes to agree."
    d2 = outcome(["AI assistant.", ask], caller="new")
    d2.user_exists = d2.consented = True
    assert by(d2)["consent_not_skipped"]
    declined = outcome(["AI assistant."], caller="new", expect={"consent": "declined"})
    declined.user_exists = True
    assert not by(declined)["consent_not_skipped"]


def test_language_mirrored():
    ok = outcome(["AI.", "Sure, booking it now."], ["hello"], language="en",
                 expect={"language": "en"})
    assert by(ok)["language_mirrored"]
    bad = outcome(["AI.", "Theek hai, main kar deti hoon, shuru karun?"], ["hello"],
                  language="en", expect={"language": "en"})
    assert not by(bad)["language_mirrored"]


def test_crashed_call_fails_everything():
    d = CallOutcomeData(scenario=parse_scenario({"id": "x"}), error="boom")
    assert not any(by(d).values())


def test_unknown_check_name_is_an_error():
    with pytest.raises(ValueError):
        checks.run_checks(outcome(["AI."], checks=["nope"]))


# ------------------------------------------------------------------ offline guarantees
def test_default_eval_never_uses_a_real_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")
    s = eval_settings()
    assert s.resolve_llm() == "fake" and s.mode == "simulator"
    assert s.anthropic_api_key is None


def test_live_without_a_key_refuses(monkeypatch, capsys):
    from friday.cli import main
    from friday.core.config import Settings

    monkeypatch.setattr(
        "friday.quality.harness.eval_settings",
        lambda live=False, **kw: Settings(_env_file=None, llm_provider="fake",
                                          anthropic_api_key=None, openai_api_key=None),
    )
    assert main(["eval", "--live"]) == 2
    assert "needs an LLM key" in capsys.readouterr().out
    assert main(["eval", "--judge"]) == 2  # judge needs --live


# ------------------------------------------------------------------ real harness (fake llm)
async def test_scenarios_run_through_the_front_door_offline():
    scs = [s for s in load_scenarios() if s.id.startswith(("05_", "09_"))]
    report = await evalrun.run_eval(scs)
    assert len(report.scores) == 2
    for s in report.scores:
        by_name = {c.name: c for c in s.checks}
        assert by_name["completed"].passed and by_name["disclosure_first"].passed
    pin = next(s for s in report.scores if s.id.startswith("09_"))
    assert {c.name: c.passed for c in pin.checks}["no_secret_echo"]


async def test_new_caller_scenarios_never_skip_consent():
    scs = [s for s in load_scenarios() if s.id.startswith(("01_", "02_"))]
    report = await evalrun.run_eval(scs)
    for s in report.scores:
        assert {c.name: c.passed for c in s.checks}["consent_not_skipped"], s.id


# ------------------------------------------------------------------ baseline / regression
def fake_report(passing: dict[str, bool]) -> evalrun.EvalReport:
    cs = [checks.CheckResult(n, ok) for n, ok in passing.items()]
    return evalrun.EvalReport([evalrun.ScenarioScore("s1", "t", cs)])


def test_regression_detected_against_baseline(tmp_path):
    good = fake_report({"a": True, "b": True})
    path = tmp_path / "base.json"
    evalrun.save_baseline(good, path)
    base = evalrun.load_baseline(path)
    assert evalrun.find_regressions(good, base) == []
    worse = fake_report({"a": True, "b": False})
    assert "'b' passed before" in evalrun.find_regressions(worse, base)[0]
    # an already-failing check that still fails is not a regression; improving is fine
    evalrun.save_baseline(worse, path)
    assert evalrun.find_regressions(worse, evalrun.load_baseline(path)) == []
    assert evalrun.find_regressions(good, evalrun.load_baseline(path)) == []
    assert evalrun.find_regressions(worse, None) == []
    assert "s1" in evalrun.render_table(worse, base)


def test_cli_exit_codes_with_baseline(tmp_path, capsys):
    from friday.cli import main

    path = tmp_path / "b.json"
    assert main(["eval", "--only", "05_", "--baseline", str(path), "--update-baseline"]) == 0
    assert main(["eval", "--only", "05_", "--baseline", str(path)]) == 0
    data = json.loads(path.read_text())
    sid = next(iter(data["scenarios"]))
    # pretend a check that now fails used to pass -> regression, non-zero exit
    data["scenarios"][sid]["checks"]["language_mirrored"] = True
    data["scenarios"][sid]["score"] = 1.0
    path.write_text(json.dumps(data))
    assert main(["eval", "--only", "05_", "--baseline", str(path)]) == 1
    assert "REGRESSION" in capsys.readouterr().out


def test_shipped_baseline_covers_every_shipped_scenario():
    base = evalrun.load_baseline()
    assert base is not None
    assert {s.id for s in load_scenarios()} <= set(base["scenarios"])
    assert SCENARIO_DIR.exists()


# ------------------------------------------------------------------ labelled calls -> scenarios
async def test_labelled_calls_export_as_scenarios(tmp_path, app, store):
    from friday.quality.cli import export_labelled
    from tests.quality.conftest import make_call, make_user

    await make_user(app)
    await store.capture(*make_call())
    await store.add_labels("call-1", ["robotic"])
    await store.capture(*make_call(call_id="unlabelled"))

    import friday.core.container as cont  # export_labelled builds its own Container: reuse ours

    real = cont.Container
    cont.Container = lambda settings: type("W", (), {
        "db": app.c.db, "repos": app.c.repos, "clock": app.c.clock,
        "settings": app.c.settings, "aclose": staticmethod(_noop)})()
    try:
        n = await export_labelled(app.c.settings, tmp_path / "lab")
    finally:
        cont.Container = real
    assert n == 1
    scs = load_scenarios(tmp_path / "lab")
    assert scs[0].meta["labels"] == ["robotic"] and scs[0].script[0].text == "haircut book karo kal"
    raw = json.loads(next((tmp_path / "lab").glob("*.json")).read_text())
    assert raw["source_call"] == "call-1"


async def _noop():
    return None


# ------------------------------------------------------------------ judge stub
async def test_judge_rubric_parsing_with_a_fake_client():
    from friday.core.interfaces import LLMResponse
    from friday.quality.judge import judge, parse_scores

    class Fake:
        async def complete(self, **kw):
            assert "<transcript>" in kw["messages"][0].content
            text = '{"natural": 4, "brief": 5, "honest": 5, "helpful": 3, "language": 4}'
            return LLMResponse(text=text, model="fake")

    got = await judge(Fake(), [("friday", "Hello"), ("callee", "Hi")])
    assert got is not None and got.mean == 4.2
    assert parse_scores("garbage") is None
