# ruff: noqa: E501
"""Every callee intent with Hinglish, Hindi and English examples."""

from __future__ import annotations

import pytest

from friday.liveagent.ports import HeardUtterance
from friday.liveagent.understand_callee import CalleeIntent as I
from friday.liveagent.understand_callee import understand

EXAMPLES: list[tuple[I, list[str]]] = [
    (I.WHO_IS_THIS, ["Hello kaun bol raha hai?", "आप कौन बोल रहे हैं", "Who is this?", "Aap kaun?"]),
    (
        I.WRONG_NUMBER,
        [
            "Yeh wrong number hai",
            "गलत नंबर है",
            "You have the wrong number",
            "Yahan koi Rohan nahi rehta",
        ],
    ),
    (
        I.BUSY_CALL_BACK_LATER,
        [
            "Abhi busy hoon, baad mein call karna",
            "अभी बिज़ी हूँ, बाद में कॉल करना",
            "I am busy, call me later",
            "Meeting mein hoon",
        ],
    ),
    (
        I.STOP_CALLING,
        [
            "Dobara call mat karna",
            "दोबारा कॉल मत करना",
            "Do not call me again",
            "Mujhe bot se baat nahi karni",
            "मुझे रोबोट से बात नहीं करनी",
            "I don't want to talk to a robot",
        ],
    ),
    (
        I.ARE_YOU_AI,
        [
            "Kya aap robot ho?",
            "क्या आप रोबोट हो",
            "Are you a robot?",
            "Is this a recording?",
            "Are you a real person?",
        ],
    ),
    (
        I.ASKS_ABOUT_USER,
        ["Unka number kya hai?", "वो कहाँ रहते हैं", "Where is he right now?", "Wo kab aayenge?"],
    ),
    (
        I.ASKS_MONEY,
        ["Paise bhej do UPI se", "मुझे पैसे चाहिए", "Please send me money", "Advance dena padega"],
    ),
    (
        I.ASKS_PERSONAL_DETAILS,
        [
            "OTP bata do",
            "ओटीपी बताइए",
            "Tell me the OTP",
            "Date of birth batao",
            "Aadhaar number do",
        ],
    ),
    (I.AGREES, ["Haan ji boliye", "ठीक है", "Okay", "Yes sure", "Hello"]),
    (I.REFUSES, ["Nahi chahiye", "इंटरेस्टेड नहीं हूँ", "Not interested", "Main nahi bataunga"]),
    (
        I.ASKS_TO_REPEAT,
        ["Kya? Sunai nahi diya", "फिर से बोलिए", "Could you repeat that?", "Awaaz nahi aa rahi"],
    ),
    (I.SILENCE, ["", "   "]),
    (
        I.VOICEMAIL_BEEP,
        [
            "Please leave a message after the beep",
            "बीप के बाद अपना संदेश छोड़िए",
            "Beep ke baad apna message chhodiye",
        ],
    ),
    (
        I.IVR_MENU,
        [
            "Press 1 for billing, press 2 for support",
            "बिलिंग के लिए 1 दबाइए",
            "Billing ke liye 1 dabaiye",
        ],
    ),
    (
        I.HOLD_MUSIC,
        [
            "Your call is important to us, please stay on the line",
            "कृपया लाइन पर बने रहें",
            "Kripya line par bane rahiye",
        ],
    ),
    (I.HOSTILE, ["Shut up you idiot", "बकवास बंद करो", "Bakwas band karo"]),
    (
        I.DISTRESS,
        ["Help me, I have chest pain", "बचाओ मुझे", "Bachao bachao", "Seene mein dard ho raha hai"],
    ),
    (
        I.OFF_TOPIC,
        [
            "Cricket dekha kal?",
            "क्रिकेट देखा क्या",
            "Did you watch the cricket match",
            "Ipl ka kya hoga",
        ],
    ),
    (
        I.PROPOSES_COMMITMENT,
        [
            "Kal subah 10 baje aa jaoon, pakka karo",
            "कल सुबह 10 बजे आ जाना पक्का",
            "Please confirm it for tomorrow at 10 in the morning",
        ],
    ),
    (
        I.GIVES_ANSWER,
        [
            "Kal subah 9 baje",
            "कल सुबह 9 बजे",
            "Tomorrow at 9 in the morning",
            "Teen sau rupay lagenge",
        ],
    ),
    (I.ASKS_TO_WAIT, ["Ek minute ruko", "एक मिनट रुको", "Hold on a second"]),
    (
        I.UNREACHABLE,
        ["The number you have dialed is switched off", "आपके द्वारा डायल किया गया नंबर पहुँच से बाहर है"],
    ),
]


@pytest.mark.parametrize(("intent", "text"), [(i, t) for i, ts in EXAMPLES for t in ts])
def test_intent_examples(intent: I, text: str) -> None:
    u = understand(HeardUtterance(text=text))
    assert u.intent == intent, (text, u.intent, u.matched)
    assert 0 < u.confidence <= 1


def test_every_intent_is_exercised() -> None:
    covered = {i for i, _ in EXAMPLES} | {I.UNKNOWN}
    assert covered >= set(I)


def test_none_is_silence() -> None:
    assert understand(None).intent == I.SILENCE


def test_unknown_gets_low_confidence() -> None:
    u = understand(HeardUtterance(text="hmm"))
    assert u.intent in (I.AGREES, I.UNKNOWN)
    u = understand(HeardUtterance(text="khrr"))
    assert u.intent == I.UNKNOWN and u.confidence < 0.5


def test_audio_class_overrides_text() -> None:
    assert understand(HeardUtterance(audio_class="hold_music")).intent == I.HOLD_MUSIC
    assert (
        understand(HeardUtterance(audio_class="voicemail", text="hello")).intent == I.VOICEMAIL_BEEP
    )
    assert understand(HeardUtterance(audio_class="ivr_prompt", text="menu")).intent == I.IVR_MENU


def test_secret_is_flagged_secret() -> None:
    u = understand(HeardUtterance(text="OTP bata do"))
    assert u.detail == "secret"
    assert understand(HeardUtterance(text="date of birth batao")).detail == "identity"


def test_stop_beats_everything_in_a_long_sentence() -> None:
    u = understand(HeardUtterance(text="haan boliye par please dobara call mat karna mujhe"))
    assert u.intent == I.STOP_CALLING


def test_human_asking_to_wait_is_not_a_hold_announcement() -> None:
    assert understand(HeardUtterance(text="please hold")).intent == I.ASKS_TO_WAIT
    assert (
        understand(
            HeardUtterance(
                text="Please hold, all our agents are busy right now",
                audio_class="queue_announcement",
            )
        ).intent
        == I.HOLD_MUSIC
    )


def test_price_quote_is_not_a_money_request() -> None:
    u = understand(HeardUtterance(text="visit charge teen sau rupay hai"))
    assert u.intent == I.GIVES_ANSWER
    assert u.entities.amounts == ["300"]


def test_entities_times() -> None:
    u = understand(HeardUtterance(text="kal shaam 6 baje"))
    assert u.entities.times
    u = understand(HeardUtterance(text="Call me tomorrow at 6 in the evening"))
    assert u.entities.times and "6" in u.entities.times[0]


def test_flags() -> None:
    assert "wants_english" in understand(HeardUtterance(text="English mein baat kijiye")).flags
    assert "health_mention" in understand(HeardUtterance(text="mujhe bukhar hai aur dard")).flags
