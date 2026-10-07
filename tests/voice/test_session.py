"""V-2: CallSessionRunner with stub policies + the simulator."""

from __future__ import annotations

import asyncio

import pytest

from friday.core.events import CallFinished, CallStarted, CallTurnRecorded
from friday.core.interfaces import CallSessionRunner, ProviderError
from friday.core.models import (
    AccountIdentifier,
    CallAction,
    CallActionType,
    CallMode,
    CallOutcome,
    CareRequestKind,
    Delegation,
    DialStatus,
    Language,
    MidCallQuestion,
    QuestionPurpose,
    Quote,
    Speaker,
    TaskType,
    UserAnswer,
)
from friday.voice.events import CallLanguageSwitched, CallLatencyReport

from .conftest import (
    AIRTEL,
    COOLCARE,
    FROSTY,
    HAVELI,
    LOOKS,
    PLUMBER,
    SHARMA,
    SPICE,
    ScriptedPolicy,
    hangup,
    make_brief,
    no_answer_user,
    say,
)


def friday_lines(result):
    return [t.text for t in result.transcript.turns if t.speaker == Speaker.FRIDAY]


def system_lines(result):
    return [t.text for t in result.transcript.turns if t.speaker == Speaker.SYSTEM]


def test_runner_satisfies_protocol(make_runner):
    assert isinstance(make_runner(ScriptedPolicy([])), CallSessionRunner)


async def test_disclosure_first_then_pending_approval(make_runner, sim, vbus):
    events = []

    async def rec(e):
        events.append(e)

    for cls in (CallStarted, CallTurnRecorded, CallFinished):
        vbus.subscribe(cls, rec)
    quote = Quote(business_name="Looks", amount_inr=400, price_text="₹400", available_slots=["6pm"])
    policy = ScriptedPolicy(
        [
            say("Kal shaam men's haircut ka slot aur rate bata dijiye?"),
            hangup(
                CallOutcome.PENDING_APPROVAL,
                "Main Rahul se confirm karke aapko call back karti hoon. Dhanyavaad!",
                quote=quote,
            ),
        ]
    )
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.PENDING_APPROVAL
    first = friday_lines(result)[0]
    assert first.startswith("Hi, main Friday hoon, ek AI assistant, Rahul")
    # disclosure spoken before the policy's first turn ever ran
    assert any(
        "Friday hoon" in t.text for t in policy.calls[0].turns if t.speaker == Speaker.FRIDAY
    )
    assert result.quotes[0].amount_inr == 400 and result.quotes[0].call_id == result.call_id
    assert result.recording_url and result.recording_url.startswith("file://")
    assert result.answered_at and result.ended_at and result.provider == "simulator"
    assert result.from_number and result.from_number.startswith("+91")
    kinds = [type(e) for e in events]
    assert kinds[0] is CallStarted and kinds[-1] is CallFinished and CallTurnRecorded in kinds


@pytest.mark.parametrize(
    ("phone", "outcome", "dial"),
    [
        (FROSTY, CallOutcome.BUSY, DialStatus.BUSY),
        (HAVELI, CallOutcome.NO_ANSWER, DialStatus.NO_ANSWER),
        ("+919999999999", CallOutcome.NO_ANSWER, DialStatus.NO_ANSWER),
    ],
)
async def test_dial_outcomes(make_runner, phone, outcome, dial):
    policy = ScriptedPolicy([])
    result = await make_runner(policy).run(make_brief(phone), no_answer_user)
    assert result.outcome == outcome and result.dial_status == dial
    assert not policy.calls


async def test_voicemail_dial_outcome(make_runner, sim):
    from friday.voice.simulator import BusinessAgent

    biz = sim.world.by_phone(LOOKS).model_copy(deep=True)
    biz.persona.answer = "voicemail"
    sim.agent_for = lambda phone, role=None: BusinessAgent(sim, biz, 1)
    result = await make_runner(ScriptedPolicy([])).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.VOICEMAIL


async def test_voicemail_greeting_detected_after_answer(make_runner, sim):
    from friday.voice.simulator import BusinessAgent

    biz = sim.world.by_phone(LOOKS).model_copy(deep=True)
    biz.persona.notes = ["sim:voicemail_greeting"]
    biz.persona.greeting = "Hello?"
    sim.agent_for = lambda phone, role=None: BusinessAgent(sim, biz, 1)
    policy = ScriptedPolicy([])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.VOICEMAIL
    assert not friday_lines(result)  # never leaves a voicemail, no disclosure to a machine
    assert not policy.calls


@pytest.mark.parametrize(
    "outcome",
    [
        CallOutcome.SUCCESS,
        CallOutcome.PARTIAL,
        CallOutcome.DECLINED,
        CallOutcome.CALLBACK_LATER,
        CallOutcome.USER_TIMEOUT,
        CallOutcome.NEEDS_USER_VERIFICATION,
    ],
)
async def test_policy_driven_outcomes(make_runner, outcome):
    policy = ScriptedPolicy([say("Rate kya hai?"), hangup(outcome)])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert result.outcome == outcome


async def test_hung_up(make_runner):
    policy = ScriptedPolicy([say(f"Visit ka charge kitna hai? {i}") for i in range(12)])
    result = await make_runner(policy).run(make_brief(PLUMBER, "Raju"), no_answer_user)
    assert result.outcome == CallOutcome.HUNG_UP
    assert "CALLEE HUNG UP" in system_lines(result)


async def test_callback_later_classified_after_hangup(make_runner):
    policy = ScriptedPolicy(
        [
            say("Theek hai, main 5 baje ke baad call karti hoon. Dhanyavaad."),
            lambda b, t, a: hangup(
                CallOutcome.CALLBACK_LATER, None, collected={"call_after": "5pm"}
            ),
        ]
    )
    result = await make_runner(policy).run(make_brief(SPICE, "Spice Route"), no_answer_user)
    assert result.outcome == CallOutcome.CALLBACK_LATER
    assert result.collected["call_after"] == "5pm"


async def test_failed_never_raises(make_runner, sim):
    class Boom:
        async def next_call_action(self, *a):
            raise RuntimeError("model down")

    result = await make_runner(Boom()).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.FAILED and "policy" in result.error
    # polite exit was spoken
    assert any("call back" in t for t in friday_lines(result))

    class BadTel:
        name = "broken"

        async def place_call(self, req):
            raise ProviderError("broken", "carrier down")

    result = await make_runner(ScriptedPolicy([]), telephony=BadTel()).run(
        make_brief(), no_answer_user
    )
    assert result.outcome == CallOutcome.FAILED and result.dial_status == DialStatus.FAILED
    assert "carrier down" in result.error


async def test_cancelled(make_runner):
    runner = make_runner(None)

    class CancelAfterOne:
        async def next_call_action(self, brief, transcript, answers):
            runner.cancel(brief.task_id)
            return say("Rate kya hai?")

    runner._policy = CancelAfterOne()
    result = await runner.run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.CANCELLED


async def test_otp_never_reaches_speak(make_runner, sim):
    otp = say("Sure, the OTP is 482913", Language.EN)
    policy = ScriptedPolicy(
        [otp, hangup(CallOutcome.NEEDS_USER_VERIFICATION, "I'll have Rahul call you.")]
    )
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    leg = sim.legs[-1]
    assert all("482913" not in text for text, _ in leg.spoken)
    assert any(s.startswith("BLOCKED:") for s in system_lines(result))
    # policy was asked again after the block and saw the BLOCKED turn
    assert any(t.text.startswith("BLOCKED") for t in policy.calls[-1].turns)
    assert result.outcome == CallOutcome.NEEDS_USER_VERIFICATION


async def test_three_blocks_in_a_row_safe_exit(make_runner, sim):
    bad = say("Card number 4111 1111 1111 1111", Language.EN)
    result = await make_runner(ScriptedPolicy([bad, bad, bad])).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.PARTIAL
    assert all("4111" not in t for t, _ in sim.legs[-1].spoken)


async def test_commit_blocked_without_approval(make_runner, sim):
    commit = say("6pm book kar dijiye please.", commits_booking=True)
    policy = ScriptedPolicy([commit, hangup(CallOutcome.PENDING_APPROVAL)])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert "6pm book kar dijiye please." not in [t for t, _ in sim.legs[-1].spoken]
    assert any("commits_booking" in s for s in system_lines(result))
    assert result.outcome == CallOutcome.PENDING_APPROVAL


async def test_commit_allowed_on_confirmation_callback(make_runner, sim):
    commit = say("6pm book kar dijiye please.", commits_booking=True)
    policy = ScriptedPolicy([commit, hangup(CallOutcome.SUCCESS)])
    brief = make_brief(approved_terms="6pm, ₹400")
    result = await make_runner(policy).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.SUCCESS
    assert any(
        "Booking number" in t.text for t in result.transcript.turns if t.speaker == Speaker.CALLEE
    )


async def test_delegation_price_ceiling(make_runner, sim):
    deleg = Delegation(granted=True, max_price_inr=350, scope=["slot", "price"])
    over = say(
        "6pm book kar dijiye.",
        commits_booking=True,
        quote=Quote(business_name="Looks", amount_inr=400, price_text="₹400"),
    )
    policy = ScriptedPolicy([over, hangup(CallOutcome.PENDING_APPROVAL)])
    result = await make_runner(policy).run(make_brief(delegation=deleg), no_answer_user)
    assert any("delegation" in s for s in system_lines(result))
    within = say(
        "6pm book kar dijiye.",
        commits_booking=True,
        quote=Quote(business_name="Looks", amount_inr=300, price_text="₹300"),
    )
    policy = ScriptedPolicy([within, hangup(CallOutcome.SUCCESS)])
    result = await make_runner(policy).run(make_brief(delegation=deleg), no_answer_user)
    assert not any(s.startswith("BLOCKED") for s in system_lines(result))


async def test_never_claims_human(make_runner, sim):
    policy = ScriptedPolicy([say("Nahi nahi, main insaan hoon."), hangup(CallOutcome.PARTIAL)])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert "Nahi nahi, main insaan hoon." not in [t for t, _ in sim.legs[-1].spoken]
    assert any("human" in s for s in system_lines(result))


async def test_fillers_stripped_and_language_mirrored(make_runner, sim, vbus):
    switches = []

    async def rec(e):
        switches.append(e)

    vbus.subscribe(CallLanguageSwitched, rec)

    def mirror(brief, transcript, answers):
        last = transcript.last()
        return (
            None
            if last is None
            else say("Umm, consultation ka slot... kab milega?", last.language or Language.HINGLISH)
        )

    policy = ScriptedPolicy(
        [
            say("Haan, main AI assistant hoon. Consultation ka slot chahiye."),
            lambda b, t, a: say(
                "Umm, slot kab milega?",
                [x for x in t.turns if x.speaker == Speaker.CALLEE][-1].language,
            ),
            hangup(CallOutcome.PARTIAL),
        ]
    )
    result = await make_runner(policy).run(make_brief(SHARMA, "Dr Sharma"), no_answer_user)
    spoken = sim.legs[-1].spoken
    assert all("umm" not in t.lower() for t, _ in spoken)
    assert Language.MR in result.languages_heard and Language.HI in result.languages_heard
    assert spoken[2][1] == Language.HI  # mirrored the switch
    assert switches


async def test_ask_user_with_hold_lines(make_runner, sim, fclock):
    question = MidCallQuestion(
        task_id="x",
        text="Male or female stylist?",
        options=["Male", "Female"],
        purpose=QuestionPurpose.CLARIFY,
        timeout_s=90,
    )

    async def slow_user(q):
        assert q.task_id == "task-0001abcd" and q.call_id
        for _ in range(10):  # user takes a while (yields to the runner's hold-line ticks)
            await asyncio.sleep(0)
        return UserAnswer(question_id=q.id, text="Male", option_index=0)

    policy = ScriptedPolicy(
        [
            CallAction(
                type=CallActionType.ASK_USER,
                text="Ek minute ji, main Rahul se confirm kar rahi hoon.",
                question=question,
            ),
            hangup(CallOutcome.PENDING_APPROVAL),
        ]
    )
    result = await make_runner(policy).run(make_brief(), slow_user)
    lines = friday_lines(result)
    assert any("intezaar" in line for line in lines)  # polished hold line, no fillers
    assert "USER ANSWERED: Male" in system_lines(result)
    assert result.answers[0].text == "Male" and len(result.questions) == 1


async def test_ask_user_timeout_and_question_cap(make_runner):
    q = MidCallQuestion(task_id="x", text="Which branch?", timeout_s=30)
    ask = CallAction(type=CallActionType.ASK_USER, text="Ek minute ji.", question=q)
    policy = ScriptedPolicy([ask, ask, ask, hangup(CallOutcome.USER_TIMEOUT)])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    sys = system_lines(result)
    assert sys.count("USER DID NOT ANSWER WITHIN 30s") == 2
    assert any("max 2 mid-call questions" in s for s in sys)
    assert result.outcome == CallOutcome.USER_TIMEOUT


async def test_ask_user_approval_enables_commit(make_runner):
    q = MidCallQuestion(
        task_id="x", text="Book 6pm for ₹400?", purpose=QuestionPurpose.APPROVE_BOOKING
    )

    async def approve(question):
        return UserAnswer(question_id=question.id, text="Yes", approves=True)

    policy = ScriptedPolicy(
        [
            CallAction(type=CallActionType.ASK_USER, text="Ek minute ji.", question=q),
            say("6pm book kar dijiye.", commits_booking=True),
            hangup(CallOutcome.SUCCESS),
        ]
    )
    result = await make_runner(policy).run(make_brief(), approve)
    assert result.outcome == CallOutcome.SUCCESS
    assert "USER ANSWERED: Yes (APPROVED)" in system_lines(result)


def _care_brief(**kw):
    acct = AccountIdentifier(
        user_id="user-1", company="Airtel", label="Registered mobile", value="9812345678"
    )
    return make_brief(
        AIRTEL,
        "Airtel Customer Care",
        task_type=TaskType.CUSTOMER_CARE,
        company="Airtel",
        care_request=CareRequestKind.COMPLAINT,
        approved_identifiers=[acct],
        goal="Raise a complaint: broadband down for 3 days",
        **kw,
    )


async def test_customer_care_ivr_hold_ticket(make_runner, sim):
    notes = []

    async def notify(text):
        notes.append(text)

    def keys(d):
        return CallAction(type=CallActionType.PRESS_KEYS, digits=d)

    policy = ScriptedPolicy(
        [
            keys("2"),
            keys("3"),
            keys("9812345678#"),
            keys("9"),
            CallAction(type=CallActionType.WAIT_ON_HOLD),
            say("I'd like to raise a complaint, my broadband is down since 3 days.", Language.EN),
            lambda b, t, a: hangup(
                CallOutcome.SUCCESS, "Thank you, bye.", collected={"ticket": "ok"}
            ),
        ]
    )
    calls_before_hold = 5
    result = await make_runner(policy).run(_care_brief(), no_answer_user, notify)
    assert result.outcome == CallOutcome.SUCCESS
    assert result.hold_seconds >= 420
    # zero policy calls during hold: 5 before hold, then 2 after
    assert result.policy_calls == calls_before_hold + 2
    sys = system_lines(result)
    assert any(s.startswith("HUMAN AGENT JOINED AFTER") for s in sys)
    assert "DTMF: ••••••5678#" in sys  # identifiers masked in transcript
    # disclosure spoken to the human agent (English, after IVR), not to the IVR
    fl = friday_lines(result)
    assert fl[0].startswith("Hi, I'm Friday, an AI assistant")
    assert result.care and result.care.hold_seconds >= 420 and "2" in result.care.ivr_path
    assert any("Expected wait" in n for n in notes)
    assert any("SR" in t.text for t in result.transcript.turns if t.speaker == Speaker.CALLEE)


async def test_unapproved_identifier_keys_blocked(make_runner, sim):
    policy = ScriptedPolicy(
        [
            CallAction(type=CallActionType.PRESS_KEYS, digits="2"),
            CallAction(type=CallActionType.PRESS_KEYS, digits="3"),
            CallAction(type=CallActionType.PRESS_KEYS, digits="9000000000#"),
            hangup(CallOutcome.NEEDS_USER_VERIFICATION, None),
        ]
    )
    result = await make_runner(policy).run(_care_brief(), no_answer_user)
    assert "9000000000#" not in sim.legs[-1].dtmf
    assert any("approved identifier" in s for s in system_lines(result))


async def test_hold_timeout(make_runner, sim):
    policy = ScriptedPolicy(
        [
            CallAction(type=CallActionType.PRESS_KEYS, digits="2"),
            CallAction(type=CallActionType.PRESS_KEYS, digits="3"),
            CallAction(type=CallActionType.PRESS_KEYS, digits="9812345678#"),
            CallAction(type=CallActionType.PRESS_KEYS, digits="9"),
            CallAction(
                type=CallActionType.WAIT_ON_HOLD, max_hold_s=120, user_update="On hold with Airtel"
            ),
        ]
    )
    notes = []

    async def notify(t):
        notes.append(t)

    result = await make_runner(policy).run(_care_brief(), no_answer_user, notify)
    assert result.outcome == CallOutcome.HOLD_TIMEOUT
    assert 120 <= result.hold_seconds < 420
    assert result.policy_calls == 5
    assert notes[0] == "On hold with Airtel"


async def test_otp_demand_bridge_user_transferred(make_runner, sim):
    """V-7: BRIDGE_USER -> user leg joins -> Friday leaves -> TRANSFERRED."""
    from friday.voice.simulator import BusinessAgent

    biz = sim.world.by_phone(AIRTEL).model_copy(deep=True)
    biz.persona.notes = ["sim:agent_asks_otp"]
    biz.persona.ivr = {}
    biz.persona.hold_seconds = 0
    orig = sim.agent_for
    sim.agent_for = lambda phone, role=None: (
        BusinessAgent(sim, biz, 1) if phone == AIRTEL else orig(phone, role=role)
    )
    policy = ScriptedPolicy(
        [
            say("I'd like to raise a complaint about my broadband.", Language.EN),
            CallAction(
                type=CallActionType.BRIDGE_USER,
                language=Language.EN,
                text=(
                    "I'm an AI assistant and can't share verification codes. "
                    "I'll connect the account holder now."
                ),
            ),
        ]
    )
    result = await make_runner(policy).run(_care_brief(), no_answer_user)
    assert result.outcome == CallOutcome.TRANSFERRED
    sys = system_lines(result)
    assert "USER JOINED THE CALL" in sys and "FRIDAY LEFT; USER AND CALLEE BRIDGED" in sys
    main = sim.legs[0]
    assert main.left and main.children and "WHISPER" in main.children[0].events[0]


async def test_bridge_monitor_mode_redacts_otp(make_runner, sim):
    from friday.voice.simulator import BusinessAgent

    biz = sim.world.by_phone(AIRTEL).model_copy(deep=True)
    biz.persona.notes = ["sim:agent_asks_otp"]
    biz.persona.ivr = {}
    biz.persona.hold_seconds = 0
    orig = sim.agent_for
    sim.agent_for = lambda phone, role=None: (
        BusinessAgent(sim, biz, 1) if phone == AIRTEL else orig(phone, role=role)
    )
    policy = ScriptedPolicy(
        [
            say("I'd like to raise a complaint about my broadband.", Language.EN),
            CallAction(
                type=CallActionType.BRIDGE_USER,
                text="Connecting Rahul now; I'm still on the line as his AI assistant.",
                language=Language.EN,
                leave_after_bridge=False,
            ),
        ]
    )
    result = await make_runner(policy).run(_care_brief(), no_answer_user)
    assert result.outcome == CallOutcome.TRANSFERRED
    text = result.transcript.render()
    assert "482913" not in text.replace(" ", "")
    assert "[redacted]" in text


async def test_bridge_user_not_answering_returns_to_policy(make_runner, sim):
    from friday.voice.simulator import SimParty

    sim.register_party("+919812345678", SimParty(answer="no_answer"))
    policy = ScriptedPolicy(
        [
            CallAction(
                type=CallActionType.BRIDGE_USER, text="Ek minute, Rahul ko connect karti hoon."
            ),
            hangup(
                CallOutcome.NEEDS_USER_VERIFICATION,
                "Rahul abhi available nahi hain, woh aapko call karenge.",
            ),
        ]
    )
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.NEEDS_USER_VERIFICATION
    assert any(s.startswith("USER DID NOT JOIN") for s in system_lines(result))


async def test_bridge_without_user_phone_blocked(make_runner):
    policy = ScriptedPolicy(
        [
            CallAction(type=CallActionType.BRIDGE_USER, text="Connecting"),
            hangup(CallOutcome.PARTIAL),
        ]
    )
    result = await make_runner(policy).run(make_brief(user_phone=None), no_answer_user)
    assert any("no user phone" in s for s in system_lines(result))


async def test_max_duration(make_runner, fclock):
    policy = ScriptedPolicy([say(f"Rate kitna hai? {i}") for i in range(200)])
    result = await make_runner(policy).run(make_brief(max_duration_s=30), no_answer_user)
    assert result.outcome in (CallOutcome.FAILED, CallOutcome.PARTIAL)
    assert "MAX CALL DURATION REACHED" in system_lines(result)


async def test_latency_report_published(make_runner, vbus):
    reports = []

    async def rec(e):
        reports.append(e)

    vbus.subscribe(CallLatencyReport, rec)
    policy = ScriptedPolicy(
        [say("Rate kitna hai?"), say("Slot kab hai?"), hangup(CallOutcome.PARTIAL)]
    )
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert reports and reports[0].turns >= 2 and reports[0].p95_ms >= reports[0].p50_ms
    assert result.latency["turns"] >= 2
    assert result.cost_inr_est > 0


async def test_wellbeing_checkin_person(make_runner, sim):
    from friday.core.models import TargetKind
    from friday.voice.simulator import SimParty

    sim.register_party(
        "+919811100001",
        SimParty(
            name="Mummy",
            language=Language.HI,
            greeting="हैलो?",
            replies={"medicine": "हाँ, सुबह की दवाई ले ली।", "feeling": "थोड़ा चक्कर आ रहा है।"},
        ),
    )
    policy = ScriptedPolicy(
        [
            say("Mummy ji, aapne subah ki dawai li? Aur tabiyat kaisi hai?"),
            hangup(CallOutcome.SUCCESS, "Theek hai Mummy ji, dhyan rakhiye. Bye."),
        ]
    )
    brief = make_brief(
        "+919811100001",
        "Mummy",
        target_kind=TargetKind.PERSON,
        task_type=TaskType.WELLBEING_CHECKIN,
        goal="Daily wellbeing check-in",
    )
    result = await make_runner(policy).run(brief, no_answer_user)
    callee = [t.text for t in result.transcript.turns if t.speaker == Speaker.CALLEE]
    assert any("चक्कर" in c for c in callee)
    assert result.outcome == CallOutcome.SUCCESS


async def test_translator_mode_marathi(make_runner, sim):
    """V-8: business speaks Marathi; user speaks Hinglish; Friday translates both ways."""
    from friday.voice.simulator import SimParty

    class FakeTranslator:
        def __init__(self):
            self.calls = []

        async def translate(self, text, *, target, source=None, context=""):
            self.calls.append((text, target, source))
            return f"[{target.value}] {text}"

    sim.register_party(
        "+919812345678",
        SimParty(
            name="Rahul",
            language=Language.HINGLISH,
            greeting="Haan, main hoon.",
            script=["2BHK ka rent kitna hai?", "Visit ka slot kab hai?"],
        ),
    )
    tr = FakeTranslator()
    brief = make_brief(
        "+912040001001",
        "Deshpande (landlord)",
        mode=CallMode.TRANSLATOR,
        user_language=Language.HINGLISH,
        task_type=TaskType.RENTAL_HUNT,
    )
    policy = ScriptedPolicy([])
    result = await make_runner(policy, translator=tr).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.SUCCESS, result.transcript.render()
    assert not policy.calls  # translator mode uses the Translator, not the CallPolicy
    assert any(t == Language.HINGLISH and s == Language.MR for _, t, s in tr.calls)
    assert any(t in (Language.MR, Language.HI) for _, t, _s in tr.calls)
    assert int(result.collected["translated_to_callee"]) >= 1


async def test_translator_refuses_to_relay_user_otp(make_runner, sim):
    from friday.voice.simulator import SimParty

    class Echo:
        async def translate(self, text, *, target, source=None, context=""):
            return text

    sim.register_party("+919812345678", SimParty(script=["Mera OTP 4 8 2 9 1 3 hai", "bye"]))
    brief = make_brief(SHARMA, "Dr Sharma", mode=CallMode.TRANSLATOR)
    result = await make_runner(ScriptedPolicy([]), translator=Echo()).run(brief, no_answer_user)
    assert all("4 8 2 9 1 3" not in t for t, _ in sim.legs[0].spoken)
    assert any("not translated" in s for s in system_lines(result))


async def test_run_cancelled_task_hangs_up(make_runner, sim):
    async def never(q):
        await asyncio.sleep(3600)

    q = MidCallQuestion(task_id="x", text="?", timeout_s=30)
    policy = ScriptedPolicy(
        [CallAction(type=CallActionType.ASK_USER, text="Ek minute ji.", question=q)]
    )
    runner = make_runner(policy)
    task = asyncio.ensure_future(runner.run(make_brief(), never))
    for _ in range(50):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sim.legs[-1].ended


async def test_coolcare_negotiation_quote_carried(make_runner):
    q1 = Quote(business_name="CoolCare", amount_inr=699, original_amount_inr=699, price_text="₹699")
    q2 = Quote(business_name="CoolCare", amount_inr=630, original_amount_inr=699, price_text="₹630")
    policy = ScriptedPolicy(
        [
            say("What's the price for a split AC service?", Language.EN, quote=q1),
            say("Can you do a better price? Another shop quoted ₹550.", Language.EN),
            say("Any less?", Language.EN, quote=q2),
            hangup(
                CallOutcome.PENDING_APPROVAL,
                "Thank you, I'll check with Rahul and call you back.",
                quote=q2,
            ),
        ]
    )
    result = await make_runner(policy).run(make_brief(COOLCARE, "CoolCare"), no_answer_user)
    assert result.outcome == CallOutcome.PENDING_APPROVAL
    assert len(result.quotes) == 1 and result.quotes[0].negotiated
