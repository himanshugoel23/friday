"""End to end, offline: (d) cards and bills on WhatsApp, (e) the user's day and the nudge after an
event. The card rows are INVENTED example rows, enabled in tests only."""

from __future__ import annotations

from friday.core.models import AutonomyCategory, Nudge, NudgeCandidate, NudgeKind
from tests.integration.conftest import World, close_world, load_demo_rules, make_world

BILL = (
    "Your electricity bill of Rs 1,240.50 for BSES is due on 25 Jan 2026. "
    "Pay online at bsesdelhi.com"
)


# ------------------------------------------------------------------------------------- (d)
async def test_d_two_cards_then_zomato_gets_a_ranked_answer_with_a_reason(world: World):
    await load_demo_rules(world)
    r = await world.say("mere paas HDFC Regalia aur SBI Cashback hai")
    assert "HDFC Bank Regalia" in (r[-1].text or "") and "SBI Card Cashback" in (r[-1].text or "")
    r = await world.say("Zomato pe 640")  # no "kaun sa card" needed once the user has cards
    ans = r[-1]
    text = ans.text or ""
    assert world.brain.seen == []  # the savings engine answered, not the brain
    assert text.index("SBI") < text.index("HDFC")  # 5% beats 2%: ranked best first
    assert "5%" in text or "Rs 32" in text  # the reason carries the reward
    assert [b.title for b in ans.buttons]  # "which card did you use" buttons
    assert "commission" in text.lower()  # the neutrality footer
    assert "example" in text.lower() or "andaaza" in text.lower() or "confirm" in text.lower()


async def test_d_example_rows_never_produce_a_savings_claim(world: World):
    await load_demo_rules(world)
    await world.say("mere paas HDFC Regalia aur SBI Cashback hai")
    await world.say("Zomato pe 640")
    r = await world.tap("Isse pay")  # the user says they used the recommended card
    assert r
    r = await world.say("is mahine kitna bachaya")
    # the rows are EXAMPLE rows (low confidence): logged, but never counted as "Friday saved"
    assert "koi figure nahi" in (r[-1].text or "")
    assert world.brain.seen == []


async def test_d_no_cards_no_guess(world: World):
    await load_demo_rules(world)
    r = await world.say("kaun sa card Zomato pe 640")
    assert r and world.brain.seen == []
    r = await world.say("Zomato pe 640")  # no cards: not a card question, goes to the brain
    assert world.brain.seen == ["Zomato pe 640"]


async def test_d_forwarded_bill_creates_a_bill_and_the_reminders_fire_once_each(world: World):
    r = await world.say(BILL)
    prompt = r[-1]
    assert "BSES" in (prompt.text or "") and "1,240.50" in (prompt.text or "")
    assert [b.title for b in prompt.buttons] == ["Sahi hai", "Galat hai"]
    r = await world.tap("Sahi")
    assert r  # confirmed
    bills = await world.consumer.savings.bills.active_for_user(world.user.id)
    assert len(bills) == 1 and bills[0].confirmed

    sent: list[str] = []
    for day, hour in ((22, 9), (22, 11), (24, 9), (25, 9)):  # d3, (again), d1, d0
        world.set_time(world.at(hour, 5, day=day))
        before = len(world.channel.messages_to(world.phone))
        await world.tick()
        sent += [m.text or "" for m in world.channel.messages_to(world.phone)[before:]]
    assert len(sent) == 3  # 3 days before, 1 day before, on the day: never twice
    assert all("BSES" in t for t in sent)
    last = world.channel.last_to(world.phone)
    assert {"Paid"} <= {b.title for b in last.buttons} or any(
        "Paid" in b.title for b in last.buttons
    )

    await world.tap("Paid")
    world.set_time(world.at(9, 5, day=26))
    before = len(world.channel.messages_to(world.phone))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before  # paid: silence


async def test_d_a_bill_reminder_is_held_in_quiet_hours_and_sent_when_they_end(world: World):
    await world.say(BILL)
    await world.tap("Sahi")
    world.set_time(world.at(23, 0, day=24))  # the "1 din pehle" stage is live, but it is night
    before = len(world.channel.messages_to(world.phone))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before  # quiet hours 22-08 IST
    world.set_time(world.at(8, 5, day=25))
    await world.tick()
    out = [m.text or "" for m in world.channel.messages_to(world.phone)[before:]]
    assert len(out) == 1 and "BSES" in out[0]  # sent once, when the quiet hours ended


# ------------------------------------------------------------------------------------- (e)
async def test_e_interview_context_and_the_nudge_after_it(world: World):
    r = await world.say("kal 2 baje interview hai")
    assert "interview" in (r[-1].text or "").lower()
    assert world.brain.seen == []

    # during the event a message reaches the brain with the day summary in its context
    world.set_time(world.at(14, 30, day=6))
    await world.say("hello")
    ctx = world.brain.contexts[-1]
    assert ctx.day_summary and "interview" in ctx.day_summary
    assert "kal 2 baje" not in ctx.day_summary  # kinds, times and counts only
    r = await world.say("mera din")
    assert "interview" in (r[-1].text or "").lower() and world.brain.seen == ["hello"]

    # nothing while it is on, nothing before the delay, the nudge exactly after it
    before = len(world.channel.messages_to(world.phone))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before
    world.set_time(world.at(15, 20, day=6))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before
    world.set_time(world.at(15, 45, day=6))
    sent = await world.tick()
    msgs = world.channel.messages_to(world.phone)[before:]
    assert len(msgs) == 1 and len(sent) == 1
    assert "interview" in (msgs[0].text or "").lower()
    assert "isliye" in (msgs[0].text or "").lower() or "kyunki" in (msgs[0].text or "").lower()
    # one nudge only, however often the tick runs
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before + 1

    # the user's answer is kept as a note on the event
    r = await world.say("achha gaya, kal result aayega")
    assert world.brain.seen == ["hello"]
    events = await world.consumer.life.store.list_events(world.user.id)
    assert any(e.note and "achha gaya" in e.note for e in events)


async def test_e_mat_poocho_mutes_that_kind_of_nudge(world: World):
    await world.say("kal 2 baje interview hai")
    world.set_time(world.at(15, 45, day=6))
    await world.tick()
    r = await world.say("mat poocho")
    assert world.brain.seen == [] and r
    await world.say("parso 11 baje interview hai")
    world.set_time(world.at(12, 30, day=7))
    before = len(world.channel.messages_to(world.phone))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before  # muted


async def test_e_the_daily_cap_is_shared_and_extra_nudges_wait_for_the_digest(world: World):
    await world.say("kal 2 baje interview hai")
    world.set_time(world.at(13, 0, day=6))
    engine = world.c.get("proactive")
    for i in range(3):  # three normal nudges already went out today
        cand = NudgeCandidate(
            user_id=world.user.id, kind=NudgeKind.FOLLOW_UP, category=AutonomyCategory.FOLLOW_UPS,
            reason=f"pehle wala {i}", due_at=world.clock.now(), dedupe_key=f"pre:{i}",
        )  # fmt: skip
        n = await engine.process(cand)
        assert isinstance(n, Nudge) and n.sent_at is not None
    before = len(world.channel.messages_to(world.phone))
    world.set_time(world.at(15, 45, day=6))
    await world.tick()
    assert len(world.channel.messages_to(world.phone)) == before  # over the cap: digest, not sent


async def test_e_quiet_hours_nothing_after_a_late_event():
    w = await make_world()
    try:
        w.set_time(w.at(20, 0))
        await w.say("aaj 9:30 baje interview hai")  # ends 10:30 pm, the nudge would be 11:10 pm
        w.set_time(w.at(23, 15))
        before = len(w.channel.messages_to(w.phone))
        await w.tick()
        assert len(w.channel.messages_to(w.phone)) == before
        w.set_time(w.at(8, 30, day=6))  # next morning it is stale: still nothing
        await w.tick()
        assert not any(
            "interview" in (m.text or "").lower() and "kaisa" in (m.text or "").lower()
            for m in w.channel.messages_to(w.phone)[before:]
        )
    finally:
        await close_world(w)


async def test_e_memory_controls_list_and_forget(world: World):
    await world.say("kal 2 baje interview hai")
    r = await world.say("tumhe kya yaad hai")
    assert "interview" in (r[-1].text or "").lower()
    r = await world.say("bhool jao interview")
    assert world.brain.seen == []
    events = await world.consumer.life.store.list_events(world.user.id, include_inactive=False)
    assert events == []


async def test_e_a_booking_time_that_clashes_is_flagged(world: World):
    await world.say("kal 2 baje interview hai")
    at = world.at(14, 30, day=6)
    note = await world.consumer.clash_note(world.user.id, at)
    assert note and "interview" in note.lower()
    assert await world.consumer.clash_note(world.user.id, world.at(18, 0, day=6)) == ""


async def test_e_the_morning_brief_lists_the_day_once_and_only_for_those_who_opted_in():
    w = await make_world(morning_briefing=True)
    off = await make_world(morning_briefing=False)
    try:
        for x in (w, off):
            await x.say("kal 2 baje interview hai")
            x.set_time(x.at(8, 10, day=6))
        before = len(w.channel.messages_to(w.phone))
        await w.tick()
        msgs = w.channel.messages_to(w.phone)[before:]
        assert len(msgs) == 1 and "interview" in (msgs[0].text or "").lower()
        await w.tick()
        assert len(w.channel.messages_to(w.phone)) == before + 1  # once a day
        before_off = len(off.channel.messages_to(off.phone))
        await off.tick()
        assert len(off.channel.messages_to(off.phone)) == before_off  # not opted in: silence
    finally:
        await close_world(w)
        await close_world(off)
