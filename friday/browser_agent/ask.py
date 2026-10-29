# ruff: noqa: E501
"""ASK-THE-USER: ONE grouped message for every missing field, defaults offered; parsing of the reply; the secret guard.

Never one question at a time: the loop collects missing fields while it keeps filling the page and flushes them together."""

from __future__ import annotations

import re

from friday.browser_agent import wording
from friday.browser_agent.types import AskField, Pending

YES = re.compile(r"^\W*(yes|yeah|yep|yup|y|haan|haa|han|ha|ji\s*haan|sahi|confirm(ed)?|go\s*ahead|do\s*it|kar\s*do|kardo|submit\s*kar\s*do)\W*$", re.I)
NO = re.compile(r"^\W*(no|nope|n|nahi|nahin|na|cancel|stop|ruko|ruk\s*jao|mat\s*karo|don'?t|do\s*not)\W*$", re.I)
OK = re.compile(r"^\W*(ok|okay|k|theek(\s*hai)?|thik(\s*hai)?|fine|use\s*(them|defaults?|suggestions?)|accept)\W*$", re.I)
DONE = re.compile(r"^\W*(done|ho\s*gaya|hogaya|kar\s*diya|kardiya|complete(d)?|saved|entered|dal\s*diya)\W*$", re.I)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_AADHAAR = re.compile(r"(?<![\d+])\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_SECRET_WORDS = re.compile(r"\b(password|passwd|passcode|pin(?!\s*-?code)|cvv|cvc|otp|one[\s-]*time|upi\s*pin)\b", re.I)
_CODE = re.compile(r"^\D{0,6}(\d{4,8})\D{0,6}$")


def yes_no(text: str) -> bool | None:
    t = (text or "").strip()
    if len(t) > 40:
        return None
    if YES.match(t):
        return True
    if NO.match(t):
        return False
    return None


def is_done(text: str) -> bool:
    return bool(DONE.match((text or "").strip()))


def looks_like_code(text: str) -> bool:
    """A bare 4-8 digit message: if an OTP is pending, the guarded login-OTP flow owns it, not this module."""
    return bool(_CODE.match((text or "").strip()))


def looks_secret(text: str) -> bool:
    """A reply that carries a password / card / PIN / OTP / Aadhaar. It is never stored, never logged, never forwarded."""
    t = text or ""
    if _CARD.search(t) or _AADHAAR.search(t):
        return True
    return bool(_SECRET_WORDS.search(t) and re.search(r"\d|is\s+\S|:\s*\S", t))


# ----------------------------------------------------------------------------- question
def merge_fields(*groups: list[AskField]) -> list[AskField]:
    seen: dict[str, AskField] = {}
    for g in groups:
        for f in g:
            if f.key not in seen:
                seen[f.key] = f
            elif not seen[f.key].default and f.default:
                seen[f.key] = seen[f.key].model_copy(update={"default": f.default})
    return list(seen.values())


def is_attest_key(key: str) -> bool:
    return key.startswith("attest:")


def format_question(fields: list[AskField], *, host: str, lang: str) -> str:
    plain = [f for f in fields if not is_attest_key(f.key)]
    attest = [f for f in fields if is_attest_key(f.key)]
    parts: list[str] = []
    n = 0
    if plain:
        parts.append(wording.line("ask_head", lang, host=host))
        for f in plain:
            n += 1
            extra = ""
            if f.options:
                extra = " " + wording.line("ask_options", lang, value=" / ".join(f.options[:8]))
            if f.default:
                extra += " " + wording.line("ask_suggest", lang, value=f.default)
            parts.append(f"{n}. {f.label}{extra}")
        parts.append(wording.line("ask_foot", lang))
    if attest:
        parts.append(wording.line("attest_head", lang))
        for f in attest:
            n += 1
            parts.append(f'{n}. "{f.label}"')
    return "\n".join(parts)


# ----------------------------------------------------------------------------- reply
_LINE = re.compile(r"^\s*(?:(\d+)[.)]\s*)?(?:(.+?)\s*[:=\-–]\s*)?(.+?)\s*$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_reply(fields: list[AskField], text: str) -> tuple[dict[str, str], list[AskField]]:
    """Rule-based. Returns (answers by field key, fields still unanswered). Attestation fields only accept yes/no."""
    t = (text or "").strip()
    answers: dict[str, str] = {}
    if not fields or not t:
        return answers, list(fields)
    if OK.match(t):
        for f in fields:
            if f.default and not is_attest_key(f.key):
                answers[f.key] = f.default
        return answers, [f for f in fields if f.key not in answers]
    lines = [ln for ln in re.split(r"[\n;]+", t) if ln.strip()]
    if len(fields) == 1:
        f = fields[0]
        val = lines[0] if len(lines) == 1 else t
        m = _LINE.match(val)
        # "Notice period: 30 days" or just "30 days"
        if m and m.group(2) and _norm(m.group(2)) and (_norm(m.group(2)) in _norm(f.label) or _norm(f.label) in _norm(m.group(2)) or _norm(m.group(2)) in _norm(f.key)):
            val = m.group(3)
        return _put(answers, f, val.strip()), [x for x in fields if x.key not in answers]
    used: set[int] = set()
    for i, ln in enumerate(lines):
        m = _LINE.match(ln)
        if not m:
            continue
        num, lab, val = m.group(1), m.group(2), m.group(3)
        target = None
        if lab:
            for f in fields:
                if f.key not in answers and (_norm(lab) in _norm(f.label) or _norm(f.label) in _norm(lab) or _norm(lab) == _norm(f.key)):
                    target = f
                    break
        if target is None and num and 1 <= int(num) <= len(fields) and fields[int(num) - 1].key not in answers:
            target = fields[int(num) - 1]
            if lab and not num:
                val = ln
            elif lab:
                val = (lab + " " + val).strip() if not _norm(lab) else val
        if target is None and not lab and not num and i < len(fields) and fields[i].key not in answers and len(lines) == len(fields):
            target = fields[i]  # one bare answer per line, in order
        if target is not None and i not in used:
            used.add(i)
            _put(answers, target, val.strip())
    return answers, [f for f in fields if f.key not in answers]


def _put(answers: dict[str, str], f: AskField, val: str) -> dict[str, str]:
    val = val.strip().strip("\"'")
    if not val:
        return answers
    if is_attest_key(f.key):
        yn = yes_no(val)
        if yn is not None:
            answers[f.key] = "yes" if yn else "no"
        return answers
    if f.options:
        hit = next((o for o in f.options if _norm(o) == _norm(val)), None) or next((o for o in f.options if _norm(val) and _norm(val) in _norm(o)), None)
        if hit is None and val.isdigit() and 1 <= int(val) <= len(f.options):
            hit = f.options[int(val) - 1]
        if hit is None:
            return answers
        val = hit
    answers[f.key] = val[:300]
    return answers


def confirm_pending(summary: str, *, host: str, lang: str, again: bool = False) -> str:
    if again:
        return wording.line("confirm_again", lang, summary=summary)
    return wording.line("confirm", lang, host=host, summary=summary)


def pending_label(p: Pending) -> str:
    return ", ".join(f.label for f in p.fields)
