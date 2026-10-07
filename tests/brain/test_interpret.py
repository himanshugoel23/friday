"""AI-3: interpret() - table-driven EN / HI / Hinglish cases on the fake path."""

from __future__ import annotations

import pytest

from friday.core.models import (
    CareRequestKind,
    FactKind,
    Intent,
    InteractionKind,
    LocationPin,
    MessageKind,
    MidCallQuestion,
    QuestionPurpose,
    Recurrence,
    Task,
    TaskResult,
    TaskSpec,
    TaskStatus,
    TaskType,
)

from .conftest import make_ctx, msg

# (text, intent, task type or None)
CASES: list[tuple[str, Intent, TaskType | None]] = [
    ("Book a haircut at Looks Salon tomorrow 6pm, 080 4123 4567", Intent.NEW_TASK,
     TaskType.BOOKING),
    ("Looks salon indiranagar mein sat ko haircut book kar do", Intent.NEW_TASK, TaskType.BOOKING),
    ("Reserve a table for 4 at Spice Route Restaurant tonight 8pm", Intent.NEW_TASK,
     TaskType.BOOKING),
    ("Dr. Sharma ke saath papa ka appointment kal subah", Intent.NEW_TASK, TaskType.HEALTHCARE),
    ("lab home collection for mom's thyroid test tomorrow 7 am", Intent.NEW_TASK,
     TaskType.HEALTHCARE),
    ("Is Apollo Pharmacy Koramangala open and do they have Dolo 650?", Intent.NEW_TASK,
     TaskType.ENQUIRY),
    ("CoolCare se poocho split ac service kitne ka hai", Intent.NEW_TASK, TaskType.ENQUIRY),
    ("Move my salon booking to Sunday", Intent.NEW_TASK, TaskType.RESCHEDULE),
    ("cancel my Dr. Mehta appointment", Intent.NEW_TASK, TaskType.CANCEL_BOOKING),
    ("Is my 7pm table at Toit still on?", Intent.NEW_TASK, TaskType.RECONFIRM),
    ("tell the clinic I'm running late by 20 minutes", Intent.NEW_TASK, TaskType.RUNNING_LATE),
    ("Order Dolo 650 x2 from Wellness Pharmacy to dad's home", Intent.NEW_TASK, TaskType.ORDER),
    ("2 water cans mangwa do", Intent.NEW_TASK, TaskType.ORDER),
    ("Dad ke ghar ke paas kis chemist ke paas Lantus insulin pen hai?", Intent.NEW_TASK,
     TaskType.STOCK_HUNT),
    ("Plumber was supposed to come at 11, chase him", Intent.NEW_TASK,
     TaskType.SERVICE_COORDINATION),
    ("is my phone repair done at Mobile Care?", Intent.NEW_TASK, TaskType.STATUS_CHASE),
    ("The dry cleaner ruined my shirt, complain to them", Intent.NEW_TASK, TaskType.COMPLAINT),
    ("2BHK in HSR under 35k, bachelors OK", Intent.NEW_TASK, TaskType.RENTAL_HUNT),
    ("Get 4 quotes for packers and movers Bengaluru to Pune on 1 Nov", Intent.NEW_TASK,
     TaskType.QUOTE),
    ("Weekly physio for Dad every Tue and Fri 10 am", Intent.NEW_TASK,
     TaskType.RECURRING_BOOKING),
    ("Call mom every morning at 10 to check in on her", Intent.NEW_TASK,
     TaskType.WELLBEING_CHECKIN),
    ("Airtel broadband 2 se 6 Oct tak band tha, refund dilwao", Intent.NEW_TASK,
     TaskType.CUSTOMER_CARE),
    ("raise a complaint with Jio, my internet is not working", Intent.NEW_TASK,
     TaskType.CUSTOMER_CARE),
    ("Homestay in Udaipur 14 to 16 Nov for 2 adults, under 4k/night", Intent.NEW_TASK,
     TaskType.HOTEL_BOOKING),
    ("Find me a good AC repair guy near Indiranagar, under ₹800", Intent.NEW_TASK,
     TaskType.DISCOVERY),
    ("mummy ke ghar ke paas koi achha physiotherapist dekho", Intent.NEW_TASK,
     TaskType.DISCOVERY),
    ("my rent is due on 5th", Intent.REMEMBER, None),
    ("btw mera car insurance march mein expire hota hai", Intent.REMEMBER, None),
    ("I'm vegetarian", Intent.REMEMBER, None),
    ("add my dad Ramesh, +91 98290 12345, lives in Jaipur", Intent.ADD_PERSON, None),
    ("save my office address as Embassy Tech Village, Bellandur", Intent.ADD_PLACE, None),
    ("be formal", Intent.SETTINGS, None),
    ("hindi mein baat karo", Intent.SETTINGS, None),
    ("turn on morning briefing at 7", Intent.SETTINGS, None),
    ("status?", Intent.STATUS, None),
    ("delete everything", Intent.DELETE_DATA, None),
    ("mera sab data delete kar do", Intent.DELETE_DATA, None),
    ("give me my invite codes", Intent.INVITE, None),
    ("my Airtel account number is 1-2345678", Intent.SAVE_IDENTIFIER, None),
    ("the plumber was great, 5 stars", Intent.RATE_VENDOR, None),
    ("help", Intent.HELP, None),
    ("thanks!", Intent.SMALL_TALK, None),
    ("what do you know about me?", Intent.QUERY_MEMORY, None),
    ("नमस्ते", Intent.SMALL_TALK, None),
]


@pytest.mark.parametrize(("text", "intent", "task_type"), CASES)
async def test_interpret_table(brain, family_ctx, text, intent, task_type):
    out = await brain.interpret(family_ctx, msg(text))
    assert out.intent == intent, out
    if task_type is not None:
        assert out.task_spec is not None and out.task_spec.type == task_type
    assert out.reply


def test_table_size():
    assert len(CASES) >= 40


async def test_booking_spec_details(brain, ctx):
    out = await brain.interpret(ctx, msg("Looks salon indiranagar mein sat ko haircut book kar "
                                         "do, 080 4123 4567, subah 11 ke aaspaas"))
    s = out.task_spec
    assert s.business_name == "Looks salon" and s.business_phone == "+918041234567"
    assert s.window_start is not None and s.when_text.startswith("Sat 10 Oct")
    assert not s.delegation.granted  # no explicit hand-over
    assert s.missing == []
    assert "confirm" in out.reply.lower()


async def test_explicit_delegation_extracted_with_limits(brain, ctx):
    text = ("Book Dr. Mehta for a cleaning, any slot Thu or Fri between 5 and 7 pm, under "
            "₹1,000. You decide. 080 2345 6789")
    out = await brain.interpret(ctx, msg(text))
    d = out.task_spec.delegation
    assert d.granted and d.max_price_inr == 1000 and d.user_words == text
    assert d.window_start and d.window_end and "5 PM" in d.time_window_text
    assert "without checking back" in out.reply or "bina poochhe" in out.reply


async def test_budget_alone_is_not_delegation(brain, ctx):
    out = await brain.interpret(ctx, msg("Book AC service at CoolCare tomorrow, budget max 600"))
    assert out.task_spec.budget.max_inr == 600
    assert not out.task_spec.delegation.granted


async def test_llm_claimed_delegation_without_user_words_is_dropped(brain, fake_llm, ctx):
    fake_llm.script("interpret", {
        "intent": "new_task", "reply": "ok",
        "task": {"type": "booking", "goal": "Book haircut", "business_phone": "080 4123 4567",
                 "when_text": "tomorrow", "delegation": {"granted": True, "max_price_inr": 900,
                                                         "user_words": "book whatever"}}})
    out = await brain.interpret(ctx, msg("book a haircut at Looks tomorrow under 900"))
    assert not out.task_spec.delegation.granted


async def test_missing_fields_instead_of_guessing(brain, ctx):
    out = await brain.interpret(ctx, msg("book a haircut at Looks Salon"))
    assert "when_text" in out.task_spec.missing
    assert out.task_spec.business_phone is None
    order = await brain.interpret(ctx, msg("order from Wellness Pharmacy"))
    assert "item" in order.task_spec.missing


async def test_customer_care_spec(brain, ctx):
    out = await brain.interpret(ctx, msg("Airtel broadband band hai 3 din se, refund dilwao"))
    s = out.task_spec
    assert s.company == "Airtel" and s.care_request == CareRequestKind.REFUND
    assert s.window_start is None


async def test_recurring_rule(brain, family_ctx):
    out = await brain.interpret(family_ctx, msg("Weekly physio for Dad every Tue and Fri 10 am"))
    r = out.task_spec.recurrence
    assert r.freq == Recurrence.WEEKLY and r.weekdays == [1, 4] and r.time_ist == "10:00"
    assert out.resolution.person_id == "p_dad"


async def test_stay_request(brain, family_ctx):
    out = await brain.interpret(family_ctx, msg("Mom-Dad ke liye Udaipur mein ek achha homestay, "
                                                "14 se 16 Nov. 4k/night tak"))
    st = out.task_spec.stay
    assert st.destination == "Udaipur" and st.nights == 2 and st.max_rate_per_night_inr == 4000


async def test_answer_pending_question_free_text(brain):
    q = MidCallQuestion(id="q1", task_id="t1", text="4pm or 6pm?", options=["4pm", "6pm",
                                                                           "None of these"],
                        purpose=QuestionPurpose.APPROVE_BOOKING)
    ctx = make_ctx(pending_question=q)
    out = await brain.interpret(ctx, msg("6 wala"))
    assert out.intent == Intent.ANSWER_QUESTION
    assert out.answer.option_index == 1 and out.answer.approves and out.answer.question_id == "q1"
    none = await brain.interpret(ctx, msg("neither"))
    assert none.answer.option_index == 2 and not none.answer.approves


async def test_answer_pending_question_button(brain):
    q = MidCallQuestion(id="q9", task_id="t1", text="Which?", options=["Sat 11am", "Sun 10am"],
                        purpose=QuestionPurpose.CHOOSE_OPTION)
    ctx = make_ctx(pending_question=q)
    out = await brain.interpret(ctx, msg("Sun 10am", kind=MessageKind.BUTTON_REPLY,
                                         button_id="q:q9:1"))
    assert out.intent == Intent.ANSWER_QUESTION and out.answer.text == "Sun 10am"
    assert not out.answer.approves  # CHOOSE_OPTION is not an approval


def _awaiting_task() -> Task:
    q = MidCallQuestion(id="qa", task_id="t7", text="Looks: 10:00 or 12:30?",
                        purpose=QuestionPurpose.APPROVE_BOOKING,
                        options=["10:00 AM, ₹600", "12:30 PM, ₹600", "None of these"])
    return Task(id="t7", requester_user_id="u1", type=TaskType.BOOKING,
                status=TaskStatus.AWAITING_APPROVAL,
                spec=TaskSpec(type=TaskType.BOOKING, goal="Book haircut at Looks"),
                result=TaskResult(success=False, summary="options", needs_approval=q))


async def test_approval_flow_text_and_buttons(brain):
    ctx = make_ctx(open_tasks=[_awaiting_task()])
    pick = await brain.interpret(ctx, msg("12:30 wala"))
    assert pick.intent == Intent.APPROVE and pick.task_id == "t7" and pick.choice_index == 1
    assert pick.answer.approves and pick.answer.question_id == "qa"
    no = await brain.interpret(ctx, msg("none of these"))
    assert no.intent == Intent.REJECT
    yes = await brain.interpret(ctx, msg(button_id="a:t7:yes", kind=MessageKind.BUTTON_REPLY))
    assert yes.intent == Intent.APPROVE and yes.task_id == "t7"
    relay = await brain.interpret(ctx, msg("ask for Sunday instead"))
    assert relay.intent == Intent.TASK_UPDATE and relay.task_id == "t7"


async def test_choose_from_comparison_button(brain):
    out = await brain.interpret(make_ctx(), msg(button_id="c:parent1:2",
                                                kind=MessageKind.BUTTON_REPLY))
    assert out.intent == Intent.CHOOSE and out.choice_index == 2


async def test_refuses_to_save_secrets(brain, ctx):
    for text in ("my OTP is 482913, save it", "save my ATM PIN 4821", "card cvv is 123"):
        out = await brain.interpret(ctx, msg(text))
        assert out.intent == Intent.SAVE_IDENTIFIER and out.identifier_upsert is None, text
        assert "OTP" in out.reply


async def test_save_identifier_value(brain, ctx):
    out = await brain.interpret(ctx, msg("my Airtel account number is 1-2345678"))
    assert out.identifier_upsert.value == "1-2345678"
    assert out.identifier_upsert.company == "Airtel"


async def test_delete_requires_pin(brain, ctx):
    out = await brain.interpret(ctx, msg("delete my data"))
    assert out.requires_pin


async def test_autonomy_level_4_requires_pin(brain, ctx):
    out = await brain.interpret(ctx, msg("you can book automatically, no need to ask before "
                                         "calling"))
    assert out.intent == Intent.SETTINGS and out.requires_pin
    assert out.autonomy_updates[0].level == 4


async def test_remember_date_fact(brain, ctx):
    out = await brain.interpret(ctx, msg("my rent is due on 5th"))
    f = out.facts[0]
    assert f.kind == FactKind.DATE and f.recurrence == Recurrence.MONTHLY
    assert f.due_on.day == 5 and f.due_on.month == 11  # 5 Oct already passed on 7 Oct


async def test_add_person_and_place(brain, ctx):
    out = await brain.interpret(ctx, msg("add my mom Sunita, +91 98290 12345, she only speaks "
                                         "Marathi, lives in Pune"))
    p = out.person_upsert
    assert p.name == "Sunita" and p.relation == "mother" and p.phone == "+919829012345"
    assert p.language.value == "mr" and out.place_upsert.person_id == p.id


async def test_location_pin_after_address_question(brain, family_ctx):
    from friday.core.models import ConversationTurn, Direction

    ctx = family_ctx.model_copy(update={"recent": [ConversationTurn(
        direction=Direction.OUTBOUND, text="Added Mom: Sunita. What's her address? Share a "
                                           "location pin.")]})
    out = await brain.interpret(ctx, msg(kind=MessageKind.LOCATION, location=LocationPin(
        lat=18.5, lng=73.8, address="Kothrud, Pune")))
    assert out.intent == Intent.ADD_PLACE and out.place_upsert.location.lat == 18.5
    assert out.place_upsert.person_id == "p_mom" and not out.place_upsert.ephemeral


async def test_rate_vendor_links_known_business(brain):
    from friday.core.models import Business

    ctx = make_ctx(known_businesses=[Business(id="b1", name="Raju Plumbing Works",
                                              phone="+918040000012", category="plumber")])
    out = await brain.interpret(ctx, msg("Raju Plumbing didn't come, total no-show"))
    assert out.intent == Intent.RATE_VENDOR
    assert out.vendor_interactions[0].kind == InteractionKind.NO_SHOW
    assert out.vendor_interactions[0].business_id == "b1"


async def test_settings_language_and_tone(brain, ctx):
    out = await brain.interpret(ctx, msg("hindi mein baat karo"))
    assert out.profile_updates == {"language": "hi"} or out.profile_updates["language"] == "hi"
    out = await brain.interpret(ctx, msg("be playful"))
    assert out.profile_updates["tone"] == "playful"


async def test_voice_note_transcript(brain, ctx):
    out = await brain.interpret(ctx, msg("haan toh kal shaam 6 baje looks salon mein haircut "
                                         "book kar dena", kind=MessageKind.VOICE_NOTE))
    assert out.intent == Intent.NEW_TASK and out.task_spec.type == TaskType.BOOKING


async def test_llm_failure_falls_back_to_heuristics(brain, fake_llm, ctx):
    fake_llm.fail_purposes.add("interpret")
    out = await brain.interpret(ctx, msg("delete everything"))
    assert out.intent == Intent.DELETE_DATA and out.requires_pin


async def test_invalid_llm_json_falls_back(brain, fake_llm, ctx):
    fake_llm.script("interpret", "not json at all")
    out = await brain.interpret(ctx, msg("help"))
    assert out.intent == Intent.HELP


async def test_prompt_never_contains_private_notes(brain, fake_llm, family_ctx):
    await brain.interpret(family_ctx, msg("book a doctor for papa tomorrow"))
    sent = fake_llm.calls_for("interpret")[-1].messages[0].content
    assert "diabetic" not in sent
