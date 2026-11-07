# ruff: noqa: E501
"""T10 unit and wiring tests (fakes only, nothing dialled): redirecting-number extraction, who is claimed, the 60-90 s capped question loop, the
per-carrier forwarding setup text (all codes marked [U]), the chat commands and the new PENDING lines. The full forwarded-call flows through the
real app are in tests/e2e/robin/test_forwarded_calls.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from friday.core.config import Settings
from friday.liveagent.ports import CallDropped, HeardUtterance
from friday.robin import lines
from friday.robin.forwarded import forward_target, forwarding_text, known_carrier
from friday.robin.models import FamilyStatus, Role
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE, SECOND_PHONE

OWN = "+918065354620"  # invented Robin line
STRANGER = "+919100000077"


def ev(redirecting=None, call_fields=None, frm=STRANGER, to=OWN, ref="SCR1"):
    return SimpleNamespace(from_phone=frm, to_number=to, provider_call_id=ref, redirecting=redirecting, call_fields=call_fields or {})


class Port:
    """A scripted caller line on a virtual clock."""

    def __init__(self, script, clock, *, speak_s=2.0, listen_s=3.0):
        self.script, self.clock, self.speak_s, self.listen_s = list(script), clock, speak_s, listen_s
        self.spoken, self.hung_up = [], False

    async def speak(self, text, language):
        self.spoken.append(text)
        self.clock["t"] += self.speak_s

    async def listen(self, timeout_s):
        self.clock["t"] += self.listen_s
        if not self.script:
            raise CallDropped("hung up")
        item = self.script.pop(0)
        return None if item is None else HeardUtterance(text=item)

    async def send_dtmf(self, digits):  # pragma: no cover
        return None

    async def hangup(self):
        self.hung_up = True


@pytest.fixture
async def fw(w):
    w.settings.robin_forwarded_calls_enabled = True
    w.settings.friday_numbers = [OWN]
    fam, parent = await w.family()
    clock = {"t": 0.0}
    w.hub.forwarded.mono = lambda: clock["t"]
    return SimpleNamespace(w=w, fam=fam, parent=parent, clock=clock, f=w.hub.forwarded)


def test_defaults_are_off_and_capped():
    s = Settings(_env_file=None)
    assert s.robin_forwarded_calls_enabled is False
    assert 60 <= s.robin_forwarded_call_max_s <= 90
    with pytest.raises(ValueError):
        Settings(_env_file=None, robin_forwarded_call_max_s=120)


async def test_redirecting_number_formats_and_exclusions(fw):
    f = fw.f
    assert f.redirecting_number(ev(f"<sip:{PARENT_PHONE}@vobiz.example>;reason=no-answer")) == PARENT_PHONE
    assert f.redirecting_number(ev(f"tel:{PARENT_PHONE}")) == PARENT_PHONE
    assert f.redirecting_number(ev("9800000102")) == PARENT_PHONE  # national form
    assert f.redirecting_number(ev(None, {"History-Info": f"<sip:{PARENT_PHONE}@h>;index=1, <sip:{OWN}@h>;index=1.1"})) == PARENT_PHONE
    assert f.redirecting_number(ev(None, {"x-weird": f"<sip:{PARENT_PHONE}@h>"})) == PARENT_PHONE  # any captured key that still holds a number
    # Friday's own number, the caller's own number and the dialled number are not diversions
    assert f.redirecting_number(ev(OWN)) is None
    assert f.redirecting_number(ev(STRANGER)) is None
    assert f.redirecting_number(ev(PARENT_PHONE, to=PARENT_PHONE)) is None
    assert f.redirecting_number(ev(None)) is None
    assert f.redirecting_number(ev("not a number")) is None


async def test_claims_only_parent_or_child_of_an_active_family(fw):
    f, w = fw.f, fw.w
    fam = fw.fam
    fam.status = FamilyStatus.ONBOARDING
    await w.store.save_family(fam)
    assert await f.claims(ev(PARENT_PHONE)) is None, "family still onboarding (no consent yet)"
    fam.status = FamilyStatus.ACTIVE
    await w.store.save_family(fam)
    hit = await f.claims(ev(PARENT_PHONE))
    assert hit is not None and hit[1].role == Role.PARENT
    hit = await f.claims(ev(CHILD_PHONE))
    assert hit is not None and hit[1].role == Role.CHILD
    assert await f.claims(ev(STRANGER)) is None
    await w.hub.fam.set_second_contact(fam, SECOND_PHONE, "Uncle")
    assert await f.claims(ev(SECOND_PHONE)) is None, "a second contact's phone is not Robin's to answer"
    fam.status = FamilyStatus.PAUSED
    await w.store.save_family(fam)
    assert await f.claims(ev(PARENT_PHONE)) is None
    fam.status = FamilyStatus.ACTIVE
    await w.store.save_family(fam)
    w.settings.robin_forwarded_calls_enabled = False
    assert await f.claims(ev(PARENT_PHONE)) is None, "switch off = never claimed"


async def test_collect_asks_both_questions_closes_and_hangs_up(fw):
    port = Port(["Main Sharma bol raha hoon", "nahi"], fw.clock)
    out = await fw.f.collect(port, fw.fam, fw.parent, "hinglish")
    assert [a.line for a in out] == ["missed.ask_who", "missed.ask_urgent"] and out[1].text == "nahi"
    assert len(port.spoken) == 3 and port.hung_up
    assert "Papa" in port.spoken[0] and "Papa" in port.spoken[-1]


async def test_collect_repeats_a_silent_question_once_then_moves_on(fw):
    port = Port([None, None, "haan"], fw.clock)
    out = await fw.f.collect(port, fw.fam, fw.parent, "en")
    assert [a.line for a in out] == ["missed.ask_urgent"] and out[0].text == "haan"
    assert [s.startswith("Hello, this is") for s in port.spoken[:2]] == [True, True]  # asked twice, not three times
    assert "I am telling Papa it is urgent" in port.spoken[-1]


async def test_collect_never_runs_past_the_cap(fw):
    fw.w.settings.robin_forwarded_call_max_s = 60
    port = Port(["x"] * 20, fw.clock, speak_s=14.0, listen_s=14.0)
    out = await fw.f.collect(port, fw.fam, fw.parent, "hinglish")
    assert fw.clock["t"] <= 60 + 14  # at most the closing line past the cap
    assert len(out) <= 2 and port.hung_up and port.spoken  # always closes politely
    assert len(port.spoken) <= 4


async def test_unclear_urgency_answer_is_not_treated_as_a_yes(fw):
    port = Port(["kuch kaam hai", "kya matlab", "matlab kya"], fw.clock)
    out = await fw.f.collect(port, fw.fam, fw.parent, "hinglish")
    assert [a.line for a in out] == ["missed.ask_who"]
    assert "pahuncha dungi" in port.spoken[-1]  # the normal thank-you, not the urgent one


# ------------------------------------------------------------------ per-carrier setup text
def test_known_carriers():
    assert known_carrier("jio") == "jio" and known_carrier("Reliance Jio") == "jio"
    assert known_carrier("forwarding airtel") == "airtel"
    assert known_carrier("vodafone idea") == "vi" and known_carrier("vi") == "vi"
    assert known_carrier("bsnl") is None and known_carrier("") is None and known_carrier("tata") is None


@pytest.mark.parametrize("carrier,name", [("jio", "Jio"), ("airtel", "Airtel"), ("vi", "Vi")])
async def test_forwarding_text_has_the_codes_and_marks_every_one_unverified(fw, carrier, name):
    for lang in ("en", "hinglish"):
        text = forwarding_text(fw.w.ctx, carrier, who="Papa", lang=lang)
        assert text is not None and name in text and "+918065354620" in text
        codes = [ln for ln in text.splitlines() if ln.startswith("- ")]
        assert len(codes) == 3 and all("[U]" in ln for ln in codes)
        assert "**61*+918065354620**" in text and "**67*+918065354620#" in text and "**62*+918065354620#" in text
        assert "##002#" in text and "*#61#" in text
        assert "real SIM" in text or "SIM" in text


async def test_forwarding_text_needs_a_configured_robin_number(w):
    w.settings.friday_numbers = []
    w.settings.receptionist_inbound_number = None
    assert forward_target(w.settings) is None
    assert forwarding_text(w.ctx, "jio", who="Papa", lang="en") is None
    w.settings.receptionist_inbound_number = OWN
    assert forward_target(w.settings) == OWN and forwarding_text(w.ctx, "jio", who="Papa", lang="en") is not None


async def test_forwarding_codes_use_the_ringing_time_from_the_receptionist_config(fw):
    text = forwarding_text(fw.w.ctx, "jio", who="Papa", lang="en")
    assert "**61*+918065354620**" in text  # standard GSM no-reply form with a seconds value


# ------------------------------------------------------------------ the lines
def test_new_lines_exist_in_every_language_and_are_pending():
    assert not lines.approved(), "LINE_STATUS must still be PENDING"
    for key, langs in (("missed.caller_told", lines.LANGS), ("missed.caller_told_urgent", lines.LANGS), ("forward.ask", lines.CHAT_LANGS), ("forward.codes", lines.CHAT_LANGS), ("forward.unknown_carrier", lines.CHAT_LANGS), ("forward.unavailable", lines.CHAT_LANGS), ("forward.test", lines.CHAT_LANGS)):
        for lang in langs:
            slots = {s: "X" for s in lines.required_slots(key)}
            assert lines.say(key, lang, **slots)
    pend = {ln.id for ln in lines.all_lines() if ln.status != lines.APPROVED}
    assert "robin.missed.caller_told.hi" in pend and "robin.forward.codes.en" in pend


def test_the_forward_test_line_says_it_is_supervised_and_robin_places_no_call():
    text = lines.say("forward.test", "en", who="Papa", brand="Robin", seconds=75)
    assert "founder" in text and "Nothing is dialled" in text
