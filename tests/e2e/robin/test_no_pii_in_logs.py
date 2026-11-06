# ruff: noqa: E501
"""The PII gate: after a whole day of Robin (setup, medicine, check-in with words, a phone alert, SOS with location, an urgent missed call, the desk, a stop, an
erase) the captured LOG records and the audit never contain a full phone number, a medicine name, what the parent or the caller SAID, or distress text."""

from __future__ import annotations

import pytest

from friday.robin.models import AnswerRaw, CallResult
from tests.e2e.robin.harness import CHILD, PARENT, RobinWorld, assert_no_pii

MEDICINE = "Zorbexin"  # invented drug name
PARENT_WORDS = "mere seene mein bahut dard hai aur chakkar aa rahe hain"  # what the parent says on the check-in call
CALLER_WORDS = "Mama gir gayi hai khoon beh raha hai jaldi aao"
DISTRESS = "I want to die"
ADDRESS = "12 Test Lane, Pune"
NAME = "Ramesh Verma"
SECRETS = (MEDICINE, "seene mein", "chakkar", "khoon beh", "gir gayi", DISTRESS, "12 Test Lane")


async def a_busy_day() -> RobinWorld:
    w = await RobinWorld.start(device=True, robin_authority_calls_enabled=True)
    w.secrets.extend(SECRETS)
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family(second="+919800000103")
    await w.child_says(f"add medicine {MEDICINE} 5mg at 9am, 9pm strips 2 of 10 bought 2026-01-04")
    await w.child_says("enable device signals")
    await w.child_says("enable payment alerts")
    await w.child_says("enable authority calls")
    await w.child_says(f"parent name {NAME}")
    await w.child_says(f"address {ADDRESS}")
    parent = await w.parent()
    await w.device.pair(parent.id)

    # the daily check-in, answered with free words (a transcript)
    w.caller.answers = {"checkin.q.ate": "haan", "checkin.q.slept": "nahi", "checkin.q.pain": PARENT_WORDS, "checkin.q.mood": "udaas", "checkin.q.strange": "nahi", "checkin.q.meds": "nahi"}
    w.script_calls(CallResult.ANSWERED)
    await w.advance(hours=1)
    await w.advance(hours=12)  # the evening medicine reminder, the digest

    # a phone alert with money, the child's own distress words (care protocol), an urgent missed call with a transcript
    w.script_calls(CallResult.NO_ANSWER)
    await w.device.signal(w, "payment_notification", app="gpay", direction="debit", amount_paise=5_000_000, payee_kind="new")
    await w.child_says(DISTRESS)
    await w.child_says("I'm okay now")
    await w.hub.on_missed_call(PARENT, CHILD, [AnswerRaw(line="missed.ask_who", text=CALLER_WORDS), AnswerRaw(line="missed.ask_urgent", text="yes")])
    # SOS with a location, the desk (dry-run), then everything ends
    await w.device.sos()
    for _ in range(8):
        await w.advance(minutes=5)
    await w.parent_says("Robin, band karo")
    await w.advance(hours=2)
    return w


async def test_a_busy_day_leaves_no_pii_in_the_logs():
    w = await a_busy_day()
    try:
        assert any("authority DRY RUN" in x for x in w.logs.lines), "the capture is alive (the app does log)"
        assert_no_pii(w.logs.text(), secrets=SECRETS, what="log records")
    finally:
        await w.close()


async def test_a_busy_day_leaves_no_pii_in_the_core_audit_log():
    """The core audit log survives 'delete everything', so it is the strictest: no numbers, names, words, medicines."""
    w = await a_busy_day()
    try:
        user_id = (await w.child.user_row()).id
        entries = await w.f.c.repos.audit.list_for_user(user_id)
        assert entries
        assert_no_pii("\n".join(repr(e) for e in entries), secrets=(*SECRETS, NAME), what="core audit log")
    finally:
        await w.close()


async def test_the_family_audit_has_no_numbers_and_no_words_that_were_spoken():
    """'What Robin did today' (child-visible, erased with the family): never a number, a transcript or distress text."""
    w = await a_busy_day()
    try:
        blob = await w.audit_blob()
        assert "Called" in blob and "DRY RUN" in blob
        assert_no_pii(blob, secrets=("seene mein", "chakkar", "khoon beh", "gir gayi", DISTRESS), what="family audit")
    finally:
        await w.close()


async def test_the_family_audit_does_not_name_medicines():
    w = await a_busy_day()
    try:
        blob = await w.audit_blob()
        assert MEDICINE.lower() not in blob.lower(), "a medicine name is in the family audit"
    finally:
        await w.close()


async def test_erase_leaves_only_counts_behind():
    w = await a_busy_day()
    try:
        fam = await w.family()
        await w.child_says("delete everything for my parent")
        await w.child_says("DELETE")
        assert await w.hub.family((await w.child.user_row()).id) is None
        entries = await w.f.c.repos.audit.list_for_user((await w.child.user_row()).id)
        erased = [e for e in entries if e.action == "robin.family_erased"]
        assert len(erased) == 1 and all(isinstance(v, int) for v in erased[0].detail["counts"].values())
        assert_no_pii("\n".join(repr(e) for e in entries) + "\n" + w.logs.text(), secrets=(*SECRETS, NAME, fam.id), what="audit + logs after erase")
    finally:
        await w.close()


# ---------------------------------------------------------------------------- the helper itself: a negative control
@pytest.mark.parametrize(
    "leak",
    ["calling +919800000102 now", "tel 919800000102", "to 9800000102 failed", "number 98000 00102", "+91 9800000102", "id 123456789012", "took Zorbexin", "said: CHEST pain"],
)
def test_assert_no_pii_catches_a_leak(leak):
    with pytest.raises(AssertionError):
        assert_no_pii(["INFO fine", leak], secrets=("zorbexin", "chest pain"))


def test_assert_no_pii_passes_a_clean_log():
    assert_no_pii(["INFO robin: alert raised (tier=high)", "WARNING robin: message to the child failed (RuntimeError)", "robin: family erased (robin_records=14,robin_members=3)"], secrets=("zorbexin",))
