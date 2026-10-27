# ruff: noqa: E501
"""The spoken line is PENDING (no audio, the real dial refuses), the lines obey the rules, the docs list
every line and text, and the real dial adapter works against a FAKE provider leg only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from friday.core.config import Settings
from friday.core.models import DialStatus
from friday.urgent import copy, lines
from friday.urgent.models import RingResult
from friday.urgent.telephony import TelephonyOwnNumberCaller
from tests.urgent.conftest import OTHER_PHONE, USER_PHONE

DOC = Path(__file__).resolve().parents[2] / "docs" / "URGENT_ESCALATION.md"
KW = dict(user_id="u", number=USER_PHONE, line_key="ring.urgent", lang="en", user_name="Asha", dedupe_key="e1:1")


class Leg:
    def __init__(self, status=DialStatus.ANSWERED):
        self.status, self.spoken, self.hung_up = status, [], False

    async def wait_for_answer(self, timeout_s):
        return self.status

    async def speak(self, text, language):
        self.spoken.append((text, language))

    async def hangup(self):
        self.hung_up = True


class Tel:
    def __init__(self, leg=None, boom=False):
        self.leg, self.boom, self.requests = leg or Leg(), boom, []

    async def place_call(self, request):
        self.requests.append(request)
        if self.boom:
            raise RuntimeError("carrier")
        return self.leg


# ----------------------------------------------------------------------------- the line is PENDING
def test_every_spoken_line_is_pending_founder_approval_and_no_audio_exists():
    assert lines.LINE_STATUS == "PENDING_FOUNDER_APPROVAL" and not lines.approved()
    assert all(pl.status == "PENDING_FOUNDER_APPROVAL" for pl in lines.all_lines())
    assert copy.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert not list(Path(__file__).resolve().parents[2].glob("**/urg*.wav"))


async def test_the_real_dial_refuses_while_the_line_is_pending():
    tel = Tel()
    caller = TelephonyOwnNumberCaller(tel, Settings(_env_file=None))
    out = await caller.ring(**KW)
    assert out.result == RingResult.REFUSED and out.detail == "line_pending"
    assert tel.requests == []  # not even placed


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setattr(lines, "LINE_STATUS", lines.APPROVED)  # ONLY inside a test, never in the repo


async def test_after_approval_the_adapter_dials_the_number_it_is_given_and_speaks_one_line(approved):
    tel = Tel()
    out = await TelephonyOwnNumberCaller(tel, Settings(_env_file=None)).ring(**KW)
    assert out.result == RingResult.ANSWERED
    assert [r.to_phone for r in tel.requests] == [USER_PHONE] and tel.requests[0].record is False
    assert tel.requests[0].task_id == "e1:1"
    assert len(tel.leg.spoken) == 1 and "Asha" in tel.leg.spoken[0][0] and tel.leg.hung_up


@pytest.mark.parametrize(
    "status,expected",
    [(DialStatus.NO_ANSWER, RingResult.NO_ANSWER), (DialStatus.BUSY, RingResult.BUSY),
     (DialStatus.VOICEMAIL, RingResult.VOICEMAIL), (DialStatus.FAILED, RingResult.FAILED)],
)  # fmt: skip
async def test_dial_statuses_map_and_the_line_is_always_hung_up(approved, status, expected):
    tel = Tel(Leg(status))
    out = await TelephonyOwnNumberCaller(tel, Settings(_env_file=None)).ring(**KW)
    assert out.result == expected and tel.leg.spoken == [] and tel.leg.hung_up


async def test_provider_errors_are_a_failed_attempt_not_a_crash(approved):
    out = await TelephonyOwnNumberCaller(Tel(boom=True), Settings(_env_file=None)).ring(**KW)
    assert out.result == RingResult.FAILED


async def test_the_adapter_also_honours_the_kill_switch_and_the_pilot_allow_list(approved):
    tel = Tel()
    out = await TelephonyOwnNumberCaller(tel, Settings(_env_file=None), paused=lambda: True).ring(**KW)
    assert out.result == RingResult.REFUSED and out.detail == "kill_switch"
    pilot = Settings(_env_file=None, pilot_block_business_calls=True, pilot_allowed_numbers=[OTHER_PHONE])
    out = await TelephonyOwnNumberCaller(tel, pilot).ring(**KW)
    assert out.result == RingResult.REFUSED and out.detail == "test_allowlist" and tel.requests == []


# ----------------------------------------------------------------------------- rules the lines obey
def test_lines_have_no_digits_no_private_details_and_only_the_user_slot():
    for key, by_lang in lines.LINES.items():
        assert set(by_lang) == set(lines.LANGS)
        assert lines.required_slots(key) == {"user"}
        for lang, text in by_lang.items():
            assert "{user}" in text
            assert not re.search(r"\d", text), (key, lang)
            low = text.lower()
            assert not any(w in low for w in ("number", "address", "naam", "kisne", "who called", "aapko call kiya")), (key, lang)
            assert "{who}" not in text and "?" not in text  # a nudge, never a question needing an answer


def test_say_fills_the_slot_and_a_missing_slot_fails_loudly():
    assert "Asha" in lines.say("ring.urgent", "en", user="Asha")
    assert "emergency" in lines.say("ring.emergency", "en", user="Asha")
    with pytest.raises(KeyError):
        lines.say("ring.urgent", "en")


def test_texts_fit_whatsapp_and_slots_are_filled():
    for lang in copy.LANGS:
        assert len(copy.button_title("ack", lang)) <= 20
        assert "5" in copy.t("alert.hint", lang, minutes=5)
        assert "{" not in copy.t("exhausted", lang, n=2)


# ----------------------------------------------------------------------------- the docs list everything
def test_the_doc_lists_every_pending_line_and_text_so_the_founder_can_approve_by_audio():
    text = DOC.read_text(encoding="utf-8")
    for pl in lines.all_lines():
        assert f"`{pl.id}`" in text, pl.id
    for lid, _lang, _t in copy.all_texts():
        assert f"`{lid}`" in text, lid
    for must in ("PENDING_FOUNDER_APPROVAL", "FRIDAY_URGENT_ESCALATION_ENABLED", "FRIDAY_URGENT_ESCALATION_MINUTES",
                 "0015_urgent_escalation", "UNVERIFIED", "quiet hours", "kill switch"):  # fmt: skip
        assert must.lower() in text.lower(), must


def test_the_receptionist_doc_points_at_the_new_lines():
    rdoc = (DOC.parent / "RECEPTIONIST.md").read_text(encoding="utf-8")
    assert "URGENT_ESCALATION.md" in rdoc
