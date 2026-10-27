# ruff: noqa: E501
"""Reminders with a fake clock: schedule per state, quiet hours, weekly cap, expiry, mute, dedupe,
per-case limit, and a simulated 30 days. Nothing is sent anywhere real."""

from __future__ import annotations

from datetime import date, timedelta

from friday.core.clock import is_quiet_hours
from friday.refunds.config import RefundConfig
from friday.refunds.models import RefundCase, RefundState
from friday.refunds.reminders import next_reminder
from friday.refunds.service import RefundService
from tests.refunds.conftest import at, open_case

S = RefundState


def actions(out):
    return [o.action for o in out]


# ------------------------------------------------------------------ pure schedule
def test_schedule_offsets_per_state():
    cfg = RefundConfig()
    created = at(10, 10)
    opened = RefundCase(user_id="u", state=S.OPENED, vendor_name="X", state_changed_at=created)
    r0 = next_reminder(opened, sent_in_epoch=0, sent_total=0, cfg=cfg)
    assert (r0.stage, r0.due_at) == ("requested_q", at(11, 10))
    assert next_reminder(opened, sent_in_epoch=1, sent_total=1, cfg=cfg).due_at == at(13, 10)
    assert next_reminder(opened, sent_in_epoch=1, sent_total=1, cfg=cfg).stage == "followup"
    # then weekly
    assert next_reminder(opened, sent_in_epoch=2, sent_total=2, cfg=cfg).due_at == at(20, 10)
    assert next_reminder(opened, sent_in_epoch=3, sent_total=3, cfg=cfg).due_at == at(27, 10)
    promised = RefundCase(
        user_id="u", state=S.PROMISED, vendor_name="X", promised_date=date(2026, 11, 20),
        promised_amount_paise=100, state_changed_at=created,
    )  # fmt: skip
    assert next_reminder(promised, sent_in_epoch=0, sent_total=0, cfg=cfg).due_at == at(21, 10)
    assert next_reminder(promised, sent_in_epoch=1, sent_total=1, cfg=cfg).stage == "followup"
    rejected = opened.model_copy(update={"state": S.REJECTED})
    assert next_reminder(rejected, sent_in_epoch=1, sent_total=1, cfg=cfg) is None  # asked once


def test_no_reminder_for_closed_muted_or_over_the_case_limit():
    cfg = RefundConfig(max_nudges_per_case=2)
    base = RefundCase(user_id="u", state=S.REQUESTED, vendor_name="X", state_changed_at=at(10))
    assert next_reminder(base, sent_in_epoch=0, sent_total=0, cfg=cfg) is not None
    assert next_reminder(base, sent_in_epoch=0, sent_total=2, cfg=cfg) is None
    assert next_reminder(base.model_copy(update={"muted": True}), sent_in_epoch=0, sent_total=0, cfg=cfg) is None
    assert next_reminder(base.model_copy(update={"state": S.CLOSED}), sent_in_epoch=0, sent_total=0, cfg=cfg) is None


def test_keys_change_with_the_epoch():
    c = RefundCase(user_id="u", state=S.OPENED, vendor_name="X", state_changed_at=at(10))
    a = next_reminder(c, sent_in_epoch=0, sent_total=0, cfg=RefundConfig())
    b = next_reminder(c.model_copy(update={"state_epoch": 1}), sent_in_epoch=0, sent_total=0, cfg=RefundConfig())
    assert a.key != b.key and a.key.startswith(f"refund:{c.id}:0:")


# ------------------------------------------------------------------ the service with a fake clock
async def test_nothing_before_it_is_due_then_one_message_then_not_again(svc, alice, sender, clock):
    case = await open_case(svc, alice.id)
    assert await svc.run_user(alice.id) == []
    clock.set(at(11, 9, 59))
    assert await svc.run_user(alice.id) == []
    clock.set(at(11, 10, 1))
    out = await svc.run_user(alice.id)
    assert actions(out) == ["sent"] and out[0].stage == "requested_q"
    text = sender.texts(alice.id)[0]
    assert text.startswith("[Refund: Exampleair]") and "refund nahi aata" not in text
    assert "Isliye pooch rahi hoon" in text and "refund mute" in text  # reason + how to stop
    assert svc.store and [b.id.split(":")[-1] for b in sender.sent[0][1].buttons] == ["asked", "notyet"]
    assert await svc.run_user(alice.id) == []  # same moment: never twice
    clock.set(at(12, 10))
    assert await svc.run_user(alice.id) == []  # the next one is on day 3
    assert case.id in sender.sent[0][1].case_id


async def test_a_state_change_starts_a_fresh_schedule(svc, alice, sender, clock):
    case = await open_case(svc, alice.id)
    clock.set(at(11, 10, 1))
    await svc.run_user(alice.id)
    await svc.mark_requested(alice.id, case.id)  # new epoch: schedule restarts from now
    clock.set(at(13, 10, 1))
    assert await svc.run_user(alice.id) == []  # requested -> first check-in is 3 days after 11th
    clock.set(at(14, 10, 1))
    out = await svc.run_user(alice.id)
    assert actions(out) == ["sent"] and out[0].stage == "checkin"


async def test_promised_date_drives_the_reminder(svc, alice, sender, clock):
    case = await open_case(svc, alice.id)
    await svc.mark_promised(alice.id, case.id, date(2026, 11, 20), 450000)
    clock.set(at(20, 12))
    assert await svc.run_user(alice.id) == []  # the promised day itself: let them have it
    clock.set(at(21, 10, 5))
    out = await svc.run_user(alice.id)
    assert out[0].stage == "received_q" and "20 Nov" in out[0].text and "Rs 4,500" in out[0].text


async def test_quiet_hours_hold_a_reminder_and_it_goes_at_eight(svc, alice, sender, clock):
    await svc.propose_from_trip_cancellation(alice.id, "leg1", "Exampleair", amount_paise=450000)
    clock.set(at(10, 23, 0))
    assert actions(await svc.run_user(alice.id)) == ["held_quiet"] and sender.sent == []
    clock.set(at(11, 3, 0))
    assert actions(await svc.run_user(alice.id)) == ["held_quiet"]
    clock.set(at(11, 8, 0))
    out = await svc.run_user(alice.id)
    assert actions(out) == ["sent"] and out[0].stage == "suspect_ask"
    assert "Expected Rs 4,500 (abhi confirm nahi)" in out[0].text
    assert [b.id.split(":")[-1] for b in sender.sent[0][1].buttons] == ["yes", "no"]


async def test_a_reminder_held_too_long_is_dropped_not_sent_late(svc, alice, sender, clock):
    await open_case(svc, alice.id)
    clock.set(at(11, 23, 0))  # due 11th 10:00; held for the cap below
    svc.cfg = RefundConfig(weekly_cap=0)
    assert actions(await svc.run_user(alice.id)) == ["held_quiet"]
    clock.set(at(14, 11, 0))  # 73 h past due
    svc.cfg = RefundConfig()
    out = await svc.run_user(alice.id)
    assert actions(out) == ["expired"] and sender.sent == []
    n = await svc.store.list_nudges(alice.id, (await svc.store.list_cases(alice.id))[0].id)
    assert [x.status for x in n] == ["expired"]
    assert [x.stage for x in n] == ["requested_q"]


async def test_weekly_cap_across_cases(svc, alice, sender, clock):
    for v in ("Aair", "Bmart", "Cfood", "Dcab"):
        await svc.open_by_user(alice.id, f"Example{v}")
    clock.set(at(11, 10, 1))
    out = await svc.run_user(alice.id)
    assert sorted(actions(out)) == ["held_cap", "sent", "sent", "sent"]
    assert len(sender.sent) == 3
    clock.set(at(12, 10, 1))
    assert actions(await svc.run_user(alice.id)) == ["held_cap"]  # still inside 7 days
    clock.set(at(18, 10, 5))  # the first three sends are now 7 days old: the budget is free
    assert await svc.store.count_sent_since(alice.id, clock.now() - timedelta(days=7)) == 0
    # the held case's reminders waited past their expiry, so they were dropped, not sent late
    assert set(actions(await svc.run_user(alice.id))) <= {"expired", "sent"}


async def test_cap_zero_sends_nothing(rsettings, store, clock, sender, alice):
    svc = RefundService(rsettings.model_copy(update={"refund_weekly_cap": 0}), store, clock, sender=sender)
    await svc.open_by_user(alice.id, "Exampleair")
    clock.set(at(12, 10))
    assert actions(await svc.run_user(alice.id)) == ["held_cap"] and sender.sent == []


async def test_mute_silences_every_case_and_unmute_restores(svc, alice, sender, clock):
    await svc.open_by_user(alice.id, "Exampleair")
    assert "band" in (await svc.set_muted(alice.id, True)).text
    clock.set(at(12, 10))
    assert await svc.run_user(alice.id) == [] and sender.sent == []
    await svc.set_muted(alice.id, False)
    assert actions(await svc.run_user(alice.id)) == ["sent"]


async def test_a_failed_send_is_retried_and_not_counted(svc, alice, sender, clock):
    await svc.open_by_user(alice.id, "Exampleair")
    clock.set(at(11, 10, 1))
    sender.refuse = True
    assert actions(await svc.run_user(alice.id)) == ["failed"]
    sender.refuse = False
    clock.set(at(11, 10, 31))
    assert actions(await svc.run_user(alice.id)) == ["sent"]
    assert len(sender.sent) == 1


async def test_closed_and_unconfirmed_cases_send_nothing_more(svc, alice, sender, clock):
    case = await open_case(svc, alice.id)
    await svc.close(alice.id, case.id)
    clock.set(at(25, 10))
    assert await svc.run_user(alice.id) == [] and sender.sent == []


async def test_an_unconfirmed_suspicion_lapses_after_a_week(svc, alice, sender, clock):
    case = await svc.propose_from_order(alice.id, "t1", "Examplemart")
    clock.set(at(10, 10, 5))
    await svc.run_user(alice.id)  # the ask
    clock.set(at(12, 10, 5))
    await svc.run_user(alice.id)  # asked again
    assert len(sender.sent) == 2
    clock.set(at(17, 10, 5))
    assert actions(await svc.run_user(alice.id)) == ["lapsed"]
    c = await svc.store.get_case(alice.id, case.id)
    assert c.state == S.CLOSED and c.closed_reason.value == "unconfirmed"
    clock.set(at(30, 10))
    assert await svc.run_user(alice.id) == []


async def test_per_case_limit_stops_the_chatter(rsettings, store, clock, sender, alice):
    svc = RefundService(rsettings, store, clock, sender=sender)
    svc.cfg = RefundConfig(max_nudges_per_case=3, weekly_cap=99, chase_calls_enabled=False)
    await svc.open_by_user(alice.id, "Exampleair")
    for _ in range(80):
        clock.advance(hours=24)
        await svc.run_user(alice.id)
    assert len(sender.sent) == 3


async def test_a_simulated_30_days_respects_quiet_hours_and_the_cap(svc, alice, sender, clock):
    """Tick every 3 hours for 30 days over several cases: no message in quiet hours, never more
    than the weekly cap in any rolling 7 days, and the same reminder is never sent twice."""
    await svc.open_by_user(alice.id, "Exampleair", amount_paise=450000)
    await svc.open_by_user(alice.id, "Examplemart", amount_paise=20000)
    await svc.propose_from_trip_cancellation(alice.id, "leg9", "Exampleair Two")
    times: list = []
    seen = 0
    end = clock.now() + timedelta(days=30)
    while clock.now() < end:
        await svc.tick()
        if len(sender.sent) > seen:
            times += [clock.now()] * (len(sender.sent) - seen)
            seen = len(sender.sent)
        clock.advance(hours=3)
    assert times, "something must have been sent"
    assert not [t for t in times if is_quiet_hours(t, 22, 8)]
    for t in times:
        assert len([x for x in times if t - timedelta(days=7) < x <= t]) <= svc.cfg.weekly_cap
    keys = [m.dedupe_key for _, m in sender.sent]
    assert len(keys) == len(set(keys))
    assert len(times) <= 3 * 5  # about 3 a week for 4 weeks, not a flood
