# ruff: noqa: E501
from __future__ import annotations

from datetime import datetime

from friday.core.clock import IST
from friday.core.models import ReplyButton
from friday.receptionist import sim
from friday.receptionist.classify import Classifier, FakeUrgencyModel
from friday.receptionist.identify import Route
from friday.receptionist.models import CallOutcomeKind, MessageStatus, ReceptionistConfig, Urgency

U = sim.USER_ID


def c(cid: str):
    return next(x for x in sim.callers() if x.id == cid)


async def call(w, cid):
    return await sim.run_caller(w, c(cid))


async def test_urgent_call_is_pushed_at_once_with_three_buttons():
    w = await sim.make_world()
    r = await call(w, "urgent-accident-hinglish")
    assert r.ok and r.pushes == 1
    uid, text, buttons = w.sent[-1]
    assert uid == U and "URGENT" in text and "Suman" in text and "+919100000010" in text
    assert [b.title for b in buttons] == ["Call back", "Ignore", "Block"]
    assert all(b.id.startswith("rcp:") and len(b.title) <= 20 for b in buttons)
    stored = (await w.store.list_messages(U))[0]
    assert stored.status == MessageStatus.NOTIFIED and stored.notified_at


async def test_urgent_push_is_sent_even_in_quiet_hours_but_normal_waits_for_the_morning():
    w = await sim.make_world()
    w.clock.set(datetime(2026, 10, 23, 2, 0, tzinfo=IST))  # 2 am, inside 22:00-08:00
    await call(w, "urgent-accident-hinglish")
    await call(w, "doctor-clinic")
    await call(w, "spam-loan-hinglish")
    assert len(w.sent) == 1  # only the urgent one
    assert await w.service.tick([U]) == 0  # quiet hours: nothing yet
    w.clock.set(datetime(2026, 10, 23, 8, 5, tzinfo=IST))
    assert await w.service.tick([U]) == 1
    digest = w.sent[-1][1]
    assert "appointment" in digest and "spam" in digest.lower()
    assert w.sent[-1][2] == []
    assert await w.service.tick([U]) == 0  # sent once: not again
    statuses = {m.status for m in await w.store.list_messages(U)}
    assert statuses == {MessageStatus.NOTIFIED}


async def test_a_call_without_a_message_is_still_reported_in_the_digest():
    w = await sim.make_world()
    await call(w, "hangs-up-at-once")
    w.clock.set(datetime(2026, 10, 23, 9, 0, tzinfo=IST))
    await w.service.tick([U])
    assert "+919100000036" in w.sent[-1][1] and "koi message nahi" in w.sent[-1][1]


async def test_buttons_call_back_ignore_block():
    w = await sim.make_world()
    await call(w, "urgent-accident-hinglish")
    m = (await w.store.list_messages(U))[0]
    cb = await w.service.on_button(U, f"rcp:{m.id}:callback")
    assert "+919100000010" in cb[0]
    assert (await w.store.get_message(U, m.id)).status == MessageStatus.CALLED_BACK
    ig = await w.service.on_button(U, f"rcp:{m.id}:ignore")
    assert "ignore" in ig[0].lower()
    bl = await w.service.on_button(U, f"rcp:{m.id}:block")
    assert "block" in bl[0].lower() and "phone" in bl[0].lower()
    assert await w.store.is_blocked(U, "+919100000010")
    # the next call from that number is ended politely and nothing is stored from it
    w2 = [x for x in await w.store.list_messages(U)]
    r = await sim.run_caller(w, sim.Caller("again", "again", "hinglish", "+919100000010",
                                          ["Hello main Suman bol rahi hoon"], scenario="normal"))  # fmt: skip
    assert r.spoken[0][0] == "blocked.end" and r.pushes == 0
    assert len(await w.store.list_messages(U)) == len(w2) + 1  # counted for the caps, no content
    last = (await w.store.list_messages(U))[-1]
    assert last.reason is None and last.snippet is None


async def test_a_button_of_another_user_or_a_stale_one_reveals_nothing():
    w = await sim.make_world()
    await call(w, "urgent-accident-hinglish")
    m = (await w.store.list_messages(U))[0]
    text, buttons = await w.service.on_button("someone-else", f"rcp:{m.id}:callback")
    assert "9100000010" not in text and buttons == []
    stale, _ = await w.service.on_button(U, "rcp:doesnotexist:block")
    assert "available" in stale or "nahi" in stale
    assert await w.service.on_button(U, "q:abc:1") is None  # not ours
    assert await w.service.on_button(U, "rcp:x:explode") is not None
    assert not await w.store.is_blocked("someone-else", "+919100000010")


async def test_kill_switch_answers_politely_stores_nothing_and_pushes_nothing():
    w = await sim.make_world()
    r = await call(w, "kill-switch")
    assert r.ok and r.spoken[0][0] == "blocked.end" and w.sent == []
    assert await w.store.list_messages(U) == []


async def test_caps_per_caller_and_per_user():
    w = await sim.make_world()
    assert (await call(w, "caller-over-hourly-cap")).outcome == "cap_reached"
    w2 = await sim.make_world()
    w2.service.per_user_per_day = 2
    ok1 = await call(w2, "doctor-clinic")
    ok2 = await call(w2, "courier-delivery")
    capped = await call(w2, "landlord-hinglish")
    assert ok1.outcome == ok2.outcome == "message" and capped.outcome == "cap_reached"
    assert capped.spoken[0][0] == "cap.end"


async def test_unknown_redirecting_number_is_never_attributed_to_a_user():
    w = await sim.make_world()
    await call(w, "unrouted-unknown-redirect")
    msgs = list(w.store.messages.values())
    assert len(msgs) == 1 and msgs[0].user_id is None and w.sent == []
    assert await w.store.list_messages(U) == []


async def test_direct_calls_are_not_claimed():
    w = await sim.make_world()
    port = sim.ScriptedPort(c("doctor-clinic"), w.mono)
    assert await w.service.handle_call(port, "+919100000015", None) is None  # front door keeps it
    assert port.spoken == []
    assert (await w.service.claims(None, None)).route == Route.NOT_FORWARDED


async def test_failed_send_keeps_the_message_for_the_digest():
    w = await sim.make_world()

    async def boom(uid, text, buttons):
        raise RuntimeError("whatsapp down")

    w.service.send = boom
    await call(w, "urgent-accident-hinglish")
    m = (await w.store.list_messages(U))[0]
    assert m.status == MessageStatus.NEW  # not lost, not marked as sent
    w.clock.set(datetime(2026, 10, 23, 9, 0, tzinfo=IST))
    sent = []

    async def ok(uid, text, buttons):
        sent.append(text)

    w.service.send = ok
    assert await w.service.tick([U]) == 1 and "Suman" in sent[0]


async def test_model_hook_can_raise_a_normal_call_but_not_touch_urgent_ones():
    model = FakeUrgencyModel({"neighbour": {"urgency": "urgent", "reason": "flooding"}})
    w = await sim.make_world(classifier=Classifier(model))
    caller = sim.Caller("m", "m", "en", "+919100000077",
                        ["I'm Omar, your neighbour, there is water coming through the ceiling and I think it is serious", "yes"])  # fmt: skip
    r = await sim.run_caller(w, caller)
    assert r.urgency == "urgent"  # 'serious' is a rule word; the model was not needed
    caller2 = sim.Caller("m2", "m2", "en", "+919100000078",
                         ["I'm Omar, your neighbour, there is a dripping noise from your balcony pipe again", "yes"])  # fmt: skip
    r2 = await sim.run_caller(w, caller2)
    assert r2.urgency == "urgent" and r2.pushes == 1  # raised by the (fake) model
    assert model.seen and set(model.seen[0]) == {"reason", "caller_name"}


# ------------------------------------------------------------------ "what did I miss?"
async def test_what_did_i_miss_text_and_spoken():
    w = await sim.make_world()
    for cid in ("family-mummy-urgent-contact", "doctor-clinic", "courier-delivery", "spam-loan-hinglish"):
        await call(w, cid)
    for q in ("what did I miss?", "Friday, kya miss hua", "kisne call kiya", "any missed call"):
        assert w.service.is_missed_question(q), q
    assert not w.service.is_missed_question("book a table for two")
    sent = len(w.sent)
    assert await w.service.handle_text(U, "what did I miss?")
    text = w.sent[sent][1]
    assert "4 call" in text and "1 urgent" in text and "2 normal" in text and "1 spam" in text
    assert "Mummy" in text and "appointment" in text and "parcel" in text
    spoken = await w.service.missed_spoken(U)
    assert "4 call" in spoken and "urgent" in spoken and "Mummy" in spoken
    assert len(spoken.split()) < 60  # short enough to say
    assert not await w.service.handle_text(U, "hello there")


async def test_what_did_i_miss_when_nothing_and_with_a_calendar():
    w = await sim.make_world()
    assert "no new missed calls" in (await w.service.missed_text(U, "en"))
    assert "koi nayi miss call nahi" in (await w.service.missed_spoken(U)).lower()

    class Cal:
        async def events_today(self, user_id, now):
            return ["10:00 AM Standup", "4:00 PM Dentist"]

    w.service.calendar = Cal()
    await call(w, "doctor-clinic")
    txt = await w.service.missed_text(U, "en")
    assert "Standup" in txt and "Dentist" in txt

    class BadCal:
        async def events_today(self, user_id, now):
            raise RuntimeError("calendar down")

    w.service.calendar = BadCal()
    assert "appointment" in await w.service.missed_text(U, "en")  # a failing calendar never blocks


async def test_blocked_calls_are_not_in_what_did_i_miss():
    w = await sim.make_world()
    await call(w, "blocked-number")
    assert "no new missed calls" in await w.service.missed_text(U, "en")


async def test_english_user_gets_english_summaries():
    w = await sim.make_world()
    cfg = sim.default_config().model_copy(update={"language": "en"})
    await w.store.save_config(U, cfg)
    await call(w, "urgent-english-ambulance")
    text = w.sent[-1][1]
    assert text.startswith("URGENT:") and "just called" in text


def test_quiet_hours_window_wraps_midnight():
    q = ReceptionistConfig().quiet_hours
    assert q.contains(23) and q.contains(2) and not q.contains(12) and not q.contains(8)
    assert Urgency.URGENT.value == "urgent" and CallOutcomeKind.BLOCKED.value == "blocked"
    assert isinstance(ReplyButton(id="rcp:1:block", title="Block"), ReplyButton)
