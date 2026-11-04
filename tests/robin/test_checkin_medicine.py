# ruff: noqa: E501
"""Daily check-in (schedule, retries, result, ladder, digests) and medicine (schedule, reminders, stock, refill, weekly count)."""

from __future__ import annotations

from datetime import date

from friday.robin import lines
from friday.robin.medicine import days_left, parse_add, parse_clock, parse_prescription_line
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, Medicine
from tests.robin.conftest import at


def answered(**said: str) -> CallOutcome:
    return CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line=f"checkin.q.{k}", text=v) for k, v in said.items()])


GOOD = {"ate": "haan", "slept": "haan", "pain": "nahi", "mood": "achha", "strange": "nahi", "meds": "haan"}


async def test_checkin_runs_at_the_time_and_sends_one_line(w):
    fam, parent = await w.family(checkin="09:00")
    w.clock.set(at(8, 30))
    await w.hub.tick()
    assert not w.caller.calls  # not yet
    w.clock.set(at(9, 1))
    w.caller.script(answered(**GOOD))
    await w.hub.tick()
    assert len(w.caller.calls) == 1 and w.caller.calls[0].purpose == "checkin"
    assert w.caller.calls[0].line_keys[0] == "checkin.greet"  # says it is an AI assistant first
    msg = w.sender.texts()[-1]
    assert "Papa checked in" in msg and "mood: achha" in msg and "Robin" not in msg.replace("Robin", "")
    await w.hub.tick()
    assert len(w.caller.calls) == 1  # one check-in a day


async def test_concern_is_flagged_and_only_a_summary_without_share_consent(w):
    fam, parent = await w.family()
    w.clock.set(at(9, 1))
    w.caller.script(answered(**{**GOOD, "pain": "haan", "mood": "udaas"}))
    await w.hub.tick()
    assert "something to note" in w.sender.texts()[-1] and "pain: yes" in w.sender.texts()[-1]
    await w.hub.fam.withdraw_consent(parent.id, "share_summary_with_child", tell_child=False)
    w.clock.set(at(9, 1, day=6))
    w.caller.script(answered(**GOOD))
    await w.hub.tick()
    assert "picked up the call" in w.sender.texts()[-1] and "mood" not in w.sender.texts()[-1]


async def test_two_retries_20_minutes_apart_then_the_ladder(w):
    fam, parent = await w.family(second=True)
    w.clock.set(at(9, 1))
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.tick()
    assert len(w.caller.calls) == 1
    w.go(minutes=10)
    await w.hub.tick()
    assert len(w.caller.calls) == 1  # not before 20 minutes
    w.go(minutes=11)
    await w.hub.tick()
    assert len(w.caller.calls) == 2
    w.go(minutes=21)
    await w.hub.tick()  # third try = the second retry; unanswered -> WhatsApp the child at once
    checkin_calls = [c for c in w.caller.calls if c.purpose == "checkin"]
    assert len(checkin_calls) == 3
    assert any("did not answer today" in t.lower() or "did not pick up" in t.lower() for t in w.sender.texts())
    w.go(minutes=21)
    await w.hub.tick()
    assert len([c for c in w.caller.calls if c.purpose == "checkin"]) == 3  # never a fourth try
    # the ladder rings the child 5 minutes after the alert, and the named second contact later
    purposes = [c.purpose for c in w.caller.calls]
    assert "escalation_child" in purposes


async def test_parent_reached_later_closes_the_ladder_with_a_fine_message(w):
    fam, parent = await w.family()
    w.clock.set(at(9, 1))
    w.caller.script(CallResult.NO_ANSWER)
    for _ in range(4):
        await w.hub.tick()
        w.go(minutes=21)
    assert await w.hub.alerts.open_count(fam) + len(await w.store.list(fam.id, "incident", status="exhausted")) >= 1
    await w.hub.parent_said("+919800000102", "namaste", "text")
    assert any("is fine" in t for t in w.sender.texts())
    assert not await w.store.list(fam.id, "incident", status=("open", "running", "exhausted"))


async def test_checkin_waits_for_quiet_hours_and_care_protocol(w):
    fam, parent = await w.family(checkin="09:00")
    await w.hub.fam.update_settings(fam, quiet_start="08:00", quiet_end="09:30")
    w.clock.set(at(9, 5))
    w.caller.script(answered(**GOOD))
    await w.hub.tick()
    assert not w.caller.calls  # quiet hours: deferred, not tried
    w.clock.set(at(9, 40))
    await w.hub.tick()
    assert len(w.caller.calls) == 1
    # care protocol active: skipped (and retried later), then answered when it ends
    w.ctx.care = lambda user_id: True
    w.clock.set(at(9, 1, day=6))
    await w.hub.tick()
    assert len(w.caller.calls) == 1
    w.ctx.care = lambda user_id: False
    w.go(minutes=31)
    await w.hub.tick()
    assert len(w.caller.calls) == 2


async def test_care_is_checked_defensively_when_absent(w):
    from friday.robin.ports import care_active_fn

    assert care_active_fn()("u") is False
    assert await w.ctx.care_active("u") is False

    async def boom(_):
        raise RuntimeError("x")

    w.ctx.care = boom
    assert await w.ctx.care_active("u") is False


async def test_digests_daily_and_on_demand(w):
    fam, parent = await w.family()
    w.clock.set(at(9, 1))
    w.caller.script(answered(**GOOD))
    await w.hub.tick()
    out = await w.hub.checkin.digest_now(fam, weekly=False)
    assert "1 of 1 check-ins answered" in out
    w.clock.set(at(20, 5))
    n_before = len(w.sender.sent)
    await w.hub.tick()
    assert len(w.sender.sent) > n_before and "Today with Papa" in w.sender.texts()[-1]
    w.sender.sent.clear()
    await w.hub.tick()
    assert not any("Today with Papa" in t for t in w.sender.texts())  # once a day


# ---------------------------------------------------------------- medicine
def test_parsers():
    assert parse_clock("8am") == "08:00" and parse_clock("8:30 pm") == "20:30" and parse_clock("18:30") == "18:30" and parse_clock("xx") is None
    m = parse_add("add medicine Amlodipine 5mg at 8am, 8pm strips 2 of 10 bought 2026-01-01", date(2026, 1, 5))
    assert isinstance(m, Medicine) and m.name == "Amlodipine" and m.dose_text == "5mg" and m.times == ["08:00", "20:00"] and m.strips == 2 and m.pills_per_strip == 10
    assert parse_add("add medicine Foo", date(2026, 1, 5)) == "no_time"
    p = parse_prescription_line("Tab Metformin 500 mg 1-0-1", date(2026, 1, 5))
    assert p and p.name == "Metformin" and p.times == ["08:00", "21:00"]
    assert parse_prescription_line("Take rest", date(2026, 1, 5)) is None


def test_stock_estimate_and_weekly_count_correction():
    m = Medicine(name="A", times=["08:00", "20:00"], strips=2, pills_per_strip=10, last_purchase_date=date(2026, 1, 1))
    assert days_left(m, date(2026, 1, 1)) == 10 and days_left(m, date(2026, 1, 6)) == 5 and days_left(m, date(2026, 3, 1)) == 0
    from datetime import UTC, datetime

    m.stock_adjust, m.stock_counted_at = 30, datetime(2026, 1, 6, tzinfo=UTC)
    assert days_left(m, date(2026, 1, 6)) == 15


async def test_reminder_taken_missed_and_unreached(w):
    fam, parent = await w.family()
    for cmd in ("add medicine Amlodipine 5mg at 8am strips 2 of 10 bought 2026-01-01",):
        res = parse_add(cmd, date(2026, 1, 5))
        await w.hub.meds.add(fam, res)
    w.clock.set(at(8, 1))
    w.caller.script(CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="med.remind", text="haan li")]))
    await w.hub.tick()
    assert [c.purpose for c in w.caller.calls] == ["medicine"] and w.caller.calls[0].line_keys == ["med.remind"]
    assert [r.status for r in await w.store.list(fam.id, "dose")] == ["taken"]
    # next day: says no -> missed and the child is told
    w.clock.set(at(8, 1, day=6))
    w.caller.script(CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="med.remind", text="nahi abhi nahi")]))
    await w.hub.tick()
    assert any("did not take Amlodipine" in t for t in w.sender.texts())
    # day after: no answer twice -> unreached (not 'missed'), no alarming message
    w.clock.set(at(8, 1, day=7))
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.tick()
    w.go(minutes=21)
    await w.hub.tick()
    assert (await w.store.list(fam.id, "dose"))[-1].status == "unreached"


async def test_no_reminder_without_consent_or_while_paused_by_the_child(w):
    fam, parent = await w.family()
    await w.hub.meds.add(fam, parse_add("add medicine X at 8am strips 1", date(2026, 1, 5)))
    await w.hub.fam.withdraw_consent(parent.id, "medicine_reminders", tell_child=False)
    w.clock.set(at(8, 5))
    await w.hub.tick()
    assert not w.caller.calls
    await w.hub.fam.give_consent(parent.id, "medicine_reminders", __import__("friday.robin.models", fromlist=["x"]).ConsentSource.ADMIN_CHAT)
    await w.hub.fam.update_settings(fam, reminders_paused_until=at(10) .replace(day=9))
    await w.hub.tick()
    assert not w.caller.calls


async def test_refill_alert_five_days_before_and_two(w):
    fam, parent = await w.family()
    await w.hub.meds.add(fam, parse_add("add medicine Amlodipine at 8am strips 1 of 10 bought 2026-01-01", date(2026, 1, 1)))
    w.clock.set(at(7, 30, day=5))  # 4 days used of 10 -> 6 left
    await w.hub.tick()
    assert not any("stock left" in t for t in w.sender.texts())
    w.clock.set(at(7, 30, day=6))  # 5 left
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 1
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 1  # once per level
    w.clock.set(at(7, 30, day=9))  # 2 left
    await w.hub.tick()
    assert sum("stock left" in t for t in w.sender.texts()) == 2


async def test_weekly_count_on_sunday_updates_stock(w):
    fam, parent = await w.family()
    await w.hub.meds.add(fam, parse_add("add medicine Amlodipine at 8am strips 3 of 10 bought 2026-01-01", date(2026, 1, 1)))
    w.clock.set(at(9, 1, day=11))  # Sunday 11 Jan 2026
    out = CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="checkin.q.ate", text="haan"), AnswerRaw(line="med.count_ask", text="12 goliyan")])
    w.caller.script(out)
    await w.hub.tick()
    assert "med.count_ask" in w.caller.calls[0].line_keys
    _, med = (await w.hub.meds.meds(fam))[0]
    assert med.stock_adjust == 12


async def test_prescription_photo_needs_the_childs_confirmation(w):
    from types import SimpleNamespace as NS

    fam, _ = await w.family()
    doc = NS(doc_type=NS(value="prescription"), fields={"m1": NS(value="Tab Metformin 500 mg 1-0-1"), "m2": NS(value="Amlodipine 5mg OD")})
    text = await w.hub.on_document_confirmed(fam.owner_user_id, doc)
    assert "Metformin" in text and "I cannot judge doses" in text
    assert not await w.hub.meds.meds(fam)  # nothing saved yet
    assert await w.hub.meds.confirm(fam, True) == 2 and len(await w.hub.meds.meds(fam)) == 2


def test_no_medical_advice_in_any_line():
    bad = ("increase", "decrease", "double", "stop taking", "skip the", "dosage should", "you should take")
    for ln in lines.all_lines():
        assert not any(b in ln.text.lower() for b in bad), ln.id
    assert any("doctor" in ln.text.lower() for ln in lines.all_lines() if ln.id.startswith("robin.checkin.pain_ack"))
