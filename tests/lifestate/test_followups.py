"""The event-aware scheduler: timing, protected events, quiet hours, caps, mute, replies."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from friday.core.clock import IST, FakeClock
from friday.lifestate import copy
from friday.lifestate.followups import (
    FollowupScheduler,
    build_morning_brief,
    parse_mute_command,
    plan_followups,
    roll_repeats,
)
from friday.lifestate.models import (
    EventKind,
    EventSource,
    EventStatus,
    LifeCommitment,
    LifeEvent,
    Repeat,
)
from friday.lifestate.ports import BillRef

WHY = re.compile(r"\bisliye\b", re.I)


def t(h: int, m: int = 0, day: int = 19, month: int = 10) -> datetime:
    return datetime(2026, month, day, h, m, tzinfo=IST)


def ev(user, kind, start, end, **kw) -> LifeEvent:
    return LifeEvent(
        user_id=user,
        title=kw.pop("title", kind.value),
        start=start,
        end=end,
        kind=kind,
        protected=kw.pop("protected", True),
        **kw,
    )


@pytest.fixture
def make(world, settings, sender):
    clock = FakeClock(t(12))

    def build(**kw):
        return FollowupScheduler(world.store, sender, settings, clock, **kw)

    build.clock = clock
    return build


# --------------------------------------------------------------------------- after the event
async def test_after_interview_nudge_comes_40_minutes_after_the_end_once(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(11, 39))
    assert await s.run_user(world.u1) == []
    s.clock.set(t(11, 41))
    out = await s.run_user(world.u1)
    assert [o.action for o in out] == ["sent"]
    assert "Interview kaisa gaya" in sender.sent[0][1]
    s.clock.set(t(12, 30))
    assert await s.run_user(world.u1) == []  # never twice
    assert len(sender.sent) == 1


@pytest.mark.parametrize(
    "kind,minutes",
    [(EventKind.INTERVIEW, 40), (EventKind.MEETING, 20), (EventKind.APPOINTMENT, 30)],
)
async def test_delay_depends_on_kind(world, make, sender, kind, minutes):
    await world.store.save_event(ev(world.u1, kind, t(10), t(11)))
    s = make()
    s.clock.set(t(11) + timedelta(minutes=minutes - 1))
    assert await s.run_user(world.u1) == []
    s.clock.set(t(11) + timedelta(minutes=minutes))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


async def test_personal_and_other_events_get_no_followup(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.PERSONAL, t(10), t(11), protected=False))
    await world.store.save_event(ev(world.u1, EventKind.OTHER, t(10), t(11), protected=False))
    make().clock.set(t(13))
    s = make()
    s.clock.set(t(13))
    assert await s.run_user(world.u1) == []


async def test_stale_nudge_is_dropped_not_sent_late(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(20))  # 9 hours later, still before quiet hours
    out = await s.run_user(world.u1)
    assert [o.action for o in out] == ["expired"] and sender.sent == []


async def test_cancelled_event_gets_no_followup(world, make, sender):
    e = ev(world.u1, EventKind.INTERVIEW, t(10), t(11))
    e.status = EventStatus.CANCELLED
    await world.store.save_event(e)
    s = make()
    s.clock.set(t(12))
    assert await s.run_user(world.u1) == []


# --------------------------------------------------------------------------- protected events
async def test_nudge_due_during_a_protected_event_is_held_until_it_ends(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(11, 30), t(12, 30)))
    s = make()
    s.clock.set(t(11, 45))  # interview nudge was due 11:40, meeting is running
    out = await s.run_user(world.u1)
    deferred = [o for o in out if o.action == "deferred"]
    assert deferred and deferred[0].release_at == t(12, 30) and sender.sent == []
    s.clock.set(t(12, 31))
    out = await s.run_user(world.u1)
    assert "sent" in [o.action for o in out]
    assert any("Interview kaisa gaya" in m[1] for m in sender.sent)


async def test_unprotected_event_does_not_hold_nudges(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    await world.store.save_event(
        ev(world.u1, EventKind.PERSONAL, t(11, 30), t(13), protected=False)
    )
    s = make()
    s.clock.set(t(11, 45))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


async def test_back_to_back_protected_events_chain_the_hold(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(11, 30), t(12)))
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(12), t(13)))
    s = make()
    s.clock.set(t(11, 50))
    out = await s.run_user(world.u1)
    assert out[0].action == "deferred" and out[0].release_at == t(13)


# --------------------------------------------------------------------------- quiet hours / caps
async def test_quiet_hours_hold_then_stale_nudge_is_dropped(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(21, 30), t(22, 15)))
    s = make()
    s.clock.set(t(23))  # due 22:55, quiet hours
    out = await s.run_user(world.u1)
    # the "how did it go" would be stale by 8 am, so it is dropped rather than sent in the morning
    assert out[0].action in ("suppressed", "held_quiet") and sender.sent == []


async def test_daily_cap_three_then_digest_then_morning_brief(world, make, sender):
    for i in range(3):
        await world.store.save_event(
            ev(
                world.u1,
                EventKind.APPOINTMENT,
                t(6 + i // 2, 30 * (i % 2)),
                t(6 + (i + 1) // 2, 30 * ((i + 1) % 2)),
            )
        )
    # a bill due the day after tomorrow: its 10:00 nudge is the 4th message of the day
    # -> it waits for the next morning brief (it will not be stale by then)
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=21), t(9, day=21), protected=False)
    )
    s = make()
    s.clock.set(t(10, 30))
    out = await s.run_user(world.u1)
    actions = sorted(o.action for o in out)
    assert actions == ["digest", "sent", "sent", "sent"]
    assert len(sender.sent) == 3
    s.clock.set(t(8, 30, day=20))
    o = await s.send_morning_brief(world.u1)
    assert o.action == "sent" and "bill" in o.text.lower()
    fl = await world.store.list_followups(world.u1)
    assert sum(1 for f in fl if f.status == "digested") == 1


async def test_over_cap_after_event_nudge_is_dropped_because_it_would_be_stale(world, make, sender):
    for i in range(4):
        await world.store.save_event(
            ev(world.u1, EventKind.APPOINTMENT, t(8 + i), t(8 + i, 30), title=f"appt{i}")
        )
    s = make()
    s.clock.set(t(14))
    out = await s.run_user(world.u1)
    assert [o.action for o in out].count("sent") == 3
    assert [o.action for o in out].count("suppressed") == 1


async def test_cap_counts_other_proactive_messages_too(world, make, sender):
    async def others(user_id):
        return 3

    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False)
    )
    s = make(extra_sent_today=others)
    s.clock.set(t(12))
    assert [o.action for o in await s.run_user(world.u1)] == ["digest"]
    assert sender.sent == []


async def test_caps_are_per_user(world, make, sender):
    for u in (world.u1, world.u2):
        await world.store.save_event(ev(u, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]
    assert [o.action for o in await s.run_user(world.u2)] == ["sent"]


# --------------------------------------------------------------------------- mute and stop
async def test_muted_topic_is_never_sent_and_other_topics_still_are(world, make, sender):
    await world.store.set_topic(world.u1, "after_event", muted=True)
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False)
    )
    s = make()
    s.clock.set(t(12))
    out = {o.topic.split(":")[0]: o.action for o in await s.run_user(world.u1)}
    assert out["after_event"] == "muted" and out["bill_due"] == "sent"
    assert len(sender.sent) == 1 and "bill" in sender.sent[0][1].lower()


async def test_kind_specific_mute_and_all_mute(world, make, sender):
    await world.store.set_topic(world.u1, "after_event:interview", muted=True)
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(10), t(10, 30)))
    s = make()
    s.clock.set(t(12))
    out = {o.topic: o.action for o in await s.run_user(world.u1)}
    assert out["after_event:interview"] == "muted" and out["after_event:meeting"] == "sent"
    await world.store.set_topic(world.u2, "all", muted=True)
    await world.store.save_event(ev(world.u2, EventKind.INTERVIEW, t(10), t(11)))
    assert [o.action for o in await s.run_user(world.u2)] == ["muted"]


async def test_mute_can_be_lifted(world, make, sender):
    await world.store.set_topic(world.u1, "after_event", muted=True)
    await world.store.set_topic(world.u1, "after_event", muted=False)
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


@pytest.mark.parametrize(
    "text,action,topic,channel",
    [
        ("mat poocho", "mute", None, None),
        ("Mat pucho", "mute", None, None),
        ("stop", "mute", None, None),
        ("ye mat bhejo", "mute", None, None),
        ("bas karo", "mute", None, None),
        ("interview ke baare mein mat poocho", "mute", "after_event:interview", None),
        ("meeting ke baad mat poocho", "mute", "after_event:meeting", None),
        ("bill ke reminder band karo", "mute", "bill_due", None),
        ("subah ka brief band karo", "mute", "morning_brief", None),
        ("sab band karo", "mute", "all", None),
        ("reminders band kar do", "mute", "reminders", None),
        ("phir se poocho", "unmute", "after_event", None),
        ("bill reminder phir se chalu karo", "unmute", "bill_due", None),
        ("interview ke baad voice note bhejo", "channel", "after_event:interview", "voice_note"),
        ("bill ke liye call karke batana", "channel", "bill_due", "call"),
        ("interview poochna text par hi", "channel", "after_event:interview", "text"),
    ],
)
def test_mute_command_table(text, action, topic, channel):
    c = parse_mute_command(text)
    assert c is not None, text
    assert (c.action, c.topic, c.channel) == (action, topic, channel)


@pytest.mark.parametrize(
    "text",
    [
        "kal 2 baje interview hai",
        "mere ghar ki light band kar do aur ye bhi dekh lo ki sab theek hai ya nahi bhai",
        "stop by the chemist on the way home and pick up the medicine please remind me",
        "hello",
        "",
    ],
)
def test_ordinary_sentences_are_not_mute_commands(text):
    assert parse_mute_command(text) is None


async def test_stop_after_a_nudge_mutes_that_topic(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    await s.run_user(world.u1)
    r = await s.handle_reply(world.u1, "mat poocho")
    assert r.handled and r.kind == "mute" and r.topic == "after_event"
    prefs = {p.topic: p for p in await world.store.list_topics(world.u1)}
    assert prefs["after_event"].muted
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(13), t(14)))
    s.clock.set(t(15))
    out = await s.run_user(world.u1)
    assert [o.action for o in out] == ["muted"]


async def test_bare_stop_with_nothing_recent_mutes_everything(world, make):
    s = make()
    r = await s.handle_reply(world.u1, "stop")
    assert r.kind == "mute" and r.topic == "all"


async def test_ignored_nudges_back_off_but_answers_reset(world, make, sender):
    s = make()
    outcomes = []
    for i in range(3):
        day = 10 + i
        await world.store.save_event(
            ev(world.u1, EventKind.MEETING, t(10, day=day), t(11, day=day))
        )
        s.clock.set(t(12, day=day))
        outcomes += [o.action for o in await s.run_user(world.u1)]  # nobody answers
    # two unanswered nudges in a row -> the third is held back (existing ignore-learning)
    assert outcomes == ["sent", "sent", "suppressed"]

    # a different user who answers keeps getting them
    s2 = make()
    got = []
    for i in range(4):
        day = 10 + i
        await world.store.save_event(
            ev(world.u2, EventKind.MEETING, t(10, day=day), t(11, day=day))
        )
        s2.clock.set(t(12, day=day))
        got += [o.action for o in await s2.run_user(world.u2)]
        await s2.handle_reply(world.u2, "theek raha")
    assert got == ["sent"] * 4


# --------------------------------------------------------------------------- replies
async def test_reply_is_stored_as_a_note_on_the_event(world, make, sender):
    e = ev(world.u1, EventKind.INTERVIEW, t(10), t(11))
    await world.store.save_event(e)
    s = make()
    s.clock.set(t(12))
    await s.run_user(world.u1)
    r = await s.handle_reply(world.u1, "accha gaya, next round parso 4 baje hai")
    assert r.handled and r.kind == "note" and r.event_id == e.id
    stored = await world.store.get_event(world.u1, e.id)
    assert "accha gaya" in stored.note
    # the follow-up answer also created the next-round event
    kinds = [x.start for x in await world.store.list_events(world.u1)]
    assert t(16, day=21) in kinds
    # answered: it is not asked again and a second reply is not a note
    assert (await s.handle_reply(world.u1, "thanks")).handled is False


async def test_reply_without_a_recent_nudge_is_not_ours(world, make):
    assert (await make().handle_reply(world.u1, "accha gaya")).handled is False


async def test_task_request_in_reply_is_left_to_other_handlers(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    await s.run_user(world.u1)
    r = await s.handle_reply(world.u1, "dentist book kar do kal")
    assert r.handled is False


# --------------------------------------------------------------------------- channels
async def test_text_by_default_voice_only_after_opt_in_for_that_topic(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    await s.run_user(world.u1)
    assert {c for _, _, c in sender.sent} == {"text"} and sender.sent  # nothing opted in

    r = await s.handle_reply(world.u1, "interview ke baad voice note bhejo")
    assert r.kind == "channel"
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(13), t(14)))
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(13), t(13, 30)))
    sender.sent.clear()
    s.clock.set(t(15))
    await s.run_user(world.u1)
    by_text = {txt.split()[0]: ch for _, txt, ch in sender.sent}
    assert by_text["Interview"] == "voice_note" and by_text["Meeting"] == "text"


async def test_a_call_is_never_chosen_without_opt_in(world, make, sender):
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False)
    )
    s = make()
    s.clock.set(t(12))
    await s.run_user(world.u1)
    assert all(ch == "text" for _, _, ch in sender.sent)


async def test_sender_failure_is_retried_next_pass(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11)))
    s = make()
    s.clock.set(t(12))
    sender.ok = False
    assert [o.action for o in await s.run_user(world.u1)] == ["failed"]
    sender.ok = True
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


# ---------------------------------------------- before / bills / commitments
class Travel:
    async def minutes_needed(self, event):
        return 45


async def test_before_event_with_travel_buffer_says_when_to_leave(world, make, sender):
    await world.store.save_event(
        ev(world.u1, EventKind.INTERVIEW, t(14), t(15), location="Acme Tower")
    )
    s = make(travel=Travel())
    s.clock.set(t(12, 44))  # leave by 13:15, nudge 30 min earlier = 12:45
    assert await s.run_user(world.u1) == []
    s.clock.set(t(12, 46))
    out = await s.run_user(world.u1)
    assert [o.action for o in out] == ["sent"]
    text = sender.sent[0][1]
    assert "nikalna" in text and "1:15" in text and WHY.search(text)


async def test_before_event_without_hook_uses_default_lead_and_stops_at_start(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15)))
    s = make()
    s.clock.set(t(12, 29))
    assert await s.run_user(world.u1) == []
    s.clock.set(t(12, 31))  # 90 minutes before
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


async def test_before_event_not_sent_in_the_last_minutes(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(14), t(15)))
    s = make()
    s.clock.set(t(13, 58))
    assert [o.action for o in await s.run_user(world.u1)] == ["expired"]


async def test_bill_nudge_two_days_before_with_pay_link(world, make, sender):
    class Bills:
        async def pending_bills(self, user_id, now):
            return [BillRef("b1", t(20, day=20).date(), "Electricity", "https://pay.example/b1")]

    s = make(bills=Bills())
    s.clock.set(t(9, day=18))
    assert await s.run_user(world.u1) == []
    s.clock.set(t(10, 5, day=18))
    out = await s.run_user(world.u1)
    assert [o.action for o in out] == ["sent"]
    assert "2 din" in sender.sent[0][1] and "https://pay.example/b1" in sender.sent[0][1]
    s.clock.set(t(12, day=18))
    assert await s.run_user(world.u1) == []  # once


async def test_generic_bill_event_without_w3(world, make, sender):
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False, title="bijli")
    )
    s = make()
    s.clock.set(t(11, day=19))  # 1 day left
    out = await s.run_user(world.u1)
    assert out[0].action == "sent" and "kal" in sender.sent[0][1]


async def test_bill_in_quiet_hours_is_held(world, make, sender):
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False)
    )
    s = make()
    s.clock.set(t(23, day=18))
    out = await s.run_user(world.u1)
    assert out[0].action == "held_quiet" and out[0].release_at == t(8, day=19)
    assert sender.sent == []
    s.clock.set(t(8, 1, day=19))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]


async def test_daily_medicine_commitment_fires_each_day_once(world, make, sender):
    c = LifeCommitment(
        user_id=world.u1,
        text="mummy ki dawai",
        due=t(8, day=20),
        repeat=Repeat(freq="daily", time="08:00"),
    )
    await world.store.save_commitment(c)
    s = make()
    s.clock.set(t(8, 2, day=20))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]
    assert "mummy ki dawai" in sender.sent[0][1]
    s.clock.set(t(9, day=20))
    assert await s.run_user(world.u1) == []
    s.clock.set(t(8, 2, day=21))
    assert [o.action for o in await s.run_user(world.u1)] == ["sent"]
    assert len(sender.sent) == 2


async def test_one_off_commitment_and_done_commitment(world, make, sender):
    done = LifeCommitment(user_id=world.u1, text="done thing", due=t(9), status="done")
    todo = LifeCommitment(user_id=world.u1, text="passport lena", due=t(9))
    await world.store.save_commitment(done)
    await world.store.save_commitment(todo)
    s = make()
    s.clock.set(t(9, 5))
    await s.run_user(world.u1)
    assert len(sender.sent) == 1 and "passport" in sender.sent[0][1]


async def test_monthly_bill_rolls_to_next_month(world):
    e = ev(
        world.u1,
        EventKind.BILL_DUE,
        t(9, day=5, month=10),
        t(9, day=5, month=10),
        protected=False,
        repeat=Repeat(freq="monthly", time="09:00", day_of_month=5),
    )
    await world.store.save_event(e)
    assert await roll_repeats(world.store, world.u1, t(12, day=6)) == 1
    starts = [x.start for x in await world.store.list_events(world.u1)]
    assert t(9, day=5, month=11) in starts
    assert await roll_repeats(world.store, world.u1, t(12, day=7)) == 0


# --------------------------------------------------------------------------- why-clause
def test_every_proactive_copy_line_states_why_and_how_to_stop():
    now = t(12)
    lines = [
        copy.after_event(k, t(11))
        for k in (
            EventKind.INTERVIEW,
            EventKind.MEETING,
            EventKind.APPOINTMENT,
            EventKind.TRAVEL,
            EventKind.OTHER,
        )
    ]
    lines += [copy.before_event(k, t(14)) for k in EventKind]
    lines += [copy.before_event(EventKind.INTERVIEW, t(14), t(13, 15))]
    lines += [copy.bill_due(d, t(20, day=21), now) for d in (-1, 0, 1, 2)]
    lines += [copy.bill_due(2, t(20, day=21), now, "https://pay.example/x")]
    lines += [copy.commitment_due("mummy ki dawai")]
    for ln in lines:
        assert WHY.search(ln), ln
        assert "mat poocho" in ln, ln
    b = copy.brief(["10:00: x"], "Suggestion", 2)
    assert WHY.search(b) and "brief band" in b


async def test_every_message_the_scheduler_sends_has_a_why(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(10), t(11), location="X"))
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=20), t(9, day=20), protected=False)
    )
    await world.store.save_commitment(
        LifeCommitment(user_id=world.u1, text="call mummy", due=t(11, 50))
    )
    s = make(travel=Travel())
    s.clock.set(t(11, 55))
    await s.run_user(world.u1)
    s.clock.set(t(12))
    await s.run_user(world.u1)
    assert len(sender.sent) >= 2
    for _, text, _ in sender.sent:
        assert WHY.search(text), text


# --------------------------------------------------------------------------- morning brief
async def test_brief_empty_is_not_sent(world, make, sender):
    b = await build_morning_brief(world.store, world.u1, t(8, 30))
    assert b.text is None
    s = make()
    s.clock.set(t(8, 30))
    o = await s.send_morning_brief(world.u1)
    assert o.action == "suppressed" and sender.sent == []
    assert await s.send_morning_brief(world.u1) is None  # decided for today


async def test_brief_few_lines_and_one_suggestion(world):
    await world.store.save_event(
        ev(world.u1, EventKind.INTERVIEW, t(14), t(15), title="Acme round 2")
    )
    await world.store.save_event(
        ev(world.u1, EventKind.BILL_DUE, t(9, day=19), t(9, day=19), protected=False)
    )
    b = await build_morning_brief(world.store, world.u1, t(8, 30))
    assert b.text and len(b.lines) == 2 and b.more == 0
    assert "Acme round 2" in b.text and "bill aaj due" in b.text
    assert b.suggestion and "bill" in b.suggestion.lower()
    assert WHY.search(b.text)


async def test_brief_many_lines_are_capped(world):
    for i in range(10):
        await world.store.save_event(
            ev(
                world.u1,
                EventKind.PERSONAL,
                t(9 + i % 5, i * 5),
                t(10 + i % 5, i * 5),
                protected=False,
                title=f"item{i}",
            )
        )
    b = await build_morning_brief(world.store, world.u1, t(8, 30), max_lines=5)
    assert len(b.lines) == 5 and b.more == 5 and "aur 5 cheezein" in b.text
    assert b.text.count("\n- ") <= 6


async def test_brief_suggests_leaving_time_and_flags_clashes(world):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15), location="Acme"))
    b = await build_morning_brief(world.store, world.u1, t(8, 30), travel=Travel())
    assert b.suggestion and "nikal" in b.suggestion
    await world.store.save_event(ev(world.u1, EventKind.MEETING, t(14, 30), t(15, 30)))
    b = await build_morning_brief(world.store, world.u1, t(8, 30))
    assert b.suggestion and "ek hi time" in b.suggestion


async def test_brief_uses_cleaned_titles_for_calendar_events(world):
    await world.store.save_event(
        LifeEvent(
            user_id=world.u1,
            title="Claim prize at http://evil.example now 9876543210",
            start=t(11),
            end=t(12),
            kind=EventKind.OTHER,
            source=EventSource.CALENDAR,
            source_ref="g1",
        )
    )
    b = await build_morning_brief(world.store, world.u1, t(8, 30))
    assert "evil" not in b.text and "9876543210" not in b.text


async def test_brief_not_before_8_once_a_day_muted_and_per_user(world, make, sender):
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15)))
    await world.store.save_event(ev(world.u2, EventKind.INTERVIEW, t(14), t(15)))
    s = make()
    s.clock.set(t(7, 30))
    assert await s.send_morning_brief(world.u1) is None
    s.clock.set(t(8, 5))
    assert (await s.send_morning_brief(world.u1)).action == "sent"
    assert await s.send_morning_brief(world.u1) is None  # once a day
    await world.store.set_topic(world.u2, "morning_brief", muted=True)
    assert (await s.send_morning_brief(world.u2)).action == "muted"
    assert [u for u, _, _ in sender.sent] == [world.u1]


async def test_brief_in_quiet_hours_configuration_is_held(world, make, sender, settings):
    settings.quiet_hours_end = 9
    await world.store.save_event(ev(world.u1, EventKind.INTERVIEW, t(14), t(15)))
    s = make()
    s.clock.set(t(8, 30))
    assert (await s.send_morning_brief(world.u1)).action == "held_quiet"
    assert sender.sent == []


def test_plan_is_pure_and_keys_are_stable():
    e = ev("u", EventKind.INTERVIEW, t(10), t(11))
    a = plan_followups([e], [], t(9))
    b = plan_followups([e], [], t(9))
    assert [p.key for p in a] == [p.key for p in b]
    assert {p.base_topic for p in a} == {"after_event", "before_event"}
    moved = e.model_copy(update={"start": t(12), "end": t(13)})
    assert {p.key for p in plan_followups([moved], [], t(9))}.isdisjoint({p.key for p in a})
