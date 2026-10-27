"""Instinct-review guards: safety lines, language on request, quick answers, ordering."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from friday.chatbot import copy
from friday.chatbot.guards import language_request, quick_answer, safety_kind

NOW = datetime(2026, 10, 23, 8, 41, tzinfo=UTC)  # 14:11 IST


@pytest.mark.parametrize("text", [
    "Chest me dard ho ra h", "seene mein dard hai", "I can't breathe", "saans nahi aa rahi",
    "सीने में दर्द है", "heart attack lag raha hai",
])
def test_emergencies(text):
    assert safety_kind(text) == "emergency"


@pytest.mark.parametrize("text", [
    "Bukhar hai konsi dwai lu?", "which medicine for headache", "paracetamol kitni leni chahiye",
])
def test_medicine_asks_are_declined(text):
    assert safety_kind(text) == "medicine"


@pytest.mark.parametrize("text", [
    "dawai ka reminder laga do shaam 8 baje", "doctor ko call karke appointment lo",
    "remind me to take medicine at 9", "mummy ko call karo", "kal ka din kya hai",
])
def test_normal_health_and_call_requests_are_not_guarded(text):
    assert safety_kind(text) is None


@pytest.mark.parametrize("text", [
    "Bill of indian oil fuel to be submitted to company, new banana h",
    "make a fake bill for office", "nakli receipt chahiye",
])
def test_fake_bill_requests(text):
    assert safety_kind(text) == "forgery"


def test_real_bill_requests_are_not_forgery():
    assert safety_kind("mera electricity bill bhejo") is None
    assert safety_kind("bill ki photo bhej raha hoon PDF bana do") is None


@pytest.mark.parametrize("text,code", [
    ("Mughe hindi me jawab do", "hi"), ("reply in English", "en"),
    ("hinglish me baat karo", "hinglish"), ("हिंदी में जवाब दो", "hi"),
])
def test_language_requests(text, code):
    assert language_request(text) == code


def test_language_word_inside_a_task_is_not_a_request():
    assert language_request("mujhe hindi tutor ke liye call karna hai") is None
    assert language_request("english teacher ko call karo kal") is None


@pytest.mark.parametrize("text,result", [
    ("20% of 5000 kitna h", "1,000"), ("20 percent of 5000", "1,000"),
    ("12*12=", "144"), ("100 + 250 + 50 kitna", "400"), ("10/4?", "2.5"),
])
def test_calculator(text, result):
    key, f = quick_answer(text, NOW)
    assert key == "quick_calc" and f["result"] == result


@pytest.mark.parametrize("text", [
    "5000 ka bill", "2 baje call karo", "10/0?", "__import__('os')=",
    "1" * 30 + "*" + "9" * 30 + "=",
])
def test_not_a_sum_or_unsafe_input_is_left_alone(text):
    assert quick_answer(text, NOW) is None


def test_time_and_date_use_india_time():
    key, f = quick_answer("Time in delhi currently", NOW)
    assert key == "quick_time" and f["time"] == "2:11 PM"
    key, f = quick_answer("aaj ki date kya hai", NOW)
    assert key == "quick_date" and "23 October 2026" in f["date"]


def test_new_lines_exist_in_three_languages_and_are_pending():
    for key in ("safety_emergency", "safety_medicine", "refuse_forgery", "lang_set",
                "quick_calc", "quick_time", "quick_date"):
        assert set(copy.LINES[key]) == {"hinglish", "hi", "en"}
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "112" in copy.line("safety_emergency", "en")


def test_messages_from_one_sender_run_in_order():
    from friday.api.inbound import InboundPipeline
    from friday.core.models import InboundMessage

    order: list[str] = []

    class P:
        async def _handle(self, msg):
            order.append("start " + msg.text)
            await asyncio.sleep(0.05 if msg.text == "slow" else 0)
            order.append("end " + msg.text)

    async def run():
        p = P()
        a = InboundMessage(channel="whatsapp", from_phone="+919999900001", text="slow")
        b = InboundMessage(channel="whatsapp", from_phone="+919999900001", text="fast")
        c = InboundMessage(channel="whatsapp", from_phone="+919999900002", text="other")
        await asyncio.gather(InboundPipeline.handle(p, a), InboundPipeline.handle(p, b),
                             InboundPipeline.handle(p, c))
        return p

    p = asyncio.run(run())
    assert order.index("end slow") < order.index("start fast")  # same sender: no overtaking
    assert order.index("start other") < order.index("end slow")  # other senders not blocked
    assert not p.__dict__["_sender_locks"]  # no lock leak


# ---------------------------------------------------------------- through the real chatbot
async def test_chat_emergency_language_and_sums(chat):
    from friday.chatbot import copy as c

    await chat.onboard()
    out = await chat.say("Chest me dard ho ra h")
    assert "112" in out[-1].text
    out = await chat.say("Mughe hindi me jawab do")
    assert "हिंदी" in out[-1].text
    out = await chat.say("20% of 5000 kitna h")
    assert "1,000" in out[-1].text
    prof = await chat.c.repos.profiles.get_or_default((await chat.user()).id)
    assert getattr(prof.language, "value", prof.language) == "hi"
    out = await chat.say("Bukhar hai konsi dwai lu?")
    assert out[-1].text == c.line("safety_medicine", "hi")
    out = await chat.say("fake bill banao office ke liye")
    assert out[-1].text == c.line("refuse_forgery", "hi")


async def test_guards_can_be_switched_off(make_chat):
    chat = await make_chat(chatbot_guards=False, chatbot_quick_answers=False)
    try:
        await chat.onboard()
        out = await chat.say("20% of 5000 kitna h")
        assert not any("1,000" in m.text for m in out)
    finally:
        await chat.c.aclose()
