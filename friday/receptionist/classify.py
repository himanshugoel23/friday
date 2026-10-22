# ruff: noqa: E501
"""Urgent / spam / normal: code rules first, a model only behind an interface (with a fake).

Order of rules (the first that fires decides, except where noted):
  1. an urgent contact (the user's list) -> URGENT, whatever was said (even a silent hang-up);
  2. STRONG urgent words (accident, hospital, emergency ... plus the user's own keywords) -> URGENT,
     even from an unknown number: when unsure, flag it;
  3. a known contact with ANY urgent word -> URGENT; a known contact otherwise -> NORMAL, never spam;
  4. spam patterns from an unknown caller (loan, KYC, lottery, offers, telemarketer prefix ...) -> SPAM;
  5. WEAK urgent words (urgent, jaldi, turant) from an unknown caller who is not a spam pitch -> URGENT;
  6. otherwise NORMAL, and only then may the optional model be asked.
The model can RAISE a normal call to urgent; it can lower to spam only for an unknown caller; it can
never lower an urgent call. Its output is validated; anything odd is ignored. It never sees the
user's private facts or the caller's number.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from friday.receptionist.models import CallCapture, Classification, ReceptionistConfig, Urgency

STRONG_URGENT = (
    "emergency", "accident", "hospital", "ambulance", "police", "icu", "heart attack", "ventilator",
    "serious", "critical", "injured", "unconscious", "died", "death", "passed away", "fire",
    "kidnap", "in trouble", "surgery", "operation theatre", "bachao", "madad", "madat", "tabiyat",
    "tabiyat kharab", "bimar", "behosh", "haadsa", "hadsa", "aspatal", "chot lagi", "gir gaye",
    "gir gayi", "guzar", "nidhan", "dil ka daura", "emergency hai",
    "इमरजेंसी", "एमरजेंसी", "एक्सीडेंट", "हादसा", "अस्पताल", "हॉस्पिटल", "एम्बुलेंस", "पुलिस",
    "तबीयत", "बीमार", "चोट", "बेहोश", "मदद", "बचाओ", "निधन", "आईसीयू",
)  # fmt: skip
WEAK_URGENT = (
    "urgent", "urgently", "asap", "immediately", "right away", "very important", "important",
    "jaldi", "turant", "foran", "zaruri", "zaroori", "jaruri", "bahut zaroori", "call back now",
    "जरूरी", "ज़रूरी", "तुरंत", "जल्दी", "फौरन",
)  # fmt: skip
STRONG_SPAM = (
    "personal loan", "loan", "credit card", "insurance", "policy", "kyc", "pre-approved",
    "pre approved", "preapproved", "lottery", "lucky draw", "you have won", "you won", "prize",
    "congratulations", "investment", "trading", "stock tips", "demat", "mutual fund", "emi",
    "limited time", "special offer", "discount", "free gift", "cashback", "recharge", "data pack",
    "survey", "telemarketing", "promotion", "scheme", "paise double", "inaam", "bima", "nivesh",
    "offer", "your number has been selected", "work from home", "part time job", "bitcoin",
    "लोन", "ऑफर", "बीमा", "इनाम", "निवेश", "क्रेडिट कार्ड", "केवाईसी",
)  # fmt: skip
SECRET_SCAM_CONTEXT = ("bank", "card", "account", "kyc", "block", "blocked", "atm", "upi", "debit", "credit")
SPAM_PITCH = re.compile(
    r"\b(we are calling from|calling from .{0,30}(bank|company|team)|company se bol|bank se bol|"
    r"hamari company|aapke liye ek|aapko .{0,20}offer|product|marketing|sales team|"
    r"real estate|property|plot|flat)\b",
    re.I,
)
TELEMARKETER_PREFIXES = ("140", "160")  # TRAI telemarketer series; UNVERIFIED


def _has(text: str, words: tuple[str, ...]) -> list[str]:
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    hits = []
    for w in words:
        if w.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t):
                hits.append(w)
        elif w in t:
            hits.append(w)
    return hits


def telemarketer_number(number: str | None) -> bool:
    d = re.sub(r"\D", "", number or "")
    if d.startswith("91") and len(d) > 10:
        d = d[2:]
    return len(d) >= 10 and d.startswith(TELEMARKETER_PREFIXES)


@runtime_checkable
class UrgencyModel(Protocol):
    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class FakeUrgencyModel:
    """Deterministic stand-in. ``answers``: a dict keyed by a substring of the reason, or a
    callable payload -> dict. Records every payload it saw (tests check nothing private leaks)."""

    def __init__(self, answers: dict[str, dict[str, Any]] | Callable[[dict], dict] | None = None):
        self.answers = answers or {}
        self.seen: list[dict[str, Any]] = []

    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(payload)
        if callable(self.answers):
            return self.answers(payload)
        text = (payload.get("reason") or "").lower()
        for key, ans in self.answers.items():
            if key in text:
                return ans
        return {"urgency": "normal", "reason": "fake: nothing special"}


class Classifier:
    def __init__(self, model: UrgencyModel | None = None) -> None:
        self.model = model

    async def classify(
        self, cap: CallCapture, caller_number: str | None, cfg: ReceptionistConfig
    ) -> Classification:
        said = " ".join(x for x in (cap.reason, cap.snippet) if x)
        contact_name = self._contact(caller_number, cfg)
        known = contact_name is not None or self._is(caller_number, cfg.urgent_contacts)
        base = Classification(urgency=Urgency.NORMAL, known_contact=known, contact_name=contact_name)

        if self._is(caller_number, cfg.urgent_contacts):
            base.urgency, base.reasons = Urgency.URGENT, ["urgent contact"]
            return base
        custom = _has(said, tuple(cfg.urgent_keywords))
        strong = _has(said, STRONG_URGENT)
        weak = _has(said, WEAK_URGENT)
        if custom or strong:
            base.urgency = Urgency.URGENT
            base.reasons = [f"urgent word: {w}" for w in (custom + strong)[:3]]
            return base
        if known:
            if weak:
                base.urgency = Urgency.URGENT
                base.reasons = [f"known contact + urgent word: {weak[0]}"]
            else:
                base.reasons = ["known contact"]
            return base
        spam = _has(said, STRONG_SPAM)
        if cap.asked_secret and _has(said, SECRET_SCAM_CONTEXT):
            spam = spam + ["asked for an OTP/PIN with bank/card wording"]
        pitch = bool(SPAM_PITCH.search(said))
        telemarketer = telemarketer_number(caller_number)
        if spam or telemarketer or (pitch and not weak):
            base.urgency = Urgency.SPAM
            base.reasons = (
                [f"spam word: {w}" for w in spam[:3]]
                + (["telemarketer number series"] if telemarketer else [])
                + (["sales pitch"] if pitch else [])
            )
            return base
        if weak:
            base.urgency = Urgency.URGENT
            base.reasons = [f"urgent word: {weak[0]}"]
            return base
        if cap.outcome.value == "no_message" and not said:
            base.reasons = ["no message left"]
            return base
        base.reasons = ["no rule fired"]
        return await self._ask_model(base, cap)

    @staticmethod
    def _is(number: str | None, lst: list[str]) -> bool:
        if not number:
            return False
        d = re.sub(r"\D", "", number)[-10:]
        return any(re.sub(r"\D", "", x)[-10:] == d for x in lst if x)

    @classmethod
    def _contact(cls, number: str | None, cfg: ReceptionistConfig) -> str | None:
        if not number:
            return None
        d = re.sub(r"\D", "", number)[-10:]
        for num, name in cfg.known_contacts.items():
            if re.sub(r"\D", "", num)[-10:] == d:
                return name or "contact"
        return None

    async def _ask_model(self, base: Classification, cap: CallCapture) -> Classification:
        if self.model is None or len((cap.reason or "").split()) < 3:
            return base
        payload = {"reason": cap.reason or "", "caller_name": cap.caller_name or ""}
        try:
            raw = await self.model.judge(payload)
            verdict = Urgency(str(raw.get("urgency", "")).lower())
        except Exception:  # noqa: BLE001 - a bad model answer is simply ignored
            return base
        if verdict == Urgency.URGENT:
            return base.model_copy(
                update={"urgency": Urgency.URGENT, "source": "llm",
                        "reasons": ["model: " + str(raw.get("reason", ""))[:80]]}
            )  # fmt: skip
        if verdict == Urgency.SPAM and not base.known_contact:
            return base.model_copy(
                update={"urgency": Urgency.SPAM, "source": "llm",
                        "reasons": ["model: " + str(raw.get("reason", ""))[:80]]}
            )  # fmt: skip
        return base
