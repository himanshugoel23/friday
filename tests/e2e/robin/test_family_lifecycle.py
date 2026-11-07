# ruff: noqa: E501
"""The whole family lifecycle through the real container, pipeline and RobinHub (tested with fakes):

child chat -> consent by the child -> the parent is NOTIFIED (voice note + text) -> daily check-in -> the parent says 'band karo' (PAUSED, child told,
only the PARENT resumes) -> check-in unanswered x3 -> ladder (child WhatsApp, child call, second contact) -> the parent answers -> the ladder closes.
"""

from __future__ import annotations

from friday.robin.models import CallResult, ConsentSource, FamilyStatus
from tests.e2e.robin.harness import SECOND, index_of, line


def count(texts: list[str], expected: str) -> int:
    return sum(1 for t in texts if expected in t)


# ---------------------------------------------------------------------------- 1. set up by the child, parent notified
async def test_child_sets_up_robin_and_the_parent_is_notified(world):
    world.script_calls(CallResult.ANSWERED)  # the optional introduction call is picked up
    fam = await world.setup_family()

    assert fam.status == FamilyStatus.ACTIVE
    texts = world.child_texts()
    # order of what the child reads: the questions in sequence, then 'all set', then the result of the introduction call
    order = [line("setup.start", rel="father"), line("setup.ask_language"), line("setup.ask_time"), line("setup.ask_quiet", start="22:00", end="07:00"), line("setup.ask_second"), line("setup.ask_sensitivity"), line("setup.ask_child_call"), line("setup.done")]
    at = -1
    for exp in order:
        at = index_of(texts, exp[:60], at + 1)
    assert count(texts, "Papa agreed") == 0  # the child consents; the parent is told, not asked

    # the child's yes is on file, as the child's, for the four non-sensitive items; nothing sensitive is on
    parent = await world.parent()
    consents = [c for c in await world.store.consents(fam.id, parent.id) if c.active]
    assert {c.item for c in consents} == {"daily_checkin_calls", "medicine_reminders", "scam_check", "share_summary_with_child"}
    assert {c.given_by for c in consents} == {"admin_on_behalf"} and {c.source for c in consents} == {ConsentSource.ADMIN_CHAT}
    assert not {c.item for c in consents} & {"device_signals", "payment_alerts", "location", "authority_calls", "call_listening"}

    # the parent got ONE notice: a voice note and the same text on WhatsApp, before any call
    assert len(world.channel.voice_notes) == 1 and len(world.channel.texts) == 1
    assert world.channel.texts[0][1] == world.channel.voice_notes[0][1]
    assert "AI assistant" in world.channel.texts[0][1] and "Robin" in world.channel.texts[0][1]
    events = [r.data["event"] for r in await world.audit_rows()]
    assert events.index("notify") < events.index("call")
    assert [(c.role, c.purpose) for c in world.caller.calls] == [("parent", "intro")]  # the only call so far
    assert index_of(world.child_texts(), "heard the introduction")  # the child hears the outcome of the intro call


async def test_setup_before_the_notice_never_rings_the_parent(world):
    """Half-way through the chat nothing has been sent or dialled."""
    await world.child_says("set up Robin for my father")
    await world.child_says("+919800000102")
    await world.child_says("hinglish")
    assert world.calls() == [] and world.channel.texts == [] and world.channel.voice_notes == []
    assert (await world.family()).status == FamilyStatus.ONBOARDING


# ---------------------------------------------------------------------------- 2. the daily check-in
async def test_daily_check_in_at_the_set_time_and_the_child_hears_the_result(world):
    world.script_calls(CallResult.ANSWERED)
    await world.setup_family(checkin="9am")
    world.caller.answers = {"checkin.q.ate": "haan", "checkin.q.slept": "haan", "checkin.q.pain": "nahi", "checkin.q.mood": "theek", "checkin.q.strange": "nahi"}
    n_before = len(world.child_texts())

    await world.advance(minutes=30)  # 08:30: not yet
    assert world.calls(purpose="checkin") == []
    await world.advance(minutes=30)  # 09:00
    (call,) = world.calls(purpose="checkin")
    assert call.role == "parent" and call.line_keys[0] == "checkin.greet" and call.line_keys[-1] == "checkin.bye"
    fresh = world.child_texts()[n_before:]
    assert len(fresh) == 1 and "Papa" in fresh[0]  # one line to the child

    await world.advance(hours=1)
    assert len(world.calls(purpose="checkin")) == 1  # once a day


# ---------------------------------------------------------------------------- 3. the parent stops Robin; only the parent resumes
async def test_parent_says_band_karo_robin_pauses_and_only_the_parent_resumes(world):
    world.script_calls(CallResult.ANSWERED)
    fam = await world.setup_family()
    parent = await world.parent()
    n_child = len(world.child_texts())
    n_notes = len(world.channel.texts)

    reply = await world.parent_says("Robin, band karo", via="text")
    assert reply is not None and reply.action == "paused"
    assert (await world.family()).status == FamilyStatus.PAUSED and (await world.parent()).paused
    fresh = world.child_texts()[n_child:]
    assert fresh == [line("pause.parent", rel="x")]  # the child is told once
    assert len(world.channel.texts) == n_notes + 1 and len(world.channel.voice_notes) == 2  # the parent gets the acknowledgement as text + voice note

    # nothing rings, tomorrow included
    calls_before = len(world.caller.calls)
    await world.advance(hours=1)  # 09:00 check-in time
    await world.advance(days=1)
    assert len(world.caller.calls) == calls_before and world.calls(purpose="checkin") == []

    # the child (admin) cannot resume it: refused and audited
    assert await world.hub.fam.resume(parent.id, "admin_chat", actor="admin_on_behalf") is False
    assert (await world.family()).status == FamilyStatus.PAUSED
    assert "resume_refused" in [r.data["event"] for r in await world.audit_rows()]
    # ... and the child's own words do not resume it either
    await world.child_says("resume Robin")
    assert (await world.family()).status == FamilyStatus.PAUSED

    # the parent resumes
    reply = await world.parent_says("shuru karo", via="text")
    assert reply is not None and reply.action == "resumed"
    assert (await world.family()).status == FamilyStatus.ACTIVE and not (await world.parent()).paused
    assert line("resume.parent", rel="x") in world.child_texts()
    world.clock.advance(days=1)
    await world.advance(minutes=1)
    assert len(world.calls(purpose="checkin")) >= 1  # check-ins are back
    assert fam.id == (await world.family()).id


# ---------------------------------------------------------------------------- 4. unanswered x3 -> the ladder -> the parent answers
async def test_three_unanswered_check_ins_start_the_ladder_and_a_word_from_the_parent_closes_it(world):
    sent_to_second: list[str] = []

    async def second_sender(member, text):  # the second contact's WhatsApp (a recording fake replaces the production sender)
        sent_to_second.append(text)

    world.hub.ctx.extra_senders["second"] = second_sender
    world.script_calls(CallResult.ANSWERED)
    await world.setup_family(second=SECOND)
    world.script_calls(CallResult.NO_ANSWER)  # nobody picks up from now on
    n_child = len(world.child_texts())

    await world.advance(hours=1)  # 09:00 try 1
    await world.advance(minutes=20)  # 09:20 try 2
    assert len(world.calls(purpose="checkin")) == 2 and await world.incidents() == []
    await world.advance(minutes=20)  # 09:40 try 3: the ladder starts
    assert len(world.calls(purpose="checkin")) == 3  # 3 tries, never more
    (inc,) = await world.incidents()
    assert inc.data["scenario"] == "checkin_unanswered" and inc.data["tier"] == "high"
    first = world.child_texts()[n_child:]
    assert len(first) == 1 and "did not pick up" in first[0] and world.child_buttons()  # step 1: WhatsApp to the child (with buttons) at once
    assert world.calls(role="child") == []

    await world.advance(minutes=5)  # 09:45 step 2: ring the child
    assert [c.purpose for c in world.calls(role="child")] == ["escalation_child"]
    assert sent_to_second == []
    await world.advance(minutes=5)  # 09:50 step 3: WhatsApp the second contact (named in advance)
    assert len(sent_to_second) == 1 and world.calls(role="second_contact") == []

    # the parent speaks (before the last step): the ladder closes and the child is told
    reply = await world.parent_says("main theek hoon", via="text")
    assert reply is not None and reply.action == "fine"
    (inc,) = await world.incidents()
    assert inc.status == "closed" and inc.data["closed_by"] == "parent_fine"
    assert line("alert.parent_fine", rel="x") in world.child_texts()
    await world.advance(minutes=30)  # step 4 (ring the second contact) must NOT happen
    assert world.calls(role="second_contact") == [] and len(world.calls(role="child")) == 1
    assert len(world.calls(purpose="checkin")) == 3


async def test_ladder_runs_to_the_end_with_caps_when_nobody_answers(world):
    async def second_sender(member, text):
        return None

    world.hub.ctx.extra_senders["second"] = second_sender
    world.script_calls(CallResult.ANSWERED)
    await world.setup_family(second=SECOND)
    world.script_calls(CallResult.NO_ANSWER)
    await world.advance(hours=1)
    await world.advance(minutes=20)
    await world.advance(minutes=20)
    for _ in range(6):
        await world.advance(minutes=5)
    await world.advance(hours=3)
    (inc,) = await world.incidents()
    assert inc.status == "exhausted"
    assert [s["action"] for s in inc.data["steps"]] == ["wa_child", "call_child", "wa_second", "call_second"] and all(s["state"] == "done" for s in inc.data["steps"])
    assert len(world.calls(role="child")) == 1 and len(world.calls(role="second_contact")) == 1
    # caps: at most 3 calls per incident per person, at most 3 escalation calls per person per day
    for who in ("child", "second_contact"):
        assert len(world.calls(role=who)) <= 3
    # nothing more rings for the rest of that day
    n = len(world.caller.calls)
    await world.advance(hours=6)
    assert len(world.caller.calls) == n


async def test_second_contact_whatsapp_is_wired_in_production(world):
    assert "second" in world.hub.ctx.extra_senders


# ---------------------------------------------------------------------------- 5. the child deletes everything
async def test_child_deletes_everything_and_the_phone_is_locked_out(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    await w.consent_device()
    parent = await w.parent()
    await w.device.pair(parent.id)
    assert (await w.device.heartbeat(w)).status_code == 200

    out = await w.child_says("delete everything for my parent")
    assert out == [line("cmd.delete_ask")]
    out = await w.child_says("DELETE")
    assert out == [line("cmd.delete_done")]
    assert await w.hub.family((await w.child.user_row()).id) is None
    assert (await w.device.heartbeat(w)).status_code == 404  # the phone token no longer works (the API answers a plain 404 for any bad token, by design)
    assert (await w.device.sos()).status_code == 404
    n = len(w.caller.calls)
    await w.advance(days=1)
    assert len(w.caller.calls) == n  # nothing rings for a family that no longer exists
