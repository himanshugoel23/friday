# ruff: noqa: E501
"""IVR menu reading: which key to press, only from a safe "press N for ..." pattern that matches
the brief's goal. Single digits only; never a number string, never an identifier."""

from __future__ import annotations

import re
from dataclasses import dataclass

from friday.liveagent.contracts import CallBrief
from friday.liveagent.slotguard import norm

_WORD_DIGIT = {
    "zero": "0", "shunya": "0", "one": "1", "ek": "1", "two": "2", "do": "2", "three": "3",
    "teen": "3", "four": "4", "char": "4", "chaar": "4", "five": "5", "paanch": "5", "panch": "5",
    "six": "6", "chhe": "6", "chah": "6", "seven": "7", "saat": "7", "eight": "8", "aath": "8",
    "nine": "9", "nau": "9",
}  # fmt: skip
_D = r"(\d|zero|one|two|three|four|five|six|seven|eight|nine|shunya|ek|do|teen|char|chaar|paanch|panch|chhe|chah|saat|aath|nau)"
_PRESS = re.compile(
    rf"press\s+{_D}\s+(?:for|to)\s+([a-z0-9ऀ-ॿ ]{{2,60}}?)(?=\s+(?:press|dial)\b|$)", re.I
)
_PRESS_B = re.compile(
    rf"([a-z0-9ऀ-ॿ ]{{2,60}}?)\s+(?:ke liye|के लिए)\s+{_D}\s+(?:dabaiye|dabayein|dabaye|dabaen|dbaye|dbaiye|दबाइए|दबाएं|दबायें|दबाएँ)",
    re.I,
)
_PRESS_C = re.compile(
    rf"{_D}\s+(?:dabaiye|dabayein|dabaye|dbaye|दबाइए|दबाएं)\s+([a-z0-9ऀ-ॿ ]{{2,40}})", re.I
)
_NEEDS_IDENTIFIER = re.compile(
    r"(enter|type|key in|dial)\s+(your\s+)?(\d+[- ]digit\s+)?(mobile|account|customer|registered|phone|card|pin|id|number|code|otp)|"
    r"(apna|apni)\s+(mobile|account|customer|number|pin)[\w ]{0,20}(daliye|darj|dalein|enter)|(otp|pin)\s+(daliye|enter|dalein)",
    re.I,
)

CONCEPTS: dict[str, set[str]] = {
    "billing": {"बिल", "बिलिंग", "भुगतान", "बकाया", "bill", "billing", "payment", "pay", "balance", "due", "invoice", "charges", "recharge", "bijli", "dues"},
    "complaint": {"शिकायत", "समस्या", "खराबी", "सर्विस", "सपोर्ट", "complaint", "shikayat", "issue", "problem", "fault", "repair", "outage", "support", "technical", "service", "not", "working"},
    "new": {"नए", "नया", "कनेक्शन", "नई", "new", "connection", "naya", "naye", "sales", "purchase", "plan", "plans", "offers", "upgrade"},
    "order": {"ऑर्डर", "डिलीवरी", "ट्रैक", "order", "delivery", "shipment", "track", "tracking", "status", "parcel", "courier", "package"},
    "refund": {"रिफंड", "रद्द", "वापसी", "refund", "cancel", "cancellation", "return", "returns"},
    "appointment": {"अपॉइंटमेंट", "बुकिंग", "appointment", "booking", "schedule", "reservation", "visit"},
    "account": {"account", "profile", "kyc", "update", "details", "address"},
    "agent": {"एजेंट", "प्रतिनिधि", "कस्टमर", "केयर", "ग्राहक", "agent", "representative", "executive", "operator", "human", "customer", "care", "queries", "other", "anything", "else", "speak", "talk"},
}  # fmt: skip


@dataclass
class IvrOption:
    digit: str
    label: str


def parse_options(text: str) -> list[IvrOption]:
    t = norm(text)
    out: list[IvrOption] = []
    seen: set[str] = set()

    def add(d: str, label: str) -> None:
        digit = _WORD_DIGIT.get(d.lower(), d)
        label = re.split(r"\b(?:press|dial)\b|\bdabai\w*", label.strip())[0].strip()
        if digit.isdigit() and len(digit) == 1 and digit not in seen:
            seen.add(digit)
            out.append(IvrOption(digit, label))

    for m in _PRESS.finditer(t):
        add(m.group(1), m.group(2))
    for seg in re.split(r"[.,;]| aur | and ", t):
        for m in _PRESS_B.finditer(seg):
            add(m.group(2), m.group(1))
    for m in _PRESS_C.finditer(t):
        add(m.group(1), m.group(2))
    return out


def needs_identifier(text: str) -> bool:
    return bool(_NEEDS_IDENTIFIER.search(norm(text)))


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 4 and w.endswith("s") else w


def _concepts(words: set[str]) -> set[str]:
    stemmed = {_stem(w) for w in words} | words
    return {c for c, ws in CONCEPTS.items() if stemmed & ws}


def brief_words(brief: CallBrief) -> set[str]:
    text = " ".join([brief.goal, brief.goal_spoken or "", *brief.ask_list, *brief.must_say])
    return {_stem(w) for w in norm(text).split() if len(w) >= 3}


def choose_option(
    options: list[IvrOption], brief: CallBrief, tried: list[str]
) -> tuple[IvrOption | None, str]:
    """(option, why). Best concept/word match with the goal; an "agent" option is the single
    fallback. A digit already pressed on an earlier menu is not pressed again."""
    bw = brief_words(brief)
    bconcepts = _concepts(bw) - {"agent"}
    scored: list[tuple[int, IvrOption]] = []
    for o in options:
        if o.digit in tried:
            continue
        lw = {_stem(w) for w in o.label.split()}
        score = 2 * len(_concepts(lw) & bconcepts) + len(lw & bw)
        if _concepts(lw) == {"agent"}:
            score = 0
        scored.append((score, o))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], "label matches the goal"
    for _s, o in scored:
        if "agent" in _concepts({_stem(w) for w in o.label.split()}):
            return o, "no label matches the goal: ask for a person"
    return None, "no safe match"
