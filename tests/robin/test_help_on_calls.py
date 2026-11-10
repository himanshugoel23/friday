# ruff: noqa: E501
"""Safety gap from T11: a help word on ANY call to the parent (alert nudge, intro, medicine...) raises the EMERGENCY SOS alert, not only on the check-in call;
and "I have told {child}" is spoken only if that alert was accepted, else the honest line. FAKES only (FakeParentCaller): no phone, no network."""

from __future__ import annotations

from friday.robin.alerts import AlertResult, RobinAlert
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, ConsentSource, Step, Tier
from tests.robin.test_alerts_sos import ready


def answered(line: str, text: str) -> CallOutcome:
    return CallOutcome(result=CallResult.ANSWERED, answers=[AnswerRaw(line=line, text=text)])


async def sos_incidents(w, fam):
    return [r for r in await w.store.list(fam.id, "incident") if r.data.get("scenario") == "sos"]


async def test_help_word_on_an_alert_nudge_call_raises_the_sos_and_says_i_have_told(w):
    fam, parent = await ready(w)
    w.caller.script(answered("nudge.generic", "madad, main gir gayi hoon"))
    res = await w.hub.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.HIGH, scenario="S1", why="unknown caller 22 minutes", dedupe_key="a"))
    assert res.accepted
    nudge = next(c for c in w.caller.calls if c.purpose == "nudge")
    assert nudge.help_line == "sos.parent"  # the alert was accepted, so the parent hears that the child was told
    (inc,) = await sos_incidents(w, fam)
    assert inc.data["tier"] == "emergency" and inc.data["scenario"] == "sos" and "parent_said_help" in inc.data["signals"]
    assert any("SOS" in t or "help" in t.lower() for t in w.sender.texts())  # the child was told by chat too


async def test_help_word_on_the_intro_call_raises_the_sos(w):
    fam, parent = await w.family(notified=False)
    w.caller.script(answered("intro.greet", "bachaooo"))
    await w.hub.intro.start(fam)
    (inc,) = await sos_incidents(w, fam)
    assert inc.data["tier"] == "emergency"
    assert next(c for c in w.caller.calls if c.purpose == "intro").help_line == "sos.parent"


async def test_fall_phrase_on_a_medicine_call_raises_the_sos(w):
    fam, parent = await ready(w)
    await w.hub.fam.give_consent(parent.id, "medicine_reminders", ConsentSource.ADMIN_CHAT)
    w.caller.script(answered("x", "seene mein bahut dard ho raha hai"))
    await w.ctx.call(fam, parent, "medicine", [Step(line="nudge.generic", slots=await w.ctx.slots(fam), expect="yesno")], dedupe_key="m2")
    assert len(await sos_incidents(w, fam)) == 1


async def test_when_the_sos_is_not_accepted_the_call_never_says_the_child_was_told(w):
    fam, parent = await ready(w)

    async def refuse(family, member, purpose, said):  # noqa: ANN001, ARG001
        return False

    w.ctx.help_handler = refuse
    w.caller.script(answered("nudge.generic", "madad"))
    await w.hub.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.HIGH, scenario="S1", why="unknown caller 22 minutes", dedupe_key="b"))
    assert next(c for c in w.caller.calls if c.purpose == "nudge").help_line == "widget.sos_failed"


async def test_no_help_word_no_sos(w):
    fam, parent = await ready(w)
    w.caller.script(answered("nudge.generic", "paani gir gaya, haan main theek hoon"))
    await w.hub.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.HIGH, scenario="S1", why="unknown caller 22 minutes", dedupe_key="c"))
    assert await sos_incidents(w, fam) == []


async def test_sos_trigger_by_call_tells_the_truth_when_nobody_could_be_told(w):
    fam, parent = await w.family(notified=False)

    async def failing(alert):  # noqa: ANN001, ARG001
        return AlertResult(False, "error")

    w.hub.alerts.raise_alert = failing  # type: ignore[method-assign]
    res = await w.hub.sos.trigger(parent.id, "call")
    assert not res.alert.accepted and res.parent_lines == ["widget.sos_failed"]
    assert [s.line for s in await w.hub.sos.call_steps(parent.id, accepted=False)] == ["widget.sos_failed"]


async def test_parent_said_fall_and_chest_phrases_reach_the_sos_on_text_and_widget(w):
    fam, parent = await ready(w)
    reply = await w.hub.parent_said("+919800000102", "main gir gayi hoon, uth nahi pa rahi", "text")
    assert reply and reply.action == "sos"
    w.go(minutes=10)
    reply2 = await w.hub.widget_voice(parent.id, "seene mein bahut dard ho raha hai")
    assert reply2 and reply2.action == "sos"
    w.go(minutes=10)
    quiet = await w.hub.parent_said("+919800000102", "paani gir gaya", "text")
    assert quiet is None or quiet.action != "sos"
