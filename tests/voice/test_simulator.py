"""V-1: telephony simulator driven directly through CallLeg."""

from __future__ import annotations

import pytest

from friday.core.interfaces import CallEnded, CallLeg, TelephonyProvider
from friday.core.models import AudioClass, DialStatus, Language, OutboundCallRequest

from .conftest import (
    AIRTEL,
    COOLCARE,
    FROSTY,
    HAVELI,
    LAKEVIEW,
    LOOKS,
    PLUMBER,
    SHARMA,
    SPICE,
)

DISCLOSURE = "Hi, main Friday hoon, ek AI assistant, Rahul ki taraf se call kar rahi hoon."


async def dial(sim, phone, **meta):
    leg = await sim.place_call(OutboundCallRequest(to_phone=phone, task_id="task-sim", metadata=meta))
    status = await leg.wait_for_answer(30)
    return leg, status


async def test_protocol_conformance(sim):
    assert isinstance(sim, TelephonyProvider)
    leg, _ = await dial(sim, LOOKS)
    assert isinstance(leg, CallLeg)


@pytest.mark.parametrize(
    ("phone", "status"),
    [
        (FROSTY, DialStatus.BUSY),
        (HAVELI, DialStatus.NO_ANSWER),
        ("+919999999999", DialStatus.NO_ANSWER),  # unknown number
        (LOOKS, DialStatus.ANSWERED),
    ],
)
async def test_dial_statuses(sim, phone, status):
    _, got = await dial(sim, phone)
    assert got == status


async def test_salon_quote_slots_and_confirmation(sim):
    leg, _ = await dial(sim, LOOKS)
    greeting = await leg.listen(5)
    assert greeting.audio_class == AudioClass.HUMAN and "Looks" in greeting.text
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    assert (await leg.listen(5)).text  # "Haan ji, boliye."
    await leg.speak("Men's haircut ka rate kitna hai aur kal shaam ka slot milega?", Language.HINGLISH)
    reply = (await leg.listen(5)).text
    assert "₹400" in reply and "6pm" in reply
    await leg.speak("6pm ke liye book kar dijiye please.", Language.HINGLISH)
    confirm = (await leg.listen(5)).text
    assert "6pm" in confirm and "Booking number" in confirm


async def test_callback_flow_is_polite(sim):
    leg, _ = await dial(sim, LOOKS)
    await leg.listen(5)
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    await leg.listen(5)
    await leg.speak("Main Rahul se confirm karke aapko call back karti hoon. Dhanyavaad!", Language.HINGLISH)
    reply = (await leg.listen(5)).text
    assert "call" in reply.lower()
    with pytest.raises(CallEnded):
        await leg.listen(5)


async def test_negotiation_never_below_floor(sim):
    leg, _ = await dial(sim, COOLCARE)
    await leg.listen(5)
    await leg.speak("Hi, I'm Friday, an AI assistant calling on behalf of Rahul.", Language.EN)
    await leg.listen(5)
    await leg.speak("What is the price for split AC service?", Language.EN)
    assert "₹699" in (await leg.listen(5)).text
    await leg.speak("Can you give a discount? Another shop quoted ₹500.", Language.EN)
    r1 = (await leg.listen(5)).text
    await leg.speak("Is that your best price? Any less?", Language.EN)
    r2 = (await leg.listen(5)).text
    await leg.speak("Can you reduce it a bit more?", Language.EN)
    r3 = (await leg.listen(5)).text
    assert "₹630" in r2 or "₹630" in r1  # 10% floor of 699 rounded up to 10
    assert "final" in r3.lower()


async def test_language_switch_and_ai_question(sim):
    leg, _ = await dial(sim, SHARMA)
    g = await leg.listen(5)
    assert g.language == Language.EN or g.text.startswith("Namaskar")
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    q = await leg.listen(5)
    assert q.language == Language.MR and "रोबोट" in q.text  # asks if AI, in Marathi
    await leg.speak("Haan, main ek AI assistant hoon. Consultation ka slot chahiye.", Language.HINGLISH)
    after = await leg.listen(5)
    assert after.language == Language.HI  # switched mid-call (switches_to=hi)


async def test_callback_later_persona(sim):
    leg, _ = await dial(sim, SPICE)
    g = await leg.listen(5)
    assert "5pm" in g.text
    await leg.speak("Theek hai, main 5 baje ke baad call karti hoon. Dhanyavaad.", Language.HINGLISH)
    await leg.listen(5)
    with pytest.raises(CallEnded):
        await leg.listen(5)


async def test_hangs_up_after_turns(sim):
    leg, _ = await dial(sim, PLUMBER)
    await leg.listen(5)
    with pytest.raises(CallEnded):
        for i in range(10):
            await leg.speak(f"Visit ka charge kitna hai? ({i})", Language.HINGLISH)
            await leg.listen(5)


async def test_ivr_dtmf_hold_queue_then_agent(sim, fclock):
    leg, _ = await dial(sim, AIRTEL)
    root = await leg.listen(5)
    assert root.audio_class == AudioClass.IVR_PROMPT and "press 2" in root.text.lower()
    await leg.send_dtmf("2")
    assert "broadband" in (await leg.listen(5)).text.lower()
    await leg.send_dtmf("3")
    assert "registered mobile" in (await leg.listen(5)).text.lower()
    await leg.send_dtmf("9812345678#")
    assert "executive" in (await leg.listen(5)).text.lower()
    await leg.send_dtmf("9")
    start = fclock.now()
    classes = []
    while True:
        chunk = await leg.listen(30)
        classes.append(chunk.audio_class)
        if chunk.audio_class == AudioClass.HUMAN:
            break
    assert AudioClass.HOLD_MUSIC in classes and AudioClass.QUEUE_ANNOUNCEMENT in classes
    assert (fclock.now() - start).total_seconds() >= 420
    assert "Priya" in chunk.text
    agent = leg.agent
    assert agent.entered == ["9812345678"]
    await leg.speak("Hi, I'm Friday, an AI assistant. I'd like to raise a complaint: broadband is down.", Language.EN)
    ticket = (await leg.listen(5)).text
    assert "SR" in ticket and "ticket" in ticket.lower()


async def test_ivr_wrong_branch_recovery_and_spoken_option(sim):
    leg, _ = await dial(sim, AIRTEL)
    await leg.listen(5)
    await leg.send_dtmf("2")
    await leg.listen(5)
    await leg.send_dtmf("1")  # prepaid (wrong branch)
    assert "star" in (await leg.listen(5)).text.lower()
    await leg.send_dtmf("*")  # back to main menu
    assert "broadband" in (await leg.listen(5)).text.lower()
    await leg.speak("broadband", Language.EN)  # speak the option instead of keying it
    assert "registered mobile" in (await leg.listen(5)).text.lower()


async def test_ivr_invalid_keys_hang_up(sim):
    leg, _ = await dial(sim, AIRTEL)
    await leg.listen(5)
    with pytest.raises(CallEnded):
        for _ in range(5):
            await leg.send_dtmf("7")
            await leg.listen(5)


async def test_room_hold_and_rates(sim):
    leg, _ = await dial(sim, LAKEVIEW)
    await leg.listen(5)
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    await leg.listen(5)
    await leg.speak("Kya 14 tareekh ke liye room available hai, rate kya hai?", Language.HINGLISH)
    assert "₹4,200" in (await leg.listen(5)).text
    await leg.speak("Kya aap room 24 ghante hold kar sakte hain?", Language.HINGLISH)
    assert "24" in (await leg.listen(5)).text


async def test_stock(sim):
    leg, _ = await dial(sim, "+912040000007")  # City Chemist, Marathi
    await leg.listen(5)
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    await leg.listen(5)
    await leg.speak("Dolo 650 available hai kya?", Language.HINGLISH)
    reply = await leg.listen(5)
    assert "dolo 650" in reply.text.lower() and reply.language == Language.MR


async def test_conference_add_participant_and_leave(sim):
    leg, _ = await dial(sim, LOOKS)
    await leg.listen(5)
    user = await leg.add_participant("+919812345678", announce="Connecting you to Looks")
    assert await user.wait_for_answer(25) == DialStatus.ANSWERED
    hello = await user.listen(5)
    assert hello.text
    biz = await leg.listen(5)  # business heard the user and replied
    assert biz.audio_class == AudioClass.HUMAN
    await leg.leave()
    with pytest.raises(CallEnded):
        await leg.speak("still here?", Language.EN)


async def test_recording_written_to_local_file(sim):
    leg, _ = await dial(sim, LOOKS)
    await leg.listen(5)
    await leg.speak(DISCLOSURE, Language.HINGLISH)
    await leg.hangup()
    url = await leg.recording_url()
    assert url and url.startswith("file://")
    from pathlib import Path
    from urllib.parse import urlparse

    content = Path(urlparse(url).path).read_text()
    assert "FRIDAY[hinglish]" in content


async def test_deterministic_given_seed(vsettings, fclock):
    from friday.simworld import load_world
    from friday.voice.simulator import SimulatedTelephony

    async def run_once():
        s = SimulatedTelephony(world=load_world(), clock=fclock, seed=3, media_dir=vsettings.media_dir)
        leg, _ = await dial(s, AIRTEL)
        await leg.send_dtmf("2")
        await leg.send_dtmf("3")
        await leg.send_dtmf("9812345678#")
        await leg.send_dtmf("9")
        while (await leg.listen(30)).audio_class != AudioClass.HUMAN:
            pass
        await leg.speak("I want to raise a complaint", Language.EN)
        return (await leg.listen(5)).text

    assert await run_once() == await run_once()


async def test_answer_rate_is_seeded(vsettings, fclock):
    from friday.simworld import load_world
    from friday.voice.simulator import SimulatedTelephony

    async def statuses(seed):
        s = SimulatedTelephony(world=load_world(), clock=fclock, seed=seed, answer_rate=0.5,
                               media_dir=vsettings.media_dir)
        return [(await dial(s, LOOKS))[1] for _ in range(8)]

    a, b = await statuses(11), await statuses(11)
    assert a == b and DialStatus.NO_ANSWER in a and DialStatus.ANSWERED in a
