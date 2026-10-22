"""What did the caller just say? Deterministic rules (Hinglish / Hindi / English), no model.

Reuses the live engine's callee understanding for silence, "are you AI", "who is this", questions
about the user, secrets and wrong number; adds what an inbound receptionist needs: abuse, the
caller's name, a volunteered call-back number, "do not note this down", "put me through", "will he
call me back / confirm this" and yes / no for the read-back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from friday.liveagent.ports import HeardUtterance
from friday.liveagent.understand_callee import CalleeIntent, understand


class Said(StrEnum):
    SILENCE = "silence"
    ABUSE = "abuse"
    SECRET = "secret"  # asks for / offers an OTP, PIN, card
    AI_QUESTION = "ai_question"
    WHO = "who"
    WRONG_NUMBER = "wrong_number"
    ASKS_USER_INFO = "asks_user_info"  # where is he, his number, his schedule
    WANTS_CONNECT = "wants_connect"  # put me through / let me talk to him
    WANTS_PROMISE = "wants_promise"  # will he call me back / tell him to come / confirm
    DECLINES_NOTES = "declines_notes"
    YES = "yes"
    NO = "no"
    NOTHING_MORE = "nothing_more"  # "bas itna hi", "that's all"
    CONTENT = "content"


@dataclass
class Heard:
    said: Said
    text: str = ""
    name: str | None = None
    reason: str | None = None  # the text without the self-introduction
    callback_number: str | None = None
    language: str | None = None


ABUSE = re.compile(
    r"(?:madarchod|behenchod|bhosd|chutiy|gaand|harami|kutt[ae]|kamine|saala|saale|randi|"
    r"fuck|bastard|bitch|asshole|shit|idiot|stupid|bewakoof|gandu|"
    r"मादरचोद|बहनचोद|भोसड|चूतिय|गांड|हरामी|कुत्ते|कमीने|साला|साले|रंडी)",
    re.I,
)
_YES = re.compile(
    r"^\s*(?:haan+|han+|ha|ji|ji haan|haan ji|yes|yeah|yep|yup|correct|right|sahi|bilkul|theek|"
    r"theek hai|ok|okay|that'?s right|sahi hai|हाँ|हां|जी|सही|ठीक)\b",
    re.I,
)
_NO = re.compile(
    r"^\s*(?:no|nahi+|nahin|nope|galat|wrong|na\b|नहीं|गलत|not really|that'?s not)", re.I
)
_NOTHING_MORE = re.compile(
    r"\b(?:bas itna|bas yahi|that'?s all|that is all|that'?s it|nothing else|aur kuch nahi|"
    r"itna hi|बस इतना|बस यही)\b",
    re.I,
)
_DECLINE = re.compile(
    r"\b(?:mat likho|mat likhna|note mat|kuch note nahi|nothing (?:to )?note|don'?t (?:write|note|record)|"
    r"do not (?:write|note|record)|no need to note|off the record|record mat|likhna mat|"
    r"नोट मत|मत लिखो)\b",
    re.I,
)
_CONNECT = re.compile(
    r"\b(?:put (?:me|him) through|connect me|transfer (?:me|the call)|let me (?:talk|speak)|"
    r"give (?:him|the phone)|phone (?:do|dijiye|de do)|baat karwa|baat karao|baat karni hai unse|"
    r"unse baat|usse baat|speak to (?:him|her|them)|talk to (?:him|her|them)|"
    r"call (?:him|her) (?:now|up)|bulao|bula do|line par laiye)\b",
    re.I,
)
_PROMISE = re.compile(
    r"\b(?:will (?:he|she|they) call|call me back|callback karenge|call karenge|"
    r"promise|confirm (?:it|that|karo)|pakka|guarantee|tell (?:him|her) to (?:come|pay|send|call)|"
    r"(?:aa|aana|bhej|pay|payment) (?:jaana|karo|kar do)|ok(?:ay)? (?:he|she) will|"
    r"will he come|will she come|agree|haan bol do|bol dena (?:ki )?haan|say yes)\b",
    re.I,
)
_INFO = re.compile(
    r"\b(?:where (?:is|are)|kahan (?:hain|hai|gaye|gayi)|kidhar|which city|kis shehar|address|"
    r"ghar ka|office ka|his number|her number|unka number|mobile number do|what time|kab aayenge|"
    r"kab milenge|when will (?:he|she)|is he (?:at|in|home)|ghar par hain|schedule|busy kyun|"
    r"kya kar rahe|kaun sa hotel|location|kab tak)\b",
    re.I,
)
_NAME_PATTERNS = [
    re.compile(
        r"(?:mera naam|my name is|meri naam|naam hai|मेरा नाम|यह\s+है|this is|i am|i'm|main)\s+"
        r"(?P<n>[A-Za-zऀ-ॿ]{2,20}(?:\s+[A-Za-zऀ-ॿ]{2,20}){0,2})",
        re.I,
    ),
    re.compile(
        r"(?P<n>[A-Za-zऀ-ॿ]{2,20}(?:\s+[A-Za-zऀ-ॿ]{2,20}){0,1})\s+"
        r"(?:bol raha|bol rahi|bol rha|bol rhi|speaking|here|bolta|bolti|बोल रहा|बोल रही)",
        re.I,
    ),
]
_NAME_STOP = re.compile(
    r"\b(?:from|se|ka|ki|ke|here|bol|bolta|bolti|speaking|hai|hoon|hu|hun|calling|and|aur|"
    r"ne|ko|mein|me|for|about|regarding|baare|bare|at|of|the|a|an|your|aapka|aapke|aap|kaam|call|"
    r"phone|se baat|karna|karni|chahta|chahti|chahte|wants|want|need|needs|have|had|was|is|are|"
    r"sir|madam|ji|bhai|sahab|saab|उनसे|से|का|की|है|हूँ|हूं|और)\b",
    re.I,
)
_NOT_A_NAME = {
    "main", "mai", "me", "the", "a", "an", "yes", "no", "haan", "nahi", "ji", "ok", "okay", "hello",
    "hi", "hii", "namaste", "sir", "madam", "uh", "um", "hmm", "kaun", "who", "what", "kya",
    "calling", "call", "phone", "ek", "one", "urgent", "bahut", "very", "just", "bas", "abhi",
}
_PHONE = re.compile(r"(?:\+?91[\s-]?)?(?:\d[\s-]?){10}")
_SECRET = re.compile(r"\b(?:otp|pin|cvv|cvc|password|passcode|card number|ओटीपी|पिन)\b", re.I)


def _clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = []
    for tok in raw.split():
        if _NAME_STOP.fullmatch(tok) or tok.lower() in _NOT_A_NAME:
            if parts:
                break
            continue
        parts.append(tok)
    name = " ".join(parts[:2]).strip()
    if len(name) < 2 or name.lower() in _NOT_A_NAME:
        return None
    return name.title() if name.isascii() else name


def extract_name(text: str) -> str | None:
    for rx in _NAME_PATTERNS:
        m = rx.search(text)
        if m:
            n = _clean_name(m.group("n"))
            if n:
                return n
    return None


def strip_intro(text: str, name: str | None) -> str:
    """The caller's words without 'main Rahul bol raha hoon' style self-introduction."""
    out = text
    if name:
        out = re.sub(
            rf"(?:mera naam|my name is|this is|i am|i'm|main)?\s*{re.escape(name)}\s*"
            r"(?:hai|hoon|hu|bol raha hoon|bol rahi hoon|bol raha|bol rahi|speaking|here)?[\s,.]*",
            " ",
            out,
            count=1,
            flags=re.I,
        )
    out = re.sub(r"^\s*(?:hello|hi|namaste|haan ji|ji|haan|yes|actually|so|toh)[\s,.]+", "", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip(" ,.")


def extract_number(text: str) -> str | None:
    m = _PHONE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return "+91" + digits if len(digits) == 10 else None


def hear(utt: HeardUtterance | None, *, awaiting_confirm: bool = False) -> Heard:
    text = (utt.text if utt else "") or ""
    text = text.strip()
    lang = utt.language if utt else None
    if not text or (utt is not None and utt.audio_class in {"silence", "hold_music"}):
        return Heard(Said.SILENCE, "", language=lang)
    if ABUSE.search(text):
        return Heard(Said.ABUSE, text, language=lang)
    if awaiting_confirm:
        if _NOTHING_MORE.search(text) or (_YES.match(text) and len(text.split()) <= 5):
            return Heard(Said.YES, text, language=lang)
        if _NO.match(text) and len(text.split()) <= 5:
            return Heard(Said.NO, text, language=lang)
    u = understand(utt)
    name = extract_name(text)
    number = extract_number(text)

    def mk(said: Said) -> Heard:  # keep a self-introduction / number given in the same breath
        return Heard(said, text, name=name, callback_number=number, language=lang)

    if u.intent == CalleeIntent.ASKS_PERSONAL_DETAILS and u.detail == "secret" or _SECRET.search(text):
        return Heard(Said.SECRET, text, language=lang)
    if u.intent == CalleeIntent.ARE_YOU_AI:
        return mk(Said.AI_QUESTION)
    if u.intent == CalleeIntent.WRONG_NUMBER:
        return Heard(Said.WRONG_NUMBER, text, language=lang)
    if _DECLINE.search(text):
        return mk(Said.DECLINES_NOTES)
    if _CONNECT.search(text):
        return mk(Said.WANTS_CONNECT)
    if _PROMISE.search(text):
        return mk(Said.WANTS_PROMISE)
    if u.intent == CalleeIntent.ASKS_ABOUT_USER or _INFO.search(text):
        return mk(Said.ASKS_USER_INFO)
    if u.intent == CalleeIntent.WHO_IS_THIS and len(text.split()) <= 6:
        return Heard(Said.WHO, text, language=lang)
    reason = strip_intro(text, name)
    if number:
        reason = re.sub(_PHONE, " ", reason)
        reason = re.sub(r"\s+", " ", reason).strip(" ,.")
        reason = re.sub(
            r"\b(?:mera number|my number|number hai|call me on|is|hai)\s*$", "", reason, flags=re.I
        ).strip(" ,.")
    if reason and len(reason.split()) <= 2 and reason.lower() in {
        "mera", "my", "number", "mera number", "my number", "is", "hai", "call me", "call me on"
    }:
        reason = ""
    return Heard(
        Said.CONTENT, text, name=name, reason=reason or None, callback_number=number, language=lang
    )
