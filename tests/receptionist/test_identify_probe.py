# ruff: noqa: E501
from __future__ import annotations

import json

import pytest

from friday.receptionist import identify as I
from friday.receptionist import probe as P
from friday.receptionist.identify import Route, UserRef

USER = "+919800000001"  # invented
FRIDAY = "+918000000099"


@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        ("+919800000001", ["+919800000001"]),
        ("09800000001", ["09800000001"]),
        ("tel:+91-98000-00001", ["+919800000001"]),
        ("<sip:+919800000001@vobiz.example>;reason=no-answer", ["+919800000001"]),
        ('"X" <sip:919800000001@host>;reason=user-busy;counter=1', ["919800000001"]),
        ("garbage", []),
        ("", []),
    ],
)
def test_parse_numbers(raw, expect):
    assert I.parse_numbers(raw) == expect


def test_reason_is_parsed():
    assert I.parse_reason("<sip:+919800000001@h>;reason=no-answer") == "no-answer"
    assert I.parse_reason("<sip:+919800000001@h>;reason=user-busy") == "user-busy"
    assert I.parse_reason("+919800000001") is None


def test_original_target_selection():
    two = "<sip:+918888888888@h>;reason=unconditional, <sip:+919800000001@h>;reason=no-answer"
    assert I.pick_original("Diversion", two) == "+919800000001"  # original is listed last
    hi = "<sip:+919800000001@h>;index=1, <sip:+918888888888@h>;index=1.1"
    assert I.pick_original("History-Info", hi) == "+919800000001"  # original is listed first


def test_extract_uses_configured_keys_case_insensitively():
    params = {"From": "9191000000", "To": FRIDAY, "diversion": f"<sip:{USER}@h>;reason=no-answer"}
    num, key, reason = I.extract_redirecting(params, ["ForwardedFrom", "Diversion"])
    assert (num, key, reason) == (USER, "diversion", "no-answer")
    assert I.extract_redirecting({"From": "1"}, ["Diversion"]) is None
    assert I.extract_redirecting({"Diversion": "   "}, ["Diversion"]) is None


class Dir:
    def __init__(self, enabled=True):
        self.enabled = enabled

    async def user_for_phone(self, phone):
        return UserRef("u1", self.enabled) if phone == USER else None


def resolver(enabled=True):
    return I.RedirectResolver(Dir(enabled), fields=["Diversion"], friday_numbers=lambda: [FRIDAY])


async def test_resolution_routes():
    r = resolver()
    assert (await r.resolve(None)).route == Route.NOT_FORWARDED
    assert (await r.resolve("nonsense")).route == Route.NOT_FORWARDED
    m = await r.resolve(f"<sip:{USER}@h>;reason=no-answer", "+919100000001")
    assert (m.route, m.user_id, m.reason) == (Route.MATCHED, "u1", "no-answer")
    u = await r.resolve("<sip:+919800000555@h>", "+919100000001")
    assert u.route == Route.UNKNOWN_NUMBER and u.user_id is None  # never a guessed user
    assert (await resolver(False).resolve(USER)).route == Route.DISABLED


async def test_friday_own_number_or_the_callers_own_number_is_not_a_diversion():
    r = resolver()
    assert (await r.resolve(FRIDAY)).route == Route.NOT_FORWARDED
    assert (await r.resolve(USER, caller=USER)).route == Route.NOT_FORWARDED


# ------------------------------------------------------------------ probe
WEBHOOK = {
    "CallUUID": "abc", "From": "919100000001", "To": FRIDAY,
    "Diversion": f"<sip:{USER}@h>;reason=no-answer", "CallStatus": "in-progress",
}  # fmt: skip


def test_probe_finds_the_key_that_carries_a_third_number_and_masks_it():
    e = P.analyse(WEBHOOK, ["ForwardedFrom"])
    assert [c.key for c in e.candidates] == ["Diversion"]
    assert e.candidates[0].configured is False
    blob = json.dumps(e.to_json())
    assert "9800000001" not in blob and "9100000001" not in blob  # nothing unmasked is kept
    assert "CallUUID" in e.keys
    assert P.analyse(WEBHOOK, ["diversion"]).candidates[0].configured is True


def test_probe_without_a_third_number_reports_it():
    plain = {"From": "919100000001", "To": FRIDAY, "CallUUID": "x"}
    e = P.analyse(plain, [])
    assert e.candidates == []
    assert "NOT delivered" in P.format_report([e.to_json()])


def test_probe_file_roundtrip(tmp_path):
    path = tmp_path / "p" / "probe.jsonl"
    pr = P.InboundProbe(["Diversion"], path)
    pr.record(WEBHOOK)
    rows = P.load(path)
    assert len(rows) == 1 and rows[0]["candidates"][0]["key"] == "Diversion"
    assert "already configured" in P.format_report(rows)
    assert "No inbound webhook" in P.format_report([])


def test_observe_inbound_is_inert_until_configured():
    P.configure((), None)
    assert P.observe_inbound(WEBHOOK) is None
    P.configure(["Diversion"], None)
    try:
        assert P.observe_inbound(WEBHOOK).startswith("<sip:")
        assert P.observe_inbound({"From": "1"}) is None
    finally:
        P.configure((), None)


async def test_probe_waiter():
    pr = P.InboundProbe(["Diversion"])
    assert await pr.wait_for_candidate(0.01) is False
