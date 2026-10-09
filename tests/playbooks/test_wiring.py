"""Salon booking tasks use the playbook; everything else keeps the LLM-driven policy."""

from __future__ import annotations

import asyncio

import pytest

from friday.brain.fake_llm import FakeLLM
from friday.brain.service import FridayBrain
from friday.core.config import Settings
from friday.core.models import (
    CallAction,
    CallActionType,
    Delegation,
    Task,
    TaskSpec,
    TaskType,
    Transcript,
)
from friday.playbooks.engine import PlaybookPolicy, RoutingCallPolicy
from friday.playbooks.select import matching_playbook, playbook_fields
from tests.brain.conftest import make_ctx

from .conftest import make_brief

PHONE = "+918040000001"


def _task(**spec_kw) -> Task:
    spec = TaskSpec(**{
        "type": TaskType.BOOKING, "goal": "Book a haircut for me", "business_name": "Looks",
        "business_phone": PHONE, "category": "salon", "when_text": "kal shaam", **spec_kw,
    })
    return Task(id="t1", requester_user_id="u1", type=spec.type, spec=spec)


@pytest.fixture
def brain() -> FridayBrain:
    return FridayBrain(FakeLLM(), Settings(_env_file=None, mode="simulator", env="test",
                                           anthropic_api_key=None, openai_api_key=None))


async def test_salon_booking_task_gets_a_scripted_brief(brain):
    brief = await brain.build_call_brief(make_ctx(), _task())
    assert brief.playbook == "salon_booking"
    assert brief.playbook_inputs["user_first_name"] == "Ankit"
    assert brief.playbook_inputs["service"] == "haircut"
    assert brief.playbook_inputs["date_window"] == "kal shaam"
    assert brief.disclosure() == "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat salon se ho rahi hai?"  # noqa: E501
    assert not brief.can_commit([])


async def test_other_business_types_keep_the_llm_policy(brain):
    for spec in (
        {"category": "restaurant", "goal": "Book a table for 4"},
        {"category": "clinic", "goal": "Book a doctor"},
        {"type": TaskType.QUOTE, "goal": "AC service quote", "category": "ac repair"},
        {"type": TaskType.ENQUIRY, "goal": "Is the salon open?", "category": "salon"},
    ):
        brief = await brain.build_call_brief(make_ctx(), _task(**spec))
        assert brief.playbook is None and brief.disclosure_text is None, spec


async def test_confirmation_callback_stays_with_the_llm_policy(brain):
    task = _task()
    task.approved_terms = "6 PM, Rs 400"
    brief = await brain.build_call_brief(make_ctx(), task)
    assert brief.playbook is None and brief.can_commit([])


async def test_missing_when_means_no_playbook(brain):
    brief = await brain.build_call_brief(make_ctx(), _task(when_text=None))
    assert brief.playbook is None  # a required input is unknown: the normal policy handles it


async def test_budget_stylist_and_delegation_are_carried(brain):
    from friday.core.models import Budget

    task = _task(budget=Budget(max_inr=600), constraints=["stylist Amit"],
                 delegation=Delegation(granted=True, max_price_inr=800))
    brief = await brain.build_call_brief(make_ctx(), task)
    assert brief.playbook_inputs["budget"] == "600"
    assert brief.playbook_inputs["stylist_pref"] == "Amit"
    assert brief.delegation.granted


async def test_a_resolved_window_is_spoken_in_hinglish(brain):
    from datetime import datetime, timedelta

    from friday.core.clock import IST

    start = datetime(2026, 10, 8, 17, 0, tzinfo=IST)  # "kal", 5 pm (ctx.now is 7 Oct, 10:00 IST)
    brief = await brain.build_call_brief(
        make_ctx(), _task(when_text="Thu 8 Oct 5 PM–8 PM", window_start=start,
                          window_end=start + timedelta(hours=3)))
    assert brief.playbook_inputs["date_window"] == "kal shaam 5 se 8 baje ke beech"


async def test_english_when_words_become_hinglish(brain):
    brief = await brain.build_call_brief(make_ctx(), _task(when_text="tomorrow evening"))
    assert brief.playbook_inputs["date_window"] == "kal shaam"


async def test_setting_can_switch_playbooks_off():
    off = FridayBrain(FakeLLM(), Settings(_env_file=None, mode="simulator", env="test",
                                          anthropic_api_key=None, openai_api_key=None,
                                          playbooks_enabled=False))
    brief = await off.build_call_brief(make_ctx(), _task())
    assert brief.playbook is None


def test_matching_by_category_or_keyword():
    assert matching_playbook("booking", "salon", "x").id == "salon_booking"
    assert matching_playbook("booking", None, "Book a haircut").id == "salon_booking"
    assert matching_playbook("booking", "restaurant", "table for two") is None
    assert matching_playbook("quote", "salon", "haircut quote") is None
    assert playbook_fields(task_type="booking", category="salon", goal="x", item=None,
                           when_text="kal shaam", preferred_times=[], requester_name="Ankit Sharma",
                           beneficiary_name=None, constraints=[], budget_max_inr=None)["playbook"]


class Base:
    def __init__(self) -> None:
        self.calls = 0

    async def next_call_action(self, brief, transcript, answers):
        self.calls += 1
        return CallAction(type=CallActionType.WAIT)


async def test_routing_policy_sends_each_brief_to_the_right_policy():
    base = Base()
    policy = RoutingCallPolicy(lambda: base, PlaybookPolicy(llm_mode="never"))
    plain = make_brief(playbook=None, playbook_inputs={}, disclosure_text=None)
    await policy.next_call_action(plain, Transcript(), [])
    assert base.calls == 1
    scripted = make_brief()
    out = await policy.next_call_action(scripted, Transcript(), [])  # nothing said yet: waits
    assert base.calls == 1 and out.type == CallActionType.WAIT
    assert policy.fixed_lines(plain) == {} and policy.fixed_lines(scripted)


def test_the_container_runner_uses_the_routing_policy(tmp_path):
    from friday.core.container import Container

    c = Container(Settings(_env_file=None, mode="simulator", env="test",
                           database_url=f"sqlite+aiosqlite:///{tmp_path}/w.db",
                           media_dir=str(tmp_path / "m")))
    try:
        assert isinstance(c.call_runner.policy, RoutingCallPolicy)
        off = Container(Settings(_env_file=None, mode="simulator", env="test",
                                 playbooks_enabled=False,
                                 database_url=f"sqlite+aiosqlite:///{tmp_path}/w2.db",
                                 media_dir=str(tmp_path / "m2")))
        assert not isinstance(off.call_runner.policy, RoutingCallPolicy)
    finally:
        asyncio.run(c.aclose())


# ------------------------------------------------------------------ the live path
def test_livecall_playbook_simulated_end_to_end(tmp_path):
    from friday.pilot import run_livecall

    out: list[str] = []
    s = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
                 media_dir=str(tmp_path / "m"))
    rc = asyncio.run(run_livecall(
        s, "+919000000000", yes=True, simulate=True, out=out.append, state_dir=tmp_path,
        on_behalf_of="Rahul", playbook="salon_booking",
        playbook_args={"date_window": "kal shaam", "budget_inr": 600}))
    text = "\n".join(out)
    assert rc == 0 and "salon_booking" in text and "cannot book" in text
    transcript = next(tmp_path.glob("livecall-*.txt")).read_text(encoding="utf-8")
    assert "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat salon se ho rahi hai?" in transcript  # noqa: E501
    assert "Playbook      : salon_booking -> outcome=SLOT_OFFERED" in text
    # the shared simulated business answers the identity question naturally, then the next line
    lines = transcript.splitlines()
    k = next(i for i, ln in enumerate(lines) if "Kya meri baat salon se ho rahi hai?" in ln)
    assert lines[k + 1].startswith("CALLEE") and "Haan ji, sahi hai" in lines[k + 1]
    assert "Main Rahul ji ki AI assistant hoon" in lines[k + 2]  # intro + availability in one turn
    assert "appointment mil sakta hai?" in lines[k + 2]


def test_livecall_playbook_keeps_every_guard(tmp_path):
    from friday.pilot import run_livecall

    out: list[str] = []
    live = Settings(_env_file=None, mode="live", profile="pilot", llm_provider="fake",
                    public_base_url="https://abc-def.trycloudflare.com",
                    sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
                    sarvam_caller_ids=["+918065354620"], sarvam_api_key="k",
                    secret_key="s" * 32, pin_pepper="p", field_key="f", index_key="i",
                    pilot_allowed_numbers=[])
    rc = asyncio.run(run_livecall(
        live, "+919812345678", yes=True, out=out.append, state_dir=tmp_path,
        on_behalf_of="Rahul", playbook="salon_booking", playbook_args={"date_window": "kal shaam"}))
    assert rc == 2 and "FRIDAY_PILOT_ALLOWED_NUMBERS" in " ".join(out)  # allow-list still applies
    out.clear()
    rc = asyncio.run(run_livecall(
        live.model_copy(update={"pilot_allowed_numbers": ["+919812345678"]}), "+919812345678",
        yes=True, out=out.append, state_dir=tmp_path, max_seconds=900,
        on_behalf_of="Rahul", playbook="salon_booking", playbook_args={"date_window": "kal shaam"}))
    assert rc == 2 and "cannot be more than" in " ".join(out)  # hard max duration
    out.clear()
    rc = asyncio.run(run_livecall(
        live, "+919812345678", yes=True, out=out.append, state_dir=tmp_path,
        on_behalf_of="Rahul", playbook="salon_booking", playbook_args={}))
    assert rc == 2 and "cannot run" in " ".join(out)  # missing required input: nothing dialled
    out.clear()
    rc = asyncio.run(run_livecall(
        live.model_copy(update={"pilot_allowed_numbers": ["+919812345678"],
                                "pilot_max_spend_inr": 0.5}), "+919812345678", yes=True,
        out=out.append, state_dir=tmp_path, on_behalf_of="Rahul", playbook="salon_booking",
        playbook_args={"date_window": "kal shaam"}))
    assert rc == 2 and "spend cap" in " ".join(out)


def test_livecall_cli_needs_a_real_first_name(capsys):
    from friday.cli import main

    rc = main(["livecall", "--to", "+919812345678", "--playbook", "salon_booking",
               "--when", "kal shaam", "--simulate"])
    assert rc == 2 and "--on-behalf-of" in capsys.readouterr().out


def test_livecall_test_brief_has_no_delegation_and_cannot_book():
    from friday.playbooks.select import playbook_test_brief

    brief = playbook_test_brief("salon_booking", to="+919812345678", user_first_name="Rahul",
                                max_seconds=120, from_number=None, date_window="kal shaam")
    assert brief.playbook == "salon_booking" and not brief.delegation.granted
    assert not brief.can_commit([]) and brief.max_duration_s == 120


# ------------------------------------------------------------------ --book-now
def test_book_now_builds_a_delegation_for_exactly_the_requested_time_and_ceiling():
    from friday.playbooks.select import playbook_test_brief

    brief = playbook_test_brief("salon_booking", to="+919812345678", user_first_name="Rahul",
                                max_seconds=120, from_number=None, date_window="aaj shaam 5 baje",
                                budget_inr=600, book_now=True)
    d = brief.delegation
    assert d.granted and d.max_price_inr == 600 and set(d.scope) == {"slot", "price"}
    assert d.window_start and d.window_end and (d.window_end - d.window_start).seconds <= 600
    assert brief.playbook_inputs["date_window"] == "aaj shaam 5 baje"
    # the code-level check agrees: right time and price pass, anything else does not
    from friday.core.safety import check_commit

    mid = d.window_start + (d.window_end - d.window_start) / 2
    assert check_commit(brief, [], amount_inr=500, slot_at=mid, decision="slot").allowed
    assert not check_commit(brief, [], amount_inr=601, slot_at=mid, decision="price").allowed
    assert not check_commit(brief, [], amount_inr=500,
                            slot_at=mid.replace(hour=(mid.hour + 3) % 24)).allowed


@pytest.mark.parametrize("kw", [
    {"date_window": "kal shaam", "budget_inr": 600},  # no specific time
    {"date_window": "kal shaam 5 se 8 baje ke beech", "budget_inr": 600},  # a range
    {"date_window": "aaj shaam 5 baje"},  # no price ceiling
])
def test_book_now_is_refused_without_a_specific_time_and_a_budget(kw):
    from friday.playbooks.model import PlaybookError
    from friday.playbooks.select import playbook_test_brief

    with pytest.raises(PlaybookError) as e:
        playbook_test_brief("salon_booking", to="+919812345678", user_first_name="Rahul",
                            max_seconds=120, from_number=None, book_now=True, **kw)
    assert "--book-now" in " ".join(e.value.problems)


def test_without_book_now_even_a_specific_time_and_budget_never_delegate():
    from friday.playbooks.select import playbook_test_brief

    brief = playbook_test_brief("salon_booking", to="+919812345678", user_first_name="Rahul",
                                max_seconds=120, from_number=None, date_window="aaj shaam 5 baje",
                                budget_inr=600)
    assert not brief.delegation.granted and not brief.can_commit([])


def test_cli_book_now_flag_is_refused_without_when_time_or_budget(capsys):
    from friday.cli import main

    rc = main(["livecall", "--to", "+919812345678", "--playbook", "salon_booking",
               "--on-behalf-of", "Rahul", "--when", "kal shaam", "--budget", "600",
               "--book-now", "--simulate", "--yes"])
    out = capsys.readouterr().out
    assert rc == 2 and "REFUSED" in out and "specific time" in out
    rc = main(["livecall", "--to", "+919812345678", "--playbook", "salon_booking",
               "--on-behalf-of", "Rahul", "--when", "aaj shaam 5 baje",
               "--book-now", "--simulate", "--yes"])
    out = capsys.readouterr().out
    assert rc == 2 and "--budget" in out


def _simulated_livecall(tmp_path, **args):
    from friday.pilot import run_livecall

    out: list[str] = []
    s = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
                 media_dir=str(tmp_path / "m"))
    rc = asyncio.run(run_livecall(
        s, "+919000000000", yes=True, simulate=True, out=out.append, state_dir=tmp_path,
        on_behalf_of="Rahul", playbook="salon_booking", playbook_args=args))
    transcript = next(tmp_path.glob("livecall-*.txt")).read_text(encoding="utf-8")
    return rc, "\n".join(out), transcript


def test_book_now_simulated_call_books_only_the_requested_time(tmp_path):
    # the simulated salon has 4 pm, 6 pm and 7:30 pm and quotes men 400 / women 700
    rc, text, transcript = _simulated_livecall(
        tmp_path, date_window="aaj shaam 6 baje", budget_inr=900, book_now=True)
    assert rc == 0 and "--book-now" in text and "outcome=BOOKED" in text
    assert transcript.count("book kar lijiye") == 1
    assert "Theek hai, aap aaj shaam 6 baje ka book kar lijiye. Thank you." in transcript


def test_book_now_does_not_book_a_time_the_salon_does_not_have(tmp_path):
    rc, text, transcript = _simulated_livecall(
        tmp_path, date_window="aaj shaam 5 baje", budget_inr=900, book_now=True)
    assert rc == 0 and "outcome=SLOT_OFFERED" in text and "book kar" not in transcript


def test_book_now_does_not_book_over_the_ceiling(tmp_path):
    rc, text, transcript = _simulated_livecall(
        tmp_path, date_window="aaj shaam 6 baje", budget_inr=500, book_now=True)
    assert rc == 0 and "outcome=SLOT_OFFERED" in text and "book kar" not in transcript


def test_without_book_now_the_same_call_can_never_book(tmp_path):
    rc, text, transcript = _simulated_livecall(
        tmp_path, date_window="aaj shaam 6 baje", budget_inr=900)
    assert rc == 0 and "outcome=SLOT_OFFERED" in text and "book kar" not in transcript


def test_call_me_script_takes_an_optional_book_now_argument():
    from pathlib import Path

    sh = (Path(__file__).parents[2] / "deploy" / "call-me.sh").read_text(encoding="utf-8")
    assert '"${5:-}"' in sh and "--book-now" in sh and "'book-now'" in sh
    # without the 5th argument no flag is passed
    assert 'BOOKFLAG=()' in sh
