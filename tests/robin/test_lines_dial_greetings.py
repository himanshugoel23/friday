# ruff: noqa: E501
"""Lines (brand, PENDING, safety lint, the docs file), the real dial adapter refusing, the CallGate/allow-list, greetings and the
screening/listen-in stubs."""

from __future__ import annotations

import re
from datetime import date

from friday.core.clock import FakeClock
from friday.core.models import DialStatus
from friday.robin import lines
from friday.robin.gate import RobinGate
from friday.robin.greetings import festivals_on, load_festivals, render_svg
from friday.robin.linesdoc import DOC, render
from friday.robin.models import CallResult, ConsentSource, Family, Member, Role, Step
from friday.robin.screening import FakeAnalyzer, PatternVerdict, ScreeningService, Verdict
from friday.robin.telephony import TelephonyParentCaller
from tests.robin.conftest import PARENT_PHONE, at

SLOTS = {"parent": "Papa", "child": "Asha", "medicine": "Metformin", "time": "09:00", "why": "x", "items": "a", "festival": "Diwali", "date": "5 Jan", "meds": "m", "summary": "s", "n": "1", "days": "3"}


def test_every_line_is_pending_and_takes_the_name_from_the_brand():
    assert lines.LINE_STATUS == "PENDING_FOUNDER_APPROVAL" and not lines.approved()
    for ln in lines.all_lines():
        assert ln.status == "PENDING_FOUNDER_APPROVAL"
        assert "Friday" not in ln.text and "Robin" not in ln.text, ln.id  # the name is only ever the {brand} slot
    assert "Zed" in lines.say("intro.greet", "en", brand="Zed", parent="Papa", child="A")
    assert "Friday" in lines.say("intro.greet", "en", parent="Papa", child="A")  # default brand


def test_parent_facing_lines_exist_in_three_languages_with_devanagari():
    for key, langs in lines.SPOKEN.items():
        assert set(langs) == {"en", "hinglish", "hi"}, key
        assert re.search(r"[ऀ-ॿ]", langs["hi"]) and not re.search(r"[ऀ-ॿ]", langs["hinglish"]), key
        slots = lines.required_slots(key)
        assert set(re.findall(r"\{(\w+)\}", langs["hi"])) - {"brand"} == set(slots) or set(slots) >= set(re.findall(r"\{(\w+)\}", langs["hi"])) - {"brand"}, key
    for key, langs in lines.CHAT.items():
        assert {"en", "hinglish"} <= set(langs), key


def test_safety_lint_never_asks_for_otp_pin_password_and_discloses_ai():
    neg = ("never", "not ", "do not", "don't", "nahi", "mat ", "मत", "नहीं", "kabhi", "without")
    for ln in lines.all_lines():
        t = ln.text.lower()
        if re.search(r"\b(otp|pin|password|cvv|aadhaar)\b|पासवर्ड|ओटीपी", t):
            assert any(n in t for n in neg), ln.id  # only ever inside a refusal
    for lang in lines.LANGS:
        assert "AI" in lines.SPOKEN["intro.greet"][lang]
        assert "AI" in lines.SPOKEN["checkin.greet"][lang] and "AI" in lines.SPOKEN["listen.disclose"][lang]


def test_lines_doc_is_in_sync_and_lists_every_line():
    text = DOC.read_text(encoding="utf-8")
    assert text == render(), "run: uv run python -m friday.robin.linesdoc"
    for ln in lines.all_lines():
        assert f"| {ln.id} |" in text
    assert f"Total lines: **{len(lines.all_lines())}**" in text


def test_every_line_renders_with_sample_slots():
    for ln in lines.all_lines():
        key = ln.id.split(".", 1)[1].rsplit(".", 1)[0]
        extra = {"phone": "+91", "rel": "father", "start": "22:00", "end": "07:00", "item": "i", "level": "calm", "list": "l", "loc": "", "lat": "1", "lon": "2", "scenario": "S1", "tier": "high", "at": "t", "steps": "s", "verdict": "v", "basis": "b", "taken": "1", "missed": "0", "total": "1", "state": "x", "today": "t", "alerts": "0", "declined": "-", "shared": "s", "source": "app", "v": "yes", "when": "w", "until": "u", "medicine": "m", "dose": "5mg", "times": "8am", "amount": "Rs 1", "items": "i", "who": "Asha", "minutes": "3", "tries": "6", "name": "N", "address": "A", "what": "w", "callback": "+91", "seconds": "60", "code": "K7M2QX9A", "link": "robin://pair?code=K7M2QX9A"}
        lines.say(key, ln.language, brand="Robin", **{**SLOTS, **extra})


# ---------------------------------------------------------------- the real dial adapter
class Leg:
    def __init__(self, heard=("haan", "haan", "nahi", "achha", "nahi")):
        self.spoken, self.heard, self.hung, self.added = [], list(heard), False, None

    async def wait_for_answer(self, t):
        return DialStatus.ANSWERED

    async def speak(self, text, language):
        self.spoken.append(text)

    async def listen(self, t):
        from friday.core.models import Transcription

        return Transcription(text=self.heard.pop(0) if self.heard else "")

    async def hangup(self):
        self.hung = True

    async def add_participant(self, phone, announce=None):
        self.added = (phone, announce)

    async def leave(self):
        pass


class Tel:
    def __init__(self, leg):
        self.leg, self.requests = leg, []

    async def place_call(self, req):
        self.requests.append(req)
        return self.leg


def _member(phone=PARENT_PHONE):
    return Family(owner_user_id="u"), Member(family_id="f", role=Role.PARENT, phone=phone, language="en")


async def test_real_dial_refuses_while_lines_are_pending(settings):
    fam, parent = _member()
    tel = Tel(Leg())
    caller = TelephonyParentCaller(tel, settings)
    out = await caller.converse(member=parent, family=fam, purpose="checkin", steps=[Step(line="checkin.greet", slots={"parent": "Papa", "child": "A"})], dedupe_key="d", brand="Robin")
    assert out.result == CallResult.REFUSED and out.detail == "line_pending" and not tel.requests
    b = await caller.bridge(child=parent, parent=parent, family=fam, dedupe_key="b", brand="Robin")
    assert b.detail == "line_pending"


async def test_real_dial_when_approved_speaks_listens_never_records_and_honours_stop(settings, monkeypatch):
    monkeypatch.setattr(lines, "LINE_STATUS", "APPROVED")
    fam, parent = _member()
    leg = Leg()
    tel = Tel(leg)
    caller = TelephonyParentCaller(tel, settings)
    steps = [Step(line="checkin.greet", slots={"parent": "Papa", "child": "A"}), Step(line="checkin.q.ate", slots={"parent": "Papa", "child": "A"}, expect="yesno")]
    out = await caller.converse(member=parent, family=fam, purpose="checkin", steps=steps, dedupe_key="d", brand="Robin")
    assert out.result == CallResult.ANSWERED and out.answers[0].text == "haan" and leg.hung
    assert tel.requests[0].record is False and "Robin" in leg.spoken[0]
    leg2 = Leg(heard=("ruk jao",))
    out2 = await TelephonyParentCaller(Tel(leg2), settings).converse(member=parent, family=fam, purpose="checkin", steps=steps, dedupe_key="e", brand="Robin")
    assert out2.detail == "stop_requested" and any("stopped" in s or "ruk" in s for s in leg2.spoken)
    settings.pilot_allowed_numbers = ["+919999999999"]
    settings.profile, settings.mode = "pilot", "live"
    out3 = await TelephonyParentCaller(Tel(Leg()), settings).converse(member=parent, family=fam, purpose="checkin", steps=steps, dedupe_key="f", brand="Robin")
    assert out3.result == CallResult.REFUSED


async def test_callgate_and_pilot_allowlist_in_front_of_every_dial(settings, container):
    from friday.calls.dnc import DncRegistry
    from friday.calls.gate import CallGate
    from friday.calls.numbers import NumberHasher
    from friday.calls.settings import CallsSettings
    from friday.core.models import User, UserStatus
    from tests.calls.conftest import make_cipher

    hasher = NumberHasher(make_cipher())
    from tests.calls.conftest import MemoryCallStore, MemoryDncStore

    clock = FakeClock(at(11))
    gate = RobinGate(CallGate(store=MemoryCallStore(), dnc=DncRegistry(MemoryDncStore(), hasher, clock), hasher=hasher, settings=CallsSettings(), core_settings=settings), hasher, settings)
    owner = User(phone="+919800000101", status=UserStatus.ACTIVE)
    assert (await gate.check(owner, PARENT_PHONE, override_window=False, now=clock.now())).allowed
    settings.profile, settings.mode = "pilot", "live"
    settings.pilot_allowed_numbers = ["+919800000555"]
    r = await gate.check(owner, PARENT_PHONE, override_window=False, now=clock.now())
    assert not r.allowed  # in the pilot the parent's number must be explicitly allow-listed
    assert (await gate.check(owner, "112", override_window=True, now=clock.now())).allowed is False  # never an emergency number


# ---------------------------------------------------------------- greetings
def test_festival_calendar_only_sends_verified_dates():
    assert not festivals_on(date(2026, 11, 8))  # Diwali is not verified yet: never sent
    assert [f["id"] for f in festivals_on(date(2027, 1, 26))] == ["republic_day"]
    assert not festivals_on(date(2026, 4, 14), regions=["kerala"]) and festivals_on(date(2026, 4, 14), regions=["punjab"])
    assert len(load_festivals()) >= 15
    svg = render_svg("republic_day", "Happy Republic Day, Papa!")
    assert svg.startswith("<svg") and "Republic" in svg and "http" not in svg.replace("http://www.w3.org/2000/svg", "")


async def test_good_morning_and_festival_message(w):
    fam, parent = await w.family()
    await w.hub.fam.update_settings(fam, good_morning=True, festival_graphics=True)
    w.clock.set(at(7, 45, day=26).replace(month=1))
    from datetime import datetime

    w.clock.set(datetime(2026, 1, 26, 7, 45, tzinfo=at(7).tzinfo))
    n = await w.hub.greetings.tick()
    assert n == 1 and w.channel.templates and w.channel.templates[0][1] == "good_morning_festival"
    assert "Republic Day" in w.channel.templates[0][2]["text"] or "Ganatantra" in w.channel.templates[0][2]["text"]
    assert await w.hub.greetings.tick() == 0  # once a day
    # quiet hours / off / paused: nothing
    w.clock.set(datetime(2026, 1, 27, 6, 0, tzinfo=at(7).tzinfo))
    assert await w.hub.greetings.tick() == 0
    await w.hub.fam.update_settings(fam, good_morning=False, festival_graphics=False)
    w.clock.set(datetime(2026, 1, 28, 8, 0, tzinfo=at(7).tzinfo))
    assert await w.hub.greetings.tick() == 0
    _ = ConsentSource


# ---------------------------------------------------------------- screening / listen-in stubs
async def test_screening_and_listen_in_are_off_by_default_and_judge_the_pattern(w):
    fam, parent = await w.family()
    svc = ScreeningService(w.ctx, FakeAnalyzer(PatternVerdict(Verdict.RISKY, "urgency ramp + secrecy + money ask", ("urgency_ramp", "secrecy", "money_ask"))))
    assert (await svc.screen(fam, parent, ["hello"])).reason == "switch_off"
    assert (await svc.listen_in_start(fam, parent)).reason == "switch_off"
    w.settings.robin_screen_unknown_enabled = True
    w.settings.robin_listen_in_enabled = True
    d = await svc.screen(fam, parent, ["I am from the bank", "do not tell anyone", "send money now"])
    assert d.action == "decline" and "urgency ramp" in w.sender.texts()[-1]
    ok = ScreeningService(w.ctx, FakeAnalyzer())
    assert (await ok.screen(fam, parent, ["I am the plumber"])).action == "bridge"
    assert (await svc.listen_in_start(fam, parent)).reason == "no_consent"
    await w.hub.fam.admin_consent(fam, "call_listening")
    start = await svc.listen_in_start(fam, parent)
    assert start.action == "bridge" and start.lines == ["listen.disclose"]  # the disclosure is the first thing spoken
    assert (await svc.listen_in_verdict(fam, parent, ["x"])).lines == ["listen.warn"]
