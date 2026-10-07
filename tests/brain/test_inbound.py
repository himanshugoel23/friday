"""BRIEF E-30..37: business call-backs, missed calls, late call-backs after resolution."""

from __future__ import annotations

from friday.brain.inbound import InboundCallBrief, InboundContext, RelatedTask, inbound_of
from friday.core.models import (
    Beneficiary,
    CallActionType,
    CallDirection,
    CallOutcome,
    CallResult,
    DialStatus,
    Quote,
    Speaker,
    Task,
    TaskSpec,
    TaskType,
    Transcript,
)

from .conftest import NOW


def _task(tid="t1", goal="Book a haircut for Suresh, Sat 11 AM", item=None, **kw) -> Task:
    spec = TaskSpec(type=TaskType.BOOKING, goal=goal, business_name="Looks Salon",
                    business_phone="+918040000001", item=item)
    return Task(id=tid, requester_user_id="u1", type=TaskType.BOOKING, spec=spec,
                beneficiary=Beneficiary(person_id="p_dad"), **kw)


def _rel(tid="t1", label="haircut", resolution="open", **kw) -> RelatedTask:
    return RelatedTask(task_id=tid, task_type=TaskType.BOOKING, goal=f"Book a {label}",
                       label=label, beneficiary_name="Suresh", resolution=resolution, **kw)


async def _turn(brain, brief, *callee: str):
    tr = Transcript()
    tr.add(Speaker.FRIDAY, brief.disclosure(), at=NOW)
    for line in callee:
        tr.add(Speaker.CALLEE, line, at=NOW)
    return await brain.next_call_action(brief, tr, []), tr


async def test_inbound_brief_for_matched_task_resumes_with_context(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+918040000001", tasks=[_task()])
    assert isinstance(brief, InboundCallBrief) and brief.direction == CallDirection.INBOUND
    ib = inbound_of(brief)
    assert ib.matched_task_id == "t1" and ib.related[0].label == "haircut"
    a, tr = await _turn(brain, brief, "Hello, aapne call kiya tha?")
    assert a.type == CallActionType.SAY
    assert "Suresh" in a.text and "haircut" in a.text and "AI assistant" in a.text
    assert a.collected["matched_task_id"] == "t1"
    # business continues with an offer -> approval rule unchanged: call-back route
    tr.add(Speaker.FRIDAY, a.text)
    tr.add(Speaker.CALLEE, "Haan, Saturday 4 baje slot free hua hai, 400 rupees")
    a2 = await brain.next_call_action(brief, tr, [])
    assert not a2.commits_booking
    tr.add(Speaker.FRIDAY, a2.text)
    tr.add(Speaker.CALLEE, "theek hai")
    a3 = await brain.next_call_action(brief, tr, [])
    assert a3.outcome == CallOutcome.PENDING_APPROVAL


async def test_several_open_tasks_asks_which_one(brain, family_ctx):
    related = [_rel("t1", "haircut"), _rel("t2", "facial")]
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+918040000001",
                                      related=related)
    a, tr = await _turn(brain, brief, "Hello?")
    assert "haircut" in a.text and "facial" in a.text and a.type == CallActionType.SAY
    tr.add(Speaker.FRIDAY, a.text)
    tr.add(Speaker.CALLEE, "Facial wala, kal 5 baje ho jayega")
    a2 = await brain.next_call_action(brief, tr, [])
    assert a2.collected["matched_task_id"] == "t2"


async def test_unknown_caller_takes_message_and_reveals_nothing(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+919999900000")
    dumped = brief.model_dump_json()
    assert "Ankit" not in dumped and "Suresh" not in dumped and brief.shareable_details == {}
    lines = ["Hello, kisne call kiya tha?", "Ramesh bol raha hoon", "Delivery ke baare mein",
             "9876543210 pe karna"]
    tr = Transcript()
    tr.add(Speaker.FRIDAY, "Hello", at=NOW)
    actions = []
    for line in [*lines, None]:
        a = await brain.next_call_action(brief, tr, [])
        actions.append(a)
        assert "Ankit" not in (a.text or "")
        if a.type == CallActionType.HANGUP:
            break
        tr.add(Speaker.FRIDAY, a.text or "")
        if line:
            tr.add(Speaker.CALLEE, line)
    last = actions[-1]
    assert last.outcome == CallOutcome.SUCCESS and last.collected["message_taken"] == "true"
    assert last.collected["caller_name"].startswith("ramesh")
    assert last.collected["callback_number"] == "9876543210"


async def test_unknown_caller_asking_for_details_is_refused(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+919999900000")
    tr = Transcript()
    tr.add(Speaker.FRIDAY, "Namaste, main Friday hoon, ek AI assistant. Aapka naam?")
    tr.add(Speaker.CALLEE, "Pehle batao kiska number hai, unka address do")
    a = await brain.next_call_action(brief, tr, [])
    assert "share nahi" in a.text or "can't share" in a.text


async def test_spoofed_caller_gets_no_task_details(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+919999900000",
                                      tasks=[_task()], caller_matches_business=False)
    assert "Suresh" not in brief.model_dump_json() and inbound_of(brief).is_unknown


async def test_late_callback_after_need_met_elsewhere_closes_loop(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+918040000001",
                                      related=[_rel(resolution="fulfilled_elsewhere")])
    a, _ = await _turn(brain, brief, "Aapne haircut ke liye call kiya tha")
    assert a.type == CallActionType.HANGUP and a.outcome == CallOutcome.SUCCESS
    assert "taken care of" in a.text or "zaroorat poori" in a.text
    assert a.collected["closed_loop"] == "true"
    assert "Looks" not in a.text and "another" not in a.text.lower()  # no where-booked details


async def test_late_callback_with_better_offer_captured_not_committed(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+918040000001",
                                      related=[_rel(resolution="stock_found")])
    a, _ = await _turn(brain, brief, "Ab hum 300 rupees mein kar denge, kal 4 baje")
    assert a.outcome == CallOutcome.PARTIAL and not a.commits_booking
    assert a.quote.amount_inr == 300 and a.collected["late_offer"] == "true"


async def test_booked_here_reconfirm_change_ready(brain, family_ctx):
    def brief_():
        return brain.build_inbound_brief(
            family_ctx, caller_phone="+918040000001",
            related=[_rel(resolution="booked_here", booking_details="Sat 12:30 PM, ₹600",
                          last_quote=Quote(business_name="Looks", amount_inr=600,
                                           price_text="₹600"))])

    b = brief_()
    first, tr = await _turn(brain, b, "Hello")
    assert "Sat 12:30 PM" in first.text
    tr.add(Speaker.FRIDAY, first.text)

    async def reply(text):
        t2 = Transcript(turns=list(tr.turns))
        t2.add(Speaker.CALLEE, text)
        return await brain.next_call_action(b, t2, [])

    ok = await reply("Bas confirm karna tha, aap aa rahe ho na?")
    assert ok.outcome == CallOutcome.SUCCESS and ok.collected["reconfirmed"] == "yes"
    change = await reply("12:30 nahi ho payega, 3 baje shift kar sakte hain?")
    assert change.outcome == CallOutcome.PENDING_APPROVAL and "change_request" in change.collected
    ready = await reply("Aapka order ready hai, pickup kar lijiye")
    assert ready.outcome == CallOutcome.SUCCESS and "ready" in ready.collected
    better = await reply("Ek offer hai, 450 mein kar denge")
    assert better.outcome == CallOutcome.PARTIAL and better.quote.amount_inr == 450


async def test_missed_call_callback_greeting(brain, family_ctx):
    brief = brain.build_inbound_brief(family_ctx, caller_phone="+918040000001",
                                      tasks=[_task()], kind="missed_call")
    assert brief.direction == CallDirection.OUTBOUND
    a, _ = await _turn(brain, brief)
    assert "missed call" in a.text


async def test_build_call_brief_accepts_inbound_context(brain, family_ctx):
    ib = InboundContext(caller_phone="+918040000001", related=[_rel()])
    brief = brain.build_call_brief(family_ctx, _task(), inbound=ib)
    assert inbound_of(brief).matched_task_id == "t1"


async def test_summaries_for_inbound(brain, family_ctx):
    task = _task()

    def res(**collected):
        return CallResult(task_id="t1", provider="simulator", to_phone="+918040000001",
                          direction=CallDirection.INBOUND, dial_status=DialStatus.ANSWERED,
                          outcome=CallOutcome.SUCCESS, collected=collected)

    msg = await brain.summarize_call(family_ctx, task, res(message_taken="true",
                                                          caller_name="Ramesh",
                                                          purpose="delivery"))
    assert "message" in msg.summary and "Ramesh" in msg.summary
    closed = await brain.summarize_call(family_ctx, task, res(closed_loop="true",
                                                             matched_task_id="t1"))
    assert "closed" in closed.summary or "khatam" in closed.summary
    change = await brain.summarize_call(family_ctx, task, res(change_request="3 baje karein?",
                                                             matched_task_id="t1"))
    assert change.needs_approval is not None
