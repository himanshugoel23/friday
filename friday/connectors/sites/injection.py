"""Prompt-injection guard for page text. Page text is data: it can never give Friday an order.

``scan`` finds instruction-like sentences (English / Hinglish); ``strip_injection`` removes them so
nothing downstream (LLM prompts, summaries) ever sees them. Detection is a safety net: the real
control is that connectors read pages only through selectors and the gate decides every action.
"""

from __future__ import annotations

import re

_PATTERNS = [
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions?|rules?|prompts?)",
    r"disregard (?:all |any )?(?:the )?(?:previous|prior|above|earlier)",
    r"forget (?:all |your |the )?(?:previous |prior )?(?:instructions?|rules?)",
    r"(?:you are|you're) now\b",
    r"\bnew (?:instructions?|rules?|task)\s*:",
    r"\bsystem (?:prompt|message|override)\b",
    r"\b(?:ai|assistant|agent|bot|llm|claude|friday)[, :]+(?:please |now )?(?:you must|must|should|do|send|pay|enter|click|tell|reveal|ignore)\b",
    r"\b(?:send|share|enter|type|reveal|tell|give|forward)\b[^.\n]{0,40}\b(?:otp|password|pin|cvv|card number|upi pin|code)\b",
    r"\b(?:pay|transfer|send)\b[^.\n]{0,30}(?:₹|rs\.?|inr)\s?\d[^.\n]{0,40}\b(?:now|immediately|to)\b",
    r"\b(?:click|press|tap)\b[^.\n]{0,20}\b(?:pay now|confirm payment|place order|buy now)\b",
    r"\binstructions? for (?:the )?(?:ai|assistant|agent|bot)\b",
    r"\bpichle (?:nirdesh|instructions?)\b[^.\n]{0,20}\b(?:bhool|ignore)",
    r"\b(?:otp|pin|password)\b[^.\n]{0,20}\bbhej(?:o|na|iye)\b",
]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def scan(text: str) -> list[str]:
    """The sentences that look like instructions to an AI (short, at most 120 chars each)."""
    hits: list[str] = []
    for m in _SENTENCE.finditer(text or ""):
        s = m.group(0).strip()
        if s and any(rx.search(s) for rx in _RX):
            hits.append(s[:120])
    return hits


def strip_injection(text: str) -> tuple[str, list[str]]:
    """(text without the instruction-like sentences, the removed sentences)."""
    hits = scan(text)
    clean = text or ""
    for h in hits:
        clean = clean.replace(h, " ")
    # sentences were cut at 120 chars; make sure no long tail survives
    for m in _SENTENCE.finditer(clean):
        if any(rx.search(m.group(0)) for rx in _RX):
            clean = clean.replace(m.group(0), " ")
    return re.sub(r"[ \t]{2,}", " ", clean).strip(), hits
