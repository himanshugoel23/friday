"""The offline script author: knowledge file, prompt, loop, drafts directory, report, promote.

No network, no .env, no model: the default backend is the deterministic template generator, and
the loop is driven by a scripted fake author where a test needs a broken or unsafe draft.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from friday.brain.fake_llm import FakeLLM
from friday.cli import main as friday_main
from friday.core.config import Settings
from friday.playbooks.authoring import author, backends, offline, prompt
from friday.playbooks.authoring.author import OutputRefused, draft_sync, resolve_draft_dir
from friday.playbooks.authoring.backends import (
    AuthorReply,
    AuthorRequest,
    LiveRefused,
    LLMAuthor,
    OfflineAuthor,
)
from friday.playbooks.authoring.knowledge import (
    KnowledgeError,
    business_type_ids,
    get_business_type,
    load_knowledge,
    parse_knowledge,
)
from friday.playbooks.authoring.promote import promote
from friday.playbooks.model import DATA_DIR, load_playbook, playbook_files

TYPES = business_type_ids()


# --------------------------------------------------------------------------- helpers
class Scripted:
    """A fake author that plays back canned replies (a callable gets the request)."""

    is_live = False
    max_tokens = 0
    model = "scripted"
    name = "scripted fake author"

    def __init__(self, *replies: str | Callable[[AuthorRequest], str]) -> None:
        self.replies = list(replies)
        self.requests: list[AuthorRequest] = []

    async def generate(self, req: AuthorRequest) -> AuthorReply:
        self.requests.append(req)
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return AuthorReply(text=r(req) if callable(r) else r, model="scripted")

    def estimate_cost_inr(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


def good(bt_id: str) -> str:
    bt = get_business_type(bt_id)
    return prompt.format_reply(
        offline.render_playbook_yaml(bt, "test"), offline.render_personas_yaml(bt, "test")
    )


def variant(
    bt_id: str,
    pb: Callable[[dict[str, Any]], None] | None = None,
    personas: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    bt = get_business_type(bt_id)
    p, q = offline.build_playbook(bt), offline.build_personas(bt)
    if pb:
        pb(p)
    if personas:
        personas(q)
    return prompt.format_reply(offline.dump_yaml(p), offline.dump_yaml(q))


def break_goto(p: dict[str, Any]) -> None:
    p["steps"]["S2"]["branches"]["YES"] = {"goto": "S99"}


def no_dnc_flag(p: dict[str, Any]) -> None:
    """Valid for the validator, but Friday would not record the stop request: a safety failure."""
    p["defaults"]["STOP_CALLING"].pop("set", None)


def drop_dnc_persona(q: dict[str, Any]) -> None:
    q["personas"] = [x for x in q["personas"] if x["id"] != "dnc_request"]


def wrong_expectation(q: dict[str, Any]) -> None:
    q["personas"][0]["expect"] = {"outcome": "NO_SLOT"}


@pytest.fixture
def data_snapshot():
    before = sorted(p.name for p in DATA_DIR.iterdir())
    yield before
    assert sorted(p.name for p in DATA_DIR.iterdir()) == before, "a draft leaked into data/"


# --------------------------------------------------------------------------- knowledge file
def test_eight_business_types():
    assert set(TYPES) == {
        "clinic_appointment", "restaurant_table", "car_service", "home_services",
        "hotel_enquiry", "gym_membership", "dentist_appointment", "pharmacy_order",
    }


@pytest.mark.parametrize("bt_id", TYPES)
def test_business_types_schema(bt_id):
    bt = get_business_type(bt_id)
    assert bt.title and bt.who_answers and bt.hangup_behaviour and bt.language_mix
    assert len(bt.typical_opening) >= 2
    assert len(bt.caller_questions) >= 4
    assert bt.quotes.price_units and bt.quotes.typical_range and bt.quotes.not_on_phone
    assert len(bt.wont_say_on_phone) >= 2
    assert len(bt.surprises) >= 5
    # the awkward things the founder listed: at least a call-back and an advance/booking amount
    outcomes = {s.expect for s in bt.surprises}
    assert "CALL_BACK_LATER" in outcomes or any(s.hold_s for s in bt.surprises)
    assert any(s.at == "s5_ask" for s in bt.surprises) or any(
        "advance" in s.say.lower() or "booking amount" in s.say.lower() for s in bt.surprises
    )
    for s in bt.surprises:
        assert s.say.isascii() or s.say  # Roman Hinglish; the persona text is free but not empty
    assert bt.template.price_inr > 0
    assert not any(ord(ch) > 0x900 and ord(ch) < 0x97F for ch in str(bt.model_dump()))


def test_common_surprises_are_covered_somewhere():
    text = " ".join(
        s.say.lower() for bt in load_knowledge().business_types.values() for s in bt.surprises
    )
    for needle in ("whatsapp pe bhej do", "busy", "token system", "advance", "booking amount",
                   "walk-in", "hold", "visit karke batayenge"):
        assert needle in text, needle


def test_knowledge_rejects_bad_files():
    good_text = Path(author.__file__).with_name("business_types.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(good_text)
    data["business_types"]["clinic_appointment"]["surprises"][0]["at"] = "nonsense"
    with pytest.raises(KnowledgeError):
        parse_knowledge(yaml.safe_dump(data))
    data = yaml.safe_load(good_text)
    del data["business_types"]["car_service"]["who_answers"]
    with pytest.raises(KnowledgeError):
        parse_knowledge(yaml.safe_dump(data))
    with pytest.raises(KnowledgeError, match="unknown business type"):
        get_business_type("space_travel")


# --------------------------------------------------------------------------- offline drafts
@pytest.mark.parametrize("bt_id", TYPES)
def test_offline_draft_validates_and_dry_runs_clean(bt_id, tmp_path, data_snapshot):
    res = draft_sync(bt_id, backend=OfflineAuthor(), out_root=tmp_path)
    assert res.status == "ready_for_review", res.failures and res.failures[0].text()
    assert res.problems == []
    assert res.report is not None and res.report.safety_violations == []
    assert 20 <= len(res.report.runs) <= 25
    assert all(not r.failed for r in res.report.runs)
    assert res.usage.calls == 1 and res.usage.cost_inr == 0
    d = tmp_path / bt_id
    for name in ("playbook.yaml", "personas.yaml", "report.md", "dryrun.txt"):
        assert (d / name).exists(), name
    # the written file loads with the existing loader
    pb = load_playbook(d / "playbook.yaml")
    assert pb.id == bt_id and pb.language == "hinglish" and pb.commit_step == "S7"
    assert sum(1 for lid in pb.lines if pb.line_def(lid).commit) == 1
    assert not any(c.name.startswith(".stage") for c in d.iterdir())


def test_offline_draft_is_deterministic_and_needs_no_settings(tmp_path, monkeypatch):
    def boom() -> None:
        raise AssertionError("offline must never read settings / .env")

    monkeypatch.setattr(backends, "load_settings", boom)
    a = draft_sync("clinic_appointment", backend=OfflineAuthor(), out_root=tmp_path / "a")
    b = draft_sync("clinic_appointment", backend=OfflineAuthor(), out_root=tmp_path / "b")
    assert a.playbook_text == b.playbook_text and a.personas_text == b.personas_text


def test_offline_personas_include_the_awkward_ones(tmp_path):
    res = draft_sync("clinic_appointment", backend=OfflineAuthor(), out_root=tmp_path)
    ids = {p.id for p in res.pf.personas}
    assert {"doctor_busy", "token_system", "whatsapp_fees", "booking_amount", "dnc_request",
            "asks_otp", "hold_too_long", "delegated_over_ceiling", "pure_hindi"} <= ids
    assert next(p for p in res.pf.personas if p.id == "dnc_request").stop_request


def test_salon_playbook_is_untouched():
    names = sorted(playbook_files())
    assert "salon_booking" in names
    pb = load_playbook(DATA_DIR / "salon_booking.yaml")
    assert pb.id == "salon_booking" and len(pb.steps) == 12


# --------------------------------------------------------------------------- the loop
def test_validator_errors_are_fed_back_and_fixed(tmp_path):
    scripted = Scripted(variant("gym_membership", pb=break_goto), good("gym_membership"))
    res = draft_sync("gym_membership", backend=scripted, out_root=tmp_path, rounds=3)
    assert [r.action for r in res.log] == ["draft", "repair"]
    assert "S99" in "\n".join(res.log[1].found)
    second = scripted.requests[1]
    assert second.kind == "repair"
    assert "S99" in second.user and "unknown step" in second.user
    assert "<your_playbook>" in second.user
    assert res.status == "ready_for_review" and res.usage.calls == 2


def test_unfixable_playbook_stops_at_max_rounds_and_is_not_promotable(tmp_path):
    scripted = Scripted(variant("gym_membership", pb=break_goto))
    res = draft_sync("gym_membership", backend=scripted, out_root=tmp_path, rounds=2)
    assert res.status == "failed" and res.report is None
    assert res.usage.calls == 3  # the draft + 2 repair rounds, then it stops
    assert "Still invalid" in (tmp_path / "gym_membership" / "report.md").read_text("utf-8")
    out = promote("gym_membership", drafts_root=tmp_path, data_dir=tmp_path / "data",
                  confirm=lambda _p: "gym_membership")
    assert not out.ok and any("does not validate" in r for r in out.refusals)


def test_dry_run_failures_are_patched(tmp_path):
    scripted = Scripted(
        variant("dentist_appointment", personas=wrong_expectation), good("dentist_appointment")
    )
    res = draft_sync("dentist_appointment", backend=scripted, out_root=tmp_path)
    assert [r.action for r in res.log] == ["draft", "patch"]
    req = scripted.requests[1]
    assert req.kind == "patch" and "friendly_free_slot" in req.user
    assert "expected NO_SLOT" in req.user  # the dry-run detail went back to the model
    assert res.status == "ready_for_review"


def test_patch_that_edits_a_test_expectation_is_reported(tmp_path):
    def fix_by_editing_the_test(q: dict[str, Any]) -> None:
        q["personas"][0]["expect"] = {"outcome": "SLOT_OFFERED"}

    scripted = Scripted(
        variant("dentist_appointment", personas=wrong_expectation),
        variant("dentist_appointment", personas=fix_by_editing_the_test),
    )
    res = draft_sync("dentist_appointment", backend=scripted, out_root=tmp_path)
    assert res.expect_changes == ["friendly_free_slot: expected NO_SLOT -> SLOT_OFFERED"]
    report = (tmp_path / "dentist_appointment" / "report.md").read_text("utf-8")
    assert "Expectation changed" in report


def test_unreadable_reply_is_retried_once(tmp_path):
    scripted = Scripted("sorry, here is a poem", good("restaurant_table"))
    res = draft_sync("restaurant_table", backend=scripted, out_root=tmp_path)
    assert res.usage.calls == 2 and res.status == "ready_for_review"
    assert "could not be read" in scripted.requests[1].user


def test_two_unreadable_replies_fail_cleanly(tmp_path):
    scripted = Scripted("nothing useful", "still nothing")
    res = draft_sync("restaurant_table", backend=scripted, out_root=tmp_path)
    assert res.status == "failed" and res.unreadable and res.usage.calls == 2
    assert not (tmp_path / "restaurant_table" / "playbook.yaml").exists()
    assert (tmp_path / "restaurant_table" / "report.md").exists()


def test_a_wrong_playbook_id_and_thin_personas_are_rejected(tmp_path):
    def thin(q: dict[str, Any]) -> None:
        q["personas"] = q["personas"][:5]

    def wrong_id(p: dict[str, Any]) -> None:
        p["id"] = "something_else"

    problems, _pb, _pf = author.check_draft(
        "car_service",
        prompt.parse_reply(variant("car_service", pb=wrong_id, personas=thin)).playbook,
        prompt.parse_reply(variant("car_service", pb=wrong_id, personas=thin)).personas or "",
    )
    joined = "\n".join(problems)
    assert "id must be exactly 'car_service'" in joined
    assert "only 5" in joined


def test_persona_reply_keys_must_be_real_line_ids(tmp_path):
    def typo(q: dict[str, Any]) -> None:
        q["personas"][0]["replies"]["s9_nothing"] = "hmm"

    scripted = Scripted(variant("car_service", personas=typo), good("car_service"))
    res = draft_sync("car_service", backend=scripted, out_root=tmp_path)
    assert "s9_nothing" in scripted.requests[1].user
    assert res.status == "ready_for_review"


def test_model_call_budget_is_a_hard_limit(tmp_path):
    scripted = Scripted("junk")  # always unreadable
    res = draft_sync("car_service", backend=scripted, out_root=tmp_path, rounds=0)
    assert res.usage.calls <= 2
    plan = author.plan_budget(scripted, rounds=3)
    assert plan.max_calls == 8


# --------------------------------------------------------------------------- safety is never waived
def test_safety_violation_blocks_and_is_reported(tmp_path):
    scripted = Scripted(variant("clinic_appointment", pb=no_dnc_flag))
    res = draft_sync("clinic_appointment", backend=scripted, out_root=tmp_path, rounds=1)
    assert res.status == "blocked_safety"
    assert ("dnc_request", "a stop request was not honoured") in res.safety_violations
    assert scripted.requests[-1].kind == "patch"
    assert "cannot be waived" in scripted.requests[-1].user
    report = (tmp_path / "clinic_appointment" / "report.md").read_text("utf-8")
    assert "BLOCKED" in report and "stop request was not honoured" in report


def test_removing_the_failing_test_does_not_waive_a_safety_violation(tmp_path):
    scripted = Scripted(
        variant("clinic_appointment", pb=no_dnc_flag),
        variant("clinic_appointment", pb=no_dnc_flag, personas=drop_dnc_persona),
    )
    res = draft_sync("clinic_appointment", backend=scripted, out_root=tmp_path, rounds=2)
    assert res.status == "blocked_safety"
    assert res.safety_waived == ["dnc_request"]
    assert any("required safety test" in p for p in res.problems)  # fed back to the model too
    report = (tmp_path / "clinic_appointment" / "report.md").read_text("utf-8")
    assert "removed from the test set" in report
    out = promote("clinic_appointment", drafts_root=tmp_path, data_dir=tmp_path / "data",
                  confirm=lambda _p: "clinic_appointment")
    assert not out.ok and any("required safety test" in r for r in out.refusals)


def test_promote_refuses_a_draft_with_safety_violations(tmp_path):
    unsafe = Scripted(variant("clinic_appointment", pb=no_dnc_flag))
    draft_sync("clinic_appointment", backend=unsafe, out_root=tmp_path, rounds=0)
    data = tmp_path / "data"
    called: list[str] = []
    out = promote("clinic_appointment", drafts_root=tmp_path, data_dir=data,
                  confirm=lambda p: called.append(p) or "clinic_appointment")
    assert not out.ok and called == []  # refused before even asking for confirmation
    assert any("SAFETY" in r for r in out.refusals)
    assert not data.exists()


# --------------------------------------------------------------------------- promote
def _make_draft(tmp_path: Path, bt_id: str = "pharmacy_order") -> Path:
    draft_sync(bt_id, backend=OfflineAuthor(), out_root=tmp_path)
    return tmp_path


def test_promote_needs_the_typed_business_type_name(tmp_path):
    _make_draft(tmp_path)
    data = tmp_path / "data"
    for typed in ("", "yes", "y", "PHARMACY_ORDER", "pharmacy"):
        out = promote("pharmacy_order", drafts_root=tmp_path, data_dir=data,
                      confirm=lambda _p, t=typed: t)
        assert not out.ok and any("not confirmed" in r for r in out.refusals)
        assert not data.exists()
    prompts: list[str] = []
    out = promote("pharmacy_order", drafts_root=tmp_path, data_dir=data,
                  confirm=lambda p: prompts.append(p) or "pharmacy_order")
    assert out.ok and "pharmacy_order" in prompts[0]
    assert (data / "pharmacy_order.yaml").exists()
    assert (data / "pharmacy_order.personas.yaml").exists()
    pb = load_playbook(data / "pharmacy_order.yaml")  # still valid after the header rewrite
    assert pb.id == "pharmacy_order"
    assert "DRAFT" not in (data / "pharmacy_order.yaml").read_text("utf-8").split("version:")[0]


def test_promote_eof_means_no(tmp_path):
    _make_draft(tmp_path)

    def eof(_p: str) -> str:
        raise EOFError

    out = promote("pharmacy_order", drafts_root=tmp_path, data_dir=tmp_path / "data", confirm=eof)
    assert not out.ok


def test_promote_never_overwrites_and_rechecks_the_edited_file(tmp_path):
    _make_draft(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "pharmacy_order.yaml").write_text("existing", encoding="utf-8")
    out = promote("pharmacy_order", drafts_root=tmp_path, data_dir=data,
                  confirm=lambda _p: "pharmacy_order")
    assert not out.ok and any("already exists" in r for r in out.refusals)
    assert (data / "pharmacy_order.yaml").read_text("utf-8") == "existing"
    # a human edit that breaks the draft is caught at promote time
    (data / "pharmacy_order.yaml").unlink()
    pfile = tmp_path / "pharmacy_order" / "playbook.yaml"
    pfile.write_text(pfile.read_text("utf-8").replace("goto: S3r", "goto: S404", 1), "utf-8")
    out = promote("pharmacy_order", drafts_root=tmp_path, data_dir=data,
                  confirm=lambda _p: "pharmacy_order")
    assert not out.ok and any("S404" in r for r in out.refusals)


def test_promote_rejects_odd_names_and_missing_drafts(tmp_path):
    for name in ("../etc", "a b", "X", "salon_booking/../x"):
        assert not promote(name, drafts_root=tmp_path, confirm=lambda _p, n=name: n).ok
    out = promote("clinic_appointment", drafts_root=tmp_path, data_dir=tmp_path / "d",
                  confirm=lambda _p: "clinic_appointment")
    assert not out.ok and "no draft found" in out.refusals[0]


# --------------------------------------------------------------------------- drafts directory
def test_drafts_never_land_outside_the_drafts_dir(tmp_path, data_snapshot):
    root = tmp_path / "drafts"
    res = draft_sync("hotel_enquiry", backend=OfflineAuthor(), out_root=root)
    written = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert written and all(root in p.parents for p in written)
    assert all(p.parent == root / "hotel_enquiry" for p in res.files.values())


@pytest.mark.parametrize("bad", [DATA_DIR, DATA_DIR / "sub", DATA_DIR.parent])
def test_output_inside_playbook_data_is_refused(bad):
    with pytest.raises(OutputRefused):
        resolve_draft_dir(bad, "clinic_appointment")
    with pytest.raises(OutputRefused):
        draft_sync("clinic_appointment", backend=OfflineAuthor(), out_root=bad)


def test_default_drafts_dir_is_under_var():
    assert resolve_draft_dir(None, "car_service").parts[-3:] == (
        "var", "playbook_drafts", "car_service")


def test_unknown_business_type():
    with pytest.raises(KnowledgeError):
        draft_sync("space_travel", backend=OfflineAuthor())


# --------------------------------------------------------------------------- report
def test_report_contents(tmp_path):
    draft_sync("dentist_appointment", backend=Scripted(
        variant("dentist_appointment", personas=wrong_expectation), good("dentist_appointment")),
        out_root=tmp_path)
    text = (tmp_path / "dentist_appointment" / "report.md").read_text("utf-8")
    for needle in (
        "# Draft playbook: Dentist appointment", "READY FOR YOUR REVIEW", "## In plain words",
        "### The steps", "12 steps", "## What the simulated businesses did", "25 of 25",
        "## What failed and what was fixed", "Round 1", "friendly_free_slot",
        "## Safety result", "No safety violation", "## Lines needing human review",
        "COMMIT line", "AI disclosure (spoken first)", "friday say",
        "friday playbook promote dentist_appointment", "Nothing is ever promoted automatically",
    ):
        assert needle in text, needle


def test_report_for_a_blocked_draft_says_so(tmp_path):
    unsafe = Scripted(variant("clinic_appointment", pb=no_dnc_flag))
    draft_sync("clinic_appointment", backend=unsafe, out_root=tmp_path, rounds=0)
    text = (tmp_path / "clinic_appointment" / "report.md").read_text("utf-8")
    assert "BLOCKED: SAFETY" in text and "never" in text.lower()


# --------------------------------------------------------------------------- the prompt
def test_prompt_carries_format_rules_and_the_salon_example():
    system = prompt.system_prompt()
    salon = (DATA_DIR / "salon_booking.yaml").read_text(encoding="utf-8")
    assert salon in system  # the full salon playbook as the worked example
    from friday.playbooks.intents import INTENTS

    assert all(i in system for i in INTENTS)  # the closed intent set
    for needle in ("Roman script", "ek AI assistant", "commit: true", "OTP", "JARVIS",
                   "approval", "20 to 25", PLAYBOOK_MARK(), prompt.PERSONAS_MARK, "stop_request"):
        assert needle in system, needle
    bt = get_business_type("clinic_appointment")
    user = prompt.draft_prompt(bt)
    assert "clinic_appointment" in user and "Receptionist" in user and "token" in user.lower()
    assert "price_inr" not in user.split("<business_type>")[1]  # offline hints are not leaked


def PLAYBOOK_MARK() -> str:  # noqa: N802
    return prompt.PLAYBOOK_MARK


def test_reply_parsing():
    r = prompt.parse_reply(
        "chatter\n=== PLAYBOOK ===\n```yaml\nversion: 1\n```\n=== PERSONAS ===\n"
        "version: 1\n=== END ==="
    )
    assert r.playbook == "version: 1\n" and r.personas == "version: 1\n"
    only = prompt.parse_reply("=== PLAYBOOK ===\nx: 1\n=== END ===", personas_required=False)
    assert only.personas is None
    with pytest.raises(prompt.ReplyParseError):
        prompt.parse_reply("no markers")
    with pytest.raises(prompt.ReplyParseError):
        prompt.parse_reply("=== PLAYBOOK ===\nx: 1\n=== END ===")


# ------------------------------------------------------------------ live path (fake LLM only)
def _offline_settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, mode="simulator", env="test", anthropic_api_key=None,
                    openai_api_key=None, **kw)


def test_live_refuses_without_an_llm_key(monkeypatch):
    monkeypatch.setattr(backends, "load_settings", lambda: _offline_settings())
    with pytest.raises(LiveRefused, match="LLM key"):
        backends.build_live_author()


def test_cli_live_refuses_without_a_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(backends, "load_settings", lambda: _offline_settings())
    rc = friday_main(["playbook", "draft", "clinic_appointment", "--live", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2 and "REFUSED" in out and "needs an LLM key" in out
    assert not list(tmp_path.iterdir())


def test_authoring_purpose_is_routed_to_a_bigger_but_not_opus_model():
    s = _offline_settings()
    assert s.model_for("playbook_author") == "claude-sonnet-5-5"
    assert "opus" not in s.model_for("playbook_author")
    assert s.model_for("interpret") == "claude-haiku-5-5"  # background purposes unchanged
    assert s.model_for("call_turn") == "claude-sonnet-5-5"
    assert "playbook_author" in s.llm_models


def test_llm_author_runs_through_the_llm_abstraction_with_cost_and_budget(tmp_path):
    llm = FakeLLM()
    llm.script("playbook_author", good("gym_membership"))
    live = LLMAuthor(llm=llm, model="claude-sonnet-5-5", provider="anthropic", max_tokens=9000)
    plan = author.plan_budget(live, rounds=3)
    text = plan.describe()
    assert "at most 3 improvement round" in text and "9000 output tokens" in text
    assert "Rs" in text and plan.worst_case_cost_inr > 0 and plan.max_calls == 8
    res = draft_sync("gym_membership", backend=live, out_root=tmp_path, rounds=3)
    assert res.status == "ready_for_review" and res.live
    assert llm.calls[0].purpose == "playbook_author" and llm.calls[0].model == "claude-sonnet-5-5"
    assert "Friday" in llm.calls[0].system
    assert res.usage.calls == 1 and res.usage.input_tokens > 0 and res.usage.cost_inr > 0
    report = (tmp_path / "gym_membership" / "report.md").read_text("utf-8")
    assert "estimated cost about Rs" in report and "Worst case allowed" in report


# --------------------------------------------------------------------------- CLI
def test_cli_draft_offline_then_promote(tmp_path, monkeypatch, capsys):
    rc = friday_main(["playbook", "draft", "gym_membership", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "No model is called" in out and "ready_for_review" in out
    monkeypatch.setattr(builtins, "input", lambda _p="": "nope")
    rc = friday_main(["playbook", "promote", "gym_membership", "--from", str(tmp_path)])
    assert rc == 2 and "not confirmed" in capsys.readouterr().out
    assert "gym_membership" not in playbook_files()


def test_cli_types_and_unknown_type(capsys, tmp_path):
    assert friday_main(["playbook", "types"]) == 0
    assert "clinic_appointment" in capsys.readouterr().out
    assert friday_main(["playbook", "draft", "moon_base", "--out", str(tmp_path)]) == 2
    assert friday_main(["playbook", "draft", "car_service", "--rounds", "99"]) == 2
    assert friday_main(["playbook", "draft", "car_service", "--out", str(DATA_DIR)]) == 2
