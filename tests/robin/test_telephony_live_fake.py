# ruff: noqa: E501
"""T11, tested with FAKES only (no phone, no network): every call outcome on a fake leg (answered, voicemail, ring timeout, busy, hang-up, silence,
barge-in, help, stop, unclear), the dial refusals, the per-family-day cost log, and `friday robin call-test` (founder number only)."""

from __future__ import annotations

import argparse
import asyncio
import re
from datetime import date
from typing import Any

import pytest

from friday.core.config import Settings
from friday.core.models import AudioClass, DialStatus, Transcription
from friday.qa import override
from friday.qa.config import APPROVAL_PHRASE, QaConfig
from friday.qa.store import QaStore
from friday.robin import lines
from friday.robin.calltest import result_lines, run_call_test
from friday.robin.checkin import base_steps
from friday.robin.models import CallResult, Family, Member, Role
from friday.robin.telephony import CallCostLedger, TelephonyParentCaller

NUMBER = "+919800000042"  # invented
OTHER = "+919800000077"  # invented
SLOTS = {"parent": "Papa", "child": "Asha"}


class CallEnded(Exception):  # noqa: N818 - same name as the real one (telephony matches on the class name)
    pass


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeLeg:
    """heard: list of str | (str, confidence) | Transcription | None (silence) | 'HANGUP' | 'HANG' (never returns)."""

    def __init__(self, clock: Clock, *, status: DialStatus = DialStatus.ANSWERED, heard: list[Any] | None = None, barge: dict[int, Transcription] | None = None, hang_ring: bool = False) -> None:
        self.clock, self.status, self.heard, self.barge, self.hang_ring = clock, status, list(heard or []), barge or {}, hang_ring
        self.spoken: list[str] = []
        self.hung = False

    async def wait_for_answer(self, t: float) -> DialStatus:
        if self.hang_ring:
            await asyncio.sleep(3600)
        return self.status

    async def speak(self, text: str, language: Any) -> Transcription | None:
        self.clock.t += 2.0
        self.spoken.append(text)
        return self.barge.get(len(self.spoken) - 1)

    async def listen(self, t: float) -> Transcription | None:
        self.clock.t += 3.0
        item = self.heard.pop(0) if self.heard else None
        if item == "HANGUP":
            raise CallEnded
        if item is None:
            return None
        if isinstance(item, Transcription):
            return item
        text, conf = item if isinstance(item, tuple) else (item, 0.9)
        return Transcription(text=text, confidence=conf)

    async def hangup(self) -> None:
        self.hung = True

    async def add_participant(self, *a: Any, **k: Any) -> None: ...
    async def leave(self) -> None: ...


class Tel:
    def __init__(self, leg: FakeLeg) -> None:
        self.leg, self.requests = leg, []

    async def place_call(self, req: Any) -> FakeLeg:
        self.requests.append(req)
        return self.leg


def settings_for(**kw: Any) -> Settings:
    values: dict[str, Any] = dict(mode="live", profile="pilot", pilot_allowed_numbers=[NUMBER], pause_file="/nonexistent/friday-test-pause")
    values.update(kw)
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Any:
    import os

    for name in list(os.environ):
        if name.startswith(("FRIDAY_", "SARVAM_", "ANTHROPIC_", "OPENAI_", "WHATSAPP_")):
            monkeypatch.delenv(name, raising=False)
    override.deactivate()
    yield
    override.deactivate()


@pytest.fixture
def approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lines, "LINE_STATUS", "APPROVED")  # the lines gate only; the number allow-list still applies


def parent(phone: str = NUMBER) -> tuple[Family, Member]:
    return Family(owner_user_id="u"), Member(family_id="f", role=Role.PARENT, phone=phone, language="hinglish")


async def call(leg: FakeLeg, clock: Clock, steps: Any = None, costs: CallCostLedger | None = None, **kw: Any) -> Any:
    fam, mem = parent()
    caller = TelephonyParentCaller(Tel(leg), settings_for(), clock=clock, costs=costs or CallCostLedger(lambda: date(2026, 1, 5)), **kw)
    return await caller.converse(member=mem, family=fam, purpose="checkin", steps=steps or base_steps(SLOTS), dedupe_key="d", brand="Robin")


ALL_YES = ["haan", "haan", "nahi", "theek", "nahi"]  # ate, slept, pain, mood, strange


# ------------------------------------------------------------------ outcomes
async def test_answered_full_call_has_timings_confidence_and_cost(approved):
    clock = Clock()
    leg = FakeLeg(clock, heard=[("haan", 0.91), ("haan ji", 0.8), "nahi", "udaas", ("nahi", 0.7)])
    out = await call(leg, clock)
    assert out.result == CallResult.ANSWERED and out.detail == "spoken" and leg.hung
    assert [a.text for a in out.answers] == ["haan", "haan ji", "nahi", "udaas", "nahi"]
    q = [t for t in out.steps if t.listen_ms]
    assert len(q) == 5 and q[0].confidence == 0.91 and q[0].heard == "yes" and q[2].heard == "no" and q[3].heard == "text"
    assert all(t.speak_ms == 2000 for t in out.steps) and q[0].listen_ms == 3000
    assert out.duration_s == 2 * 7 + 3 * 5 and out.cost_inr == round(out.duration_s / 60 * 5.0, 1)


async def test_voicemail_is_not_reached_and_nothing_is_spoken(approved):
    clock = Clock()
    leg = FakeLeg(clock, status=DialStatus.VOICEMAIL)
    out = await call(leg, clock)
    assert out.result == CallResult.NO_ANSWER and out.detail == "voicemail" and not leg.spoken and leg.hung and not out.answers


async def test_machine_greeting_after_pickup_is_voicemail_not_reached(approved):
    clock = Clock()
    leg = FakeLeg(clock, heard=[Transcription(text="please leave a message after the tone", audio_class=AudioClass.VOICEMAIL)])
    out = await call(leg, clock)
    assert out.result == CallResult.NO_ANSWER and out.detail == "voicemail" and len(leg.spoken) == 2  # greeting + first question, then stopped


async def test_ring_timeout_no_answer_busy_failed(approved):
    clock = Clock()
    leg = FakeLeg(clock, hang_ring=True)
    fam, mem = parent()
    caller = TelephonyParentCaller(Tel(leg), settings_for(), ring_timeout_s=0, clock=clock)
    out = await caller.converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin", max_seconds=60)
    assert out.result == CallResult.NO_ANSWER and out.detail == "ring_timeout" and leg.hung
    for status, want in ((DialStatus.NO_ANSWER, CallResult.NO_ANSWER), (DialStatus.BUSY, CallResult.BUSY), (DialStatus.FAILED, CallResult.FAILED)):
        o = await call(FakeLeg(clock, status=status), clock)
        assert o.result == want and o.duration_s == 0 and o.cost_inr == 0


async def test_hang_up_midway_counts_as_reached_with_partial_answers(approved):
    clock = Clock()
    out = await call(FakeLeg(clock, heard=["haan", "HANGUP"]), clock)
    assert out.result == CallResult.ANSWERED and out.hung_up_early and out.detail == "CallEnded" and len(out.answers) == 1


async def test_silence_repeats_once_then_hangs_up_not_reached(approved):
    clock = Clock()
    leg = FakeLeg(clock, heard=[None, None, None, None])  # question 1 twice, question 2 twice
    out = await call(leg, clock)
    assert out.result == CallResult.NO_ANSWER and out.detail == "silence" and leg.hung
    assert sum("sun" in s or "hear" in s for s in leg.spoken) >= 2 and out.steps[1].repeated and out.steps[1].heard == "silence"


async def test_silence_after_some_answers_is_still_reached(approved):
    clock = Clock()
    out = await call(FakeLeg(clock, heard=["haan", None, None, None, None]), clock)
    assert out.result == CallResult.ANSWERED and out.detail == "silence"


async def test_unclear_or_low_confidence_yesno_is_asked_once_more(approved):
    clock = Clock()
    leg = FakeLeg(clock, heard=[("haan", 0.1), ("haan", 0.9), "pata nahi kuch", "haan", "nahi", "nahi", "nahi"])
    out = await call(leg, clock)
    assert out.steps[1].repeated and out.answers[0].text == "haan" and out.steps[1].confidence == 0.9
    # a second unclear answer is kept as text and read as None (never as yes)
    from friday.robin.checkin import parse_answers

    out2 = await call(FakeLeg(clock, heard=["achha", "achha", "haan", "nahi", "nahi", "nahi", "nahi"]), clock)
    assert parse_answers(out2)["ate"] is None


async def test_barge_in_text_answers_the_question_without_listening(approved):
    clock = Clock()
    leg = FakeLeg(clock, heard=[], barge={1: Transcription(text="haan khaya", confidence=0.88)})
    out = await call(leg, clock, steps=base_steps(SLOTS)[:2])
    assert out.steps[1].barge_in and out.steps[1].listen_ms == 0 and out.answers[0].text == "haan khaya" and out.steps[1].heard == "yes"


async def test_help_word_ends_call_with_help_requested_even_over_greeting(approved):
    clock = Clock()
    out = await call(FakeLeg(clock, heard=["madad karo"]), clock)
    assert out.result == CallResult.ANSWERED and out.detail == "help_requested"
    leg = FakeLeg(clock, barge={0: Transcription(text="bachao", confidence=0.5)})
    out2 = await call(leg, clock)
    assert out2.detail == "help_requested" and leg.spoken[-1].startswith("Papa") or "Papa" in leg.spoken[-1]


async def test_stop_is_honoured(approved):
    clock = Clock()
    out = await call(FakeLeg(clock, heard=["ruk jao"]), clock)
    assert out.detail == "stop_requested"


async def test_max_duration_ends_the_call(approved):
    clock = Clock()
    fam, mem = parent()
    caller = TelephonyParentCaller(Tel(FakeLeg(clock, heard=ALL_YES)), settings_for(), clock=clock)
    out = await caller.converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin", max_seconds=8)
    assert out.detail == "max_duration" and len(out.answers) < 5


# ------------------------------------------------------------------ refusals (unchanged behaviour)
async def test_refused_while_pending_unless_founder_qa_override(caplog):
    clock = Clock()
    leg = FakeLeg(clock, heard=ALL_YES)
    tel = Tel(leg)
    fam, mem = parent()
    caller = TelephonyParentCaller(tel, settings_for(), clock=clock)
    out = await caller.converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert out.result == CallResult.REFUSED and out.detail == "line_pending" and not tel.requests
    override.activate(override.QaSession(run_id="r", scenario="s", target=NUMBER))
    ok = await caller.converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert ok.result == CallResult.ANSWERED and tel.requests
    _, other = parent(OTHER)
    tel2 = Tel(FakeLeg(clock))
    refused = await TelephonyParentCaller(tel2, settings_for(), clock=clock).converse(member=other, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert refused.result == CallResult.REFUSED and not tel2.requests


async def test_override_never_reaches_a_second_number(approved):
    override.activate(override.QaSession(run_id="r", scenario="s", target=NUMBER))
    fam, other = parent(OTHER)
    tel = Tel(FakeLeg(Clock()))
    out = await TelephonyParentCaller(tel, settings_for()).converse(member=other, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert out.detail == "test_allowlist" and not tel.requests


async def test_emergency_numbers_are_never_dialled(approved):
    fam, mem = parent("112")
    tel = Tel(FakeLeg(Clock()))
    out = await TelephonyParentCaller(tel, settings_for(pilot_allowed_numbers=["112"])).converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert out.detail == "emergency_number" and not tel.requests


# ------------------------------------------------------------------ cost log
async def test_cost_estimate_is_summed_per_family_per_day_and_logged(approved, caplog):
    import logging

    caplog.set_level(logging.INFO)
    clock, costs = Clock(), CallCostLedger(lambda: date(2026, 1, 5))
    fam, mem = parent()
    caller = TelephonyParentCaller(Tel(FakeLeg(clock, heard=ALL_YES + ALL_YES)), settings_for(), clock=clock, costs=costs)
    caller._telephony = lambda: Tel(FakeLeg(clock, heard=ALL_YES))  # noqa: SLF001 - a fresh leg per call
    for _ in range(2):
        await caller.converse(member=mem, family=fam, purpose="checkin", steps=base_steps(SLOTS), dedupe_key="d", brand="Robin")
    assert list(costs.per_family_day()) == [(fam.id, "2026-01-05")]
    (total,) = costs.per_family_day().values()
    assert total == 4.8, total
    assert any("call cost estimate" in r.getMessage() and "day=2026-01-05" in r.getMessage() for r in caplog.records)
    assert not any(NUMBER in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ friday robin call-test
def ns(**kw: Any) -> argparse.Namespace:
    d = dict(to=None, language="hinglish", parent="Papa", child="Asha", seconds=None, plan_only=False)
    d.update(kw)
    return argparse.Namespace(**d)


def run_ct(tmp_path: Any, args: argparse.Namespace, leg: FakeLeg | None, *, typed: str = APPROVAL_PHRASE, settings: Settings | None = None, clock: Clock | None = None):
    printed: list[str] = []
    clock = clock or Clock()
    leg = leg or FakeLeg(clock)
    tel = Tel(leg)
    qa = QaConfig(live=True, dir=str(tmp_path / "qa"))
    code = asyncio.run(run_call_test(args, settings or settings_for(), qa, QaStore(qa.dir), tel, input_fn=lambda _p: typed, out=printed.append, clock=clock))
    return code, printed, tel, QaStore(qa.dir)


def test_call_test_places_one_call_prints_pii_free_result_and_uses_pending_override(tmp_path):
    clock = Clock()
    leg = FakeLeg(clock, heard=[("haan", 0.93), ("haan", 0.8), "nahi", "theek hoon", ("nahi", 0.7)])
    code, printed, tel, store = run_ct(tmp_path, ns(), leg, clock=clock)
    text = "\n".join(printed)
    assert code == 0 and len(tel.requests) == 1 and tel.requests[0].to_phone == NUMBER and tel.requests[0].record is False
    assert "Outcome: answered" in text and "Reached: yes" in text and "stt 0.93" in text and "speak" in text and "estimated cost" in text
    assert NUMBER not in text and not re.search(r"\d{8,}", text) and "theek hoon" not in text and "haan" not in text  # no number, no words said
    assert store.pending_path.exists() and "robin.checkin.greet" in store.pending_path.read_text()  # pending line ids are logged for approval
    assert override.active() is None  # the override is off again
    assert store.today()[0] == 1  # one QA ledger entry


def test_call_test_refuses_any_other_number_before_dialling(tmp_path):
    code, printed, tel, _ = run_ct(tmp_path, ns(to=OTHER), None)
    assert code == 2 and not tel.requests and "REFUSED" in "\n".join(printed) and OTHER not in "\n".join(printed)


def test_call_test_refuses_when_qa_is_not_startable(tmp_path):
    for kw in ({"mode": "simulator"}, {"pilot_allowed_numbers": [NUMBER, OTHER]}):
        code, _, tel, _ = run_ct(tmp_path, ns(), None, settings=settings_for(**kw))
        assert code == 2 and not tel.requests


def test_call_test_needs_the_approval_phrase_and_plan_only_dials_nothing(tmp_path):
    code, printed, tel, _ = run_ct(tmp_path, ns(), None, typed="yes")
    assert code == 1 and not tel.requests and "Cancelled" in "\n".join(printed)
    code, printed, tel, _ = run_ct(tmp_path, ns(plan_only=True), None)
    assert code == 0 and not tel.requests and "checkin.greet" in "\n".join(printed)


def test_call_test_respects_the_kill_switch(tmp_path):
    pause = tmp_path / "pause"
    pause.write_text("1")
    code, _, tel, _ = run_ct(tmp_path, ns(), None, settings=settings_for(pause_file=str(pause)))
    assert code == 2 and not tel.requests


def test_call_test_voicemail_is_reported_not_reached(tmp_path):
    clock = Clock()
    code, printed, tel, _ = run_ct(tmp_path, ns(), FakeLeg(clock, status=DialStatus.VOICEMAIL), clock=clock)
    text = "\n".join(printed)
    assert code == 1 and "Reached: no" in text and "voicemail" in text


def test_result_lines_have_no_free_text():
    from friday.robin.models import CallOutcome, StepTiming

    rows = result_lines(CallOutcome(result=CallResult.ANSWERED, detail="spoken", steps=[StepTiming(line="checkin.q.ate", heard="yes", confidence=0.5)]))
    assert any("checkin.q.ate" in r and "0.50" in r for r in rows)
