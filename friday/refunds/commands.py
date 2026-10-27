# ruff: noqa: E501
"""Chat commands and buttons of refund tracking ("mera refund kahan hai", "Exampleair ka refund nahi
aaya 4500", "refund aa gaya 4500", button ids ``refund:<case_id>:<action>``). Not wired into the live
router yet (docs/REFUNDS.md); the service is complete without it. Returns ``None`` for anything that
is not a refund command. Parsing is by code; a message the parser cannot read is not guessed."""

from __future__ import annotations

import re
from datetime import date

from friday.core.clock import ist_date
from friday.refunds.copy import t
from friday.refunds.service import RefundReply, RefundsDisabled, RefundService

_LIST = re.compile(
    r"\bkahan\s+hai\b.*\brefund\b|\brefund\b.*\b(kahan|kab|status|list|dikhao)\b|where\s+is\s+my\s+refund|\bmy\s+refunds\b|\bmera\s+refund\b.*\bkahan\b",
    re.I,
)
_WHO = re.compile(
    r"\bkisko\s+call\b|who\s+(should|do)\s+i\s+call|\brefund\b.*\bkis\s+number\b", re.I
)
_NOT_ARRIVED = re.compile(
    r"\brefund\b.*\b(nahi\s+aaya|nahi\s+mila|nahi\s+aya|not\s+(received|arrived|come)|pending|still\s+waiting)\b|\b(nahi\s+aaya|nahi\s+mila)\b.*\brefund\b",
    re.I,
)
_RECEIVED = re.compile(
    r"\brefund\b.*\b(aa\s+gaya|aagaya|mil\s+gaya|received|arrived|credited)\b|\b(aa\s+gaya|mil\s+gaya)\b.*\brefund\b",
    re.I,
)
_ASKED = re.compile(r"\brefund\b.*\b(maang\s+liya|maanga|asked|requested)\b", re.I)
_ACK = re.compile(r"\brefund\b.*\b(acknowledged|maan\s+liya|accept(ed)?)\b", re.I)
_REJECTED = re.compile(r"\brefund\b.*\b(reject(ed)?|mana\s+kar\s+diya|denied|declined)\b", re.I)
_ESCALATE = re.compile(r"\brefund\b.*\b(escalate|upar\s+bhej)", re.I)
_CLOSE = re.compile(r"\brefund\b.*\b(band\s+karo|close|chhod\s+do|drop)\b", re.I)
_MUTE = re.compile(r"^\s*refund\s+mute\s*$", re.I)
_UNMUTE = re.compile(r"^\s*refund\s+unmute\s*$", re.I)
_NUMBER = re.compile(r"\brefund\s+number\s*[:\-]?\s*(\+?[0-9][0-9 \-]{6,17}[0-9])", re.I)
_PROMISE_HI = re.compile(
    r"^\s*(?P<vendor>[A-Za-z][\w .&'-]{1,40}?)\s+ne\s+(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]{3,9})\s+tak\s+(?:rs\.?\s*|₹\s*)?(?P<amt>\d[\d,]*(?:\.\d{1,2})?)",
    re.I,
)
_PROMISE_EN = re.compile(
    r"^\s*(?P<vendor>[A-Za-z][\w .&'-]{1,40}?)\s+(?:said|promised)\s+(?:rs\.?\s*|₹\s*)?(?P<amt>\d[\d,]*(?:\.\d{1,2})?)\s+by\s+(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]{3,9})",
    re.I,
)
_AMOUNT = re.compile(
    r"(?:rs\.?\s*|inr\s*|₹\s*)?(?<![\w.])(\d[\d,]*(?:\.\d{1,2})?)(?![\w])(?!\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b)",
    re.I,
)
_VENDOR = re.compile(
    r"^\s*(?:mera|meri|mujhe|my|the)?\s*(?P<v>[A-Za-z][\w .&'-]{1,40}?)\s+(?:ka|ki|se|ke|ne)\s+(?:.*\s)?refund\b|^\s*(?:my\s+)?refund\s+(?:from|of)\s+(?P<v2>[A-Za-z][\w .&'-]{1,40}?)(?:\s+(?:not|is|has|nahi)|\s*$|\s+\d)|^\s*(?:mera|meri|mujhe|my|the)?\s*(?P<v3>[A-Za-z][\w .&'-]{1,40}?)\s+refunds?\b",
    re.I,
)
_STOP = {"mera", "meri", "mujhe", "my", "the", "refund", "ka", "ki", "se", "ke", "ne"}
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def parse_paise(raw: str) -> int | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    paise = int(round(value * 100))
    return paise if 0 < paise <= 10_000_000_00 else None  # up to Rs 1 crore


def extract_amount(text: str) -> int | None:
    """The LAST figure of 2+ digits in the text (so a date's day number is not the amount)."""
    found = [m.group(1) for m in _AMOUNT.finditer(text) if len(re.sub(r"\D", "", m.group(1))) >= 2]
    return parse_paise(found[-1]) if found else None


def extract_vendor(text: str) -> str:
    m = _VENDOR.search(text)
    raw = (m.group("v") or m.group("v3") or m.group("v2")) if m else ""
    words = [w for w in (raw or "").split() if w.lower() not in _STOP]
    return " ".join(words).strip()


def parse_date(d: str, m: str, today: date) -> date | None:
    mon = _MONTHS.get(m[:3].lower())
    if mon is None:
        return None
    try:
        out = date(today.year, mon, int(d))
    except ValueError:
        return None
    return out if (today - out).days <= 60 else date(today.year + 1, mon, int(d))


class RefundCommands:
    def __init__(self, service: RefundService) -> None:
        self.svc = service

    async def handle_text(self, user_id: str, text: str) -> RefundReply | None:
        svc = self.svc
        if not svc.enabled_for(user_id):
            return None
        try:
            return await self._text(user_id, text)
        except RefundsDisabled:
            return None

    async def _text(self, user_id: str, text: str) -> RefundReply | None:
        svc, lang = self.svc, self.svc.lang
        today = ist_date(svc.clock.now())
        if _MUTE.match(text) or _UNMUTE.match(text):
            return await svc.set_muted(user_id, bool(_MUTE.match(text)))
        for rx in (_PROMISE_HI, _PROMISE_EN):
            m = rx.match(text)
            if m:
                d, amt = parse_date(m["d"], m["m"], today), parse_paise(m["amt"])
                case, amb = await svc.find_case(user_id, m["vendor"])
                if case is None:
                    return None if not amb else RefundReply(t("case.which", lang))
                if d is None or amt is None:
                    return RefundReply(t("promised.need", lang))
                return await svc.mark_promised(user_id, case.id, d, amt)
        if not re.search(
            r"\brefunds?\b|kisko\s+call|who\s+(should|do)\s+i\s+call|where\s+is\s+my", text, re.I
        ):
            return None
        if _LIST.search(text):
            return await svc.where_is_my_refund(user_id)
        if _NOT_ARRIVED.search(text) and not _RECEIVED.search(text):
            vendor = extract_vendor(text)
            if not vendor:
                case, _ = await svc.find_case(user_id, None)
                return (
                    await svc.open_by_user(user_id, case.vendor_name)
                    if case
                    else RefundReply(t("open.need_vendor", lang))
                )
            return await svc.open_by_user(user_id, vendor, amount_paise=extract_amount(text))
        hint = extract_vendor(text) or None
        if _NUMBER.search(text):
            case, amb = await svc.find_case(user_id, hint)
            return (
                await svc.set_number(user_id, case.id, _NUMBER.search(text).group(1))
                if case
                else RefundReply(t("case.which" if amb else "case.unknown", lang))
            )
        verbs = (
            (_RECEIVED, "received"),
            (_ASKED, "asked"),
            (_ACK, "ack"),
            (_REJECTED, "rejected"),
            (_ESCALATE, "escalate"),
            (_CLOSE, "close"),
        )
        for rx, verb in verbs:
            if rx.search(text):
                case, amb = await svc.find_case(user_id, hint)
                if case is None:
                    return RefundReply(t("case.which" if amb else "case.unknown", lang))
                return await self._verb(user_id, case.id, verb, text)
        if _WHO.search(text):
            case, amb = await svc.find_case(user_id, hint)
            return (
                await svc.who_to_call(user_id, case.id)
                if case
                else RefundReply(t("case.which" if amb else "case.unknown", lang))
            )
        return None

    async def _verb(self, user_id: str, case_id: str, verb: str, text: str) -> RefundReply:
        svc = self.svc
        if verb == "received":
            amount = extract_amount(text)
            if amount is None:
                return RefundReply(t("received.need_amount", svc.lang), case_id=case_id)
            return await svc.mark_received(
                user_id, case_id, amount, proof_text=text if len(text) > 30 else None
            )
        return await {
            "asked": svc.mark_requested,
            "ack": svc.mark_acknowledged,
            "rejected": svc.mark_rejected,
            "escalate": svc.mark_escalated,
            "close": svc.close,
        }[verb](user_id, case_id)

    async def handle_button(self, user_id: str, button_id: str) -> RefundReply | None:
        parts = button_id.split(":")
        if len(parts) != 3 or parts[0] != "refund" or not self.svc.enabled_for(user_id):
            return None
        case_id, action = parts[1], parts[2]
        svc = self.svc
        case = await svc.store.get_case(user_id, case_id)
        if case is None:  # a button of another user's case does nothing
            return RefundReply(t("case.unknown", svc.lang))
        table = {
            "yes": svc.confirm,
            "no": svc.decline,
            "asked": svc.mark_requested,
            "chase": svc.mark_escalated,
            "close": svc.close,
            "call": svc.approve_followup,
            "nocall": svc.decline_followup,
        }
        if action in table:
            return await table[action](user_id, case_id)
        if action == "recd":
            return RefundReply(t("received.need_amount", svc.lang), case_id=case_id)
        if action == "notyet":
            return RefundReply(t("notyet.ok", svc.lang), case_id=case_id)  # the schedule goes on
        return None
