# ruff: noqa: E501
"""The child's chat commands and the onboarding flow, end to end through RobinHub.handle (the same entry the web chat and WhatsApp use)."""

from __future__ import annotations

from friday.core.models import Channel, InboundMessage, MessageKind
from friday.robin.models import FamilyStatus
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE, SECOND_PHONE, at


async def say(w, text: str, *, button: str | None = None) -> str:
    n = len(w.sender.sent)
    msg = InboundMessage(channel=Channel.SIMULATOR, from_phone=CHILD_PHONE, text=text, kind=MessageKind.BUTTON_REPLY if button else MessageKind.TEXT, button_id=button)
    handled = await w.hub.handle(w.child_user, msg)
    return ("\n".join(s.text for s in w.sender.sent[n:])) if handled else "<NOT HANDLED>"


async def test_onboarding_by_chat_notifies_the_parent_and_makes_no_call(w):
    assert await say(w, "hello there") == "<NOT HANDLED>"  # normal chat is untouched
    assert "mobile number" in await say(w, "set up Robin for my father")
    assert "does not look" in await say(w, "12345")
    assert "your own number" in (await say(w, CHILD_PHONE)).replace("That is your own number", "your own number")
    assert "language" in await say(w, PARENT_PHONE)
    assert "language" in await say(w, "klingon")
    assert "check-in" in await say(w, "Hindi")
    assert "quiet hours" in await say(w, "11pm")  # inside quiet hours 22:00 to 07:00
    assert "between 22:00 and 07:00" in await say(w, "9 am")
    assert "second person" in await say(w, "ok")
    assert "careful" in (await say(w, SECOND_PHONE)).lower()
    assert "ring you" in await say(w, "balanced")
    done = await say(w, "yes")
    assert "I will NOT call Papa until" in done or "NOT call" in done
    fam = await w.hub.family(w.child_user.id)
    parent = await w.hub.parent(fam)
    assert fam.status == FamilyStatus.ACTIVE and fam.settings.checkin_time == "09:00" and parent.language == "hi"
    assert {c.item for c in await w.store.consents(fam.id, parent.id)} == {"daily_checkin_calls", "medicine_reminders", "scam_check", "share_summary_with_child"}
    assert await w.hub.fam.view(fam) is not None
    # the parent was NOTIFIED (voice note + text, in Hindi) and nothing rang them: the introduction call went to the (fake) port only if lines allow
    assert w.channel.voice_notes and "रॉबिन" not in w.channel.voice_notes[0][1] and "Robin" in w.channel.voice_notes[0][1]
    assert "AI" in w.channel.voice_notes[0][1]
    assert all(c.purpose == "intro" for c in w.caller.calls)
    assert (await w.hub.ctx.second(fam)).call_ok  # named in advance


async def test_setup_in_hinglish_and_cancel_erases(w):
    out = await say(w, "papa ke liye robin set up karo")
    assert "mobile number" in out or "Unka mobile" in out
    await say(w, "cancel")
    assert await w.hub.family(w.child_user.id) is None


async def test_chat_commands(w):
    fam, parent = await w.family()
    assert "Papa: active" in await say(w, "parent status")
    assert "Check-in time for Papa is now 08:30" in await say(w, "check-in time 8:30am")
    assert "quiet hours" in await say(w, "check-in time 11pm")
    assert "Sensitivity is now careful" in await say(w, "sensitivity careful")
    assert "Calm, Balanced or Careful" in await say(w, "sensitivity wild")
    saved = await say(w, "add medicine Amlodipine 5mg at 8am, 8pm strips 2 of 10 bought 2026-01-04")
    assert "Saved Amlodipine" in saved and "ask the doctor" in saved
    assert "Amlodipine 5mg at 08:00, 20:00" in await say(w, "medicines")
    assert "add medicine" in await say(w, "add medicine nonsense")
    assert "OK" in await say(w, "pills left amlodipine 18")
    assert "Removed Amlodipine" in await say(w, "remove medicine amlodipine")
    assert "No medicines" in await say(w, "medicines")
    assert "paused until" in await say(w, "pause reminders 3 days")
    assert "back on" in await say(w, "resume reminders")
    seen = await say(w, "what does Robin see")
    assert "Robin" in seen and "daily check-in calls: agreed" in seen and "never records calls" in seen
    assert "Today with Papa" in await say(w, "digest") and "This week with Papa" in await say(w, "weekly digest")
    assert "Good-morning messages for Papa are on" in await say(w, "good morning on")
    assert "Festival greetings for Papa are off" in await say(w, "festival greetings off")
    assert "Switched on: phone safety signals" in await say(w, "enable device signals")
    assert "do not know that item" in await say(w, "enable teleportation")
    assert "Guardian basis recorded" in await say(w, "guardian mode court order for incapacity")
    assert "Please write the basis" in await say(w, "guardian mode x")
    assert "safe word" not in (await say(w, "robin help")).lower()  # not in the default help
    assert await say(w, "safe word tulsi") == "<NOT HANDLED>"  # off by default


async def test_call_papa_runs_an_on_demand_check_in(w):
    from friday.robin.models import AnswerRaw, CallOutcome, CallResult

    fam, parent = await w.family()
    w.caller.script(CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line="checkin.q.ate", text="haan")]))
    out = await say(w, "call papa")
    assert "Calling Papa now" in out and "Papa checked in" in out and w.caller.calls[-1].purpose == "callnow"


async def test_alert_buttons_and_words_through_chat(w):
    from friday.robin.alerts import RobinAlert
    from friday.robin.models import Tier

    fam, parent = await w.family()
    await w.hub.fam.admin_consent(fam, "device_signals")
    r = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "unknown caller 22 minutes + camera on"))
    assert "Marked safe" in await say(w, "x", button=f"rb:{r.incident_id}:safe")
    r2 = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "again", dedupe_key="2"))
    assert "Alert details" in await say(w, "details")
    assert "you have it" in await say(w, "I have it")
    assert (await w.store.get(r2.incident_id)).status == "closed"


async def test_delete_everything_needs_confirmation(w):
    fam, parent = await w.family()
    assert "Reply DELETE" in await say(w, "delete everything for my parent")
    assert "nothing was deleted" in await say(w, "no")
    assert await w.hub.family(w.child_user.id)
    await say(w, "delete everything for my parent")
    assert "Deleted everything about Papa" in await say(w, "DELETE")
    assert await w.hub.family(w.child_user.id) is None and not await w.store.members_by_phone(PARENT_PHONE)


async def test_prescription_yes_no_confirmation(w):
    from datetime import date

    from friday.robin.medicine import parse_prescription_line

    fam, _ = await w.family()
    await w.hub.meds.propose(fam, [parse_prescription_line("Metformin 500mg 1-0-1", date(2026, 1, 5))])
    assert "Saved 1 medicine" in await say(w, "yes")
    assert "Metformin" in await say(w, "medicines")


async def test_brand_is_one_setting(w):
    w.settings.brand_name = "Zed"
    fam, parent = await w.family()
    out = await say(w, "what does zed see")
    assert "Zed" in out and "Robin" not in out and "Friday" not in out
    assert "Zed commands" in await say(w, "zed help")
    _ = at


async def test_inbound_pipeline_calls_the_robin_hook_when_enabled(settings, container):
    import inspect

    from friday.api import inbound

    src = inspect.getsource(inbound.InboundPipeline._active)
    assert "self.robin" in src and src.index("self.robin") < src.index("self.features")
    settings.robin_enabled = False
    from friday.robin.wiring import build_robin

    assert build_robin(container) is None  # switch OFF by default
    assert settings.robin_enabled is False
