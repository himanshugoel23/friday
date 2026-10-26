# ruff: noqa: E501
"""Rule-based guards and quick answers learned from the Instinct chat review
(docs/CHATBOT_PERSONA.md, appendix C). Everything here is deterministic: no model, no guessing.

* ``safety_kind``: an emergency (chest pain, cannot breathe, self-harm) or a medicine / dose ask, or
  a request to fake a bill. These are answered with a fixed line before anything else runs.
* ``language_request``: "Hindi me jawab do" / "reply in English" sets the reply language.
* ``quick_answer``: a percentage, simple arithmetic, the time in India, today's date. Computed in
  code, never by a model. Anything else is left to the normal flows.
"""

from __future__ import annotations

import ast
import operator
import re
from datetime import datetime

from friday.core.clock import to_ist

_I = re.IGNORECASE

# ------------------------------------------------------------------ safety
_EMERGENCY = re.compile(
    r"(?:chest|seene|seena|sine)\s*(?:me|mein|mai|men)?\s*(?:\w+\s+){0,2}(?:pain|dard|dukh)|"
    r"(?:can'?t|cannot|unable\s+to)\s+breathe|saans\s+(?:nahi|lene\s+mein|phool)|"
    r"heart\s+attack|dil\s+ka\s+daura|overdose|suicid|khud\s+ko\s+(?:khatam|maar)|"
    r"marna\s+chah|jaan\s+de\s+du|unconscious|behosh|"
    r"सीने\s+में\s+दर्द|सांस\s+नहीं|साँस\s+नहीं|आत्महत्या",
    _I,
)
_MED_WORDS = (
    r"(?:dawai|dawa|dwai|dawaai|medicine|medication|tablet|goli|syrup|dose|dosage|antibiotic|"
    r"paracetamol|crocin|dolo|ibuprofen|aspirin|दवा|दवाई|गोली)"
)
_MEDICINE = re.compile(
    rf"(?:kaun\s*si|konsi|kon\s*si|which|what|kya|konsa|kaunsa)\W+(?:\w+\W+){{0,3}}{_MED_WORDS}|"
    rf"{_MED_WORDS}\W+(?:\w+\W+){{0,3}}(?:lu|loon|lun|le\s+sakta|le\s+sakti|kitni|kitna|how\s+much|"
    rf"how\s+many|lena\s+chahiye|batao|bataiye|suggest)|"
    r"(?:bukhar|fever|khansi|cough|sar\s*dard|headache|pet\s*dard)\W+(?:\w+\W+){0,4}"
    rf"(?:{_MED_WORDS}|ilaaj|treatment)",
    _I,
)
_MED_EXEMPT = re.compile(r"\b(?:remind|reminder|yaad|call|appointment|order|delivery|pharmacy)\b|रिमाइंडर", _I)
_FORGERY = re.compile(
    r"\b(?:fake|nakli|jaali|jali|false|jhootha|jhuta)\s+(?:bill|receipt|invoice|certificate|document|"
    r"slip|ticket)\b|"
    r"\b(?:bill|receipt|invoice|certificate)\s+(?:fake|nakli|jaali|jali)\b|"
    r"^(?=.*\b(?:bill|receipt|invoice)\b)(?=.*\b(?:new|naya|naye|sample|fresh)\b)"
    r"(?=.*\b(?:banao|bana\s+do|banana|banani|generate|create|make)\b)"
    r"(?=.*\b(?:company|office|reimburse\w*|claim|submit\w*)\b)",
    _I,
)


def safety_kind(text: str | None) -> str | None:
    """``emergency`` | ``medicine`` | ``forgery`` | None."""
    t = " ".join((text or "").split())
    if not t or len(t) > 400:
        return None
    if _EMERGENCY.search(t):
        return "emergency"
    if _FORGERY.search(t):
        return "forgery"
    if _MEDICINE.search(t) and not _MED_EXEMPT.search(t):
        return "medicine"
    return None


# ------------------------------------------------------------------ language on request
_LANG_REQ = re.compile(
    r"\b(hindi|hinglish|english|angrezi)\b\W+(?:me|mein|mai|men|main|में)\W+"
    r"(?:\w+\W+){0,2}(?:jawab|jawaab|reply|baat|bolo|bol|likho|answer|batao|bataiye|samjhao)|"
    r"\b(?:reply|answer|talk|speak|write|respond)\b\W+(?:\w+\W+){0,2}(?:in)\W+(hindi|hinglish|english)\b|"
    r"\b(hindi|english|hinglish)\W+(?:please|plz|pls)\b|"
    r"(हिंदी|हिन्दी|अंग्रेज़ी|अंग्रेजी)\s+(?:में|मे)\s+(?:\S+\s+){0,2}(?:जवाब|बात|बोलो|लिखो|बताओ)",
    _I,
)
_LANG_CODE = {
    "hindi": "hi", "हिंदी": "hi", "हिन्दी": "hi", "english": "en", "angrezi": "en",
    "अंग्रेज़ी": "en", "अंग्रेजी": "en", "hinglish": "hinglish",
}


def language_request(text: str | None) -> str | None:
    """``hi`` | ``en`` | ``hinglish`` when the whole message is a request to change language."""
    t = " ".join((text or "").split())
    if not t or len(t) > 80:
        return None
    m = _LANG_REQ.search(t)
    if not m:
        return None
    word = next((g for g in m.groups() if g), "")
    return _LANG_CODE.get(word.lower())


# ------------------------------------------------------------------ quick answers
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_PERCENT = re.compile(
    rf"^\W*{_NUM}\s*(?:%|percent|pratishat|प्रतिशत)\s*(?:of|ka|ki|ke)\s*{_NUM}"
    r"\s*(?:kitna|kitne|how\s+much|=|\?|hai|h|hota\s+hai)?(?:\s+(?:h|hai|hota\s+hai))?\W*$",
    _I,
)
_ARITH = re.compile(r"^\W*([\d\s.+\-*/x×÷()]+?)\s*(?:=|\?|kitna(?:\s+hota)?(?:\s+hai)?|equals?)\W*$", _I)
_TIME = re.compile(
    r"\b(?:time\s+(?:in|now|kya|batao)|current\s+time|what\s+time|abhi\s+kitne\s+baje|kitne\s+baje|"
    r"time\s+kya\s+hua)\b",
    _I,
)
_DATE = re.compile(
    r"\b(?:today'?s\s+date|aaj\s+(?:ki\s+)?(?:date|tarikh|tareekh)|aaj\s+kya\s+(?:date|din)|"
    r"what\s+(?:is\s+)?(?:the\s+)?date|aaj\s+konsa\s+din|which\s+day\s+is\s+today)\b",
    _I,
)
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("not arithmetic")


def _fmt(v: float) -> str:
    if abs(v) >= 1e15:
        raise ValueError("too large")
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def quick_answer(text: str | None, now: datetime) -> tuple[str, dict[str, str]] | None:
    """``(copy_key, fields)`` for a sum, a percentage, the time or the date; else None."""
    t = " ".join((text or "").split())
    if not t or len(t) > 80:
        return None
    try:
        if m := _PERCENT.match(t):
            return "quick_calc", {"expr": f"{m.group(1)}% of {m.group(2)}",
                                   "result": _fmt(_num(m.group(1)) * _num(m.group(2)) / 100)}
        if m := _ARITH.match(t):
            expr = m.group(1).replace("x", "*").replace("×", "*").replace("÷", "/")
            if len(re.findall(r"\d+(?:\.\d+)?", expr)) >= 2 and re.search(r"[+\-*/]", expr):
                return "quick_calc", {"expr": " ".join(m.group(1).split()),
                                       "result": _fmt(_eval(ast.parse(expr.strip(), mode="eval")))}
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError, RecursionError):
        return None
    if _TIME.search(t):
        return "quick_time", {"time": to_ist(now).strftime("%I:%M %p").lstrip("0")}
    if _DATE.search(t):
        return "quick_date", {"date": to_ist(now).strftime("%A, %d %B %Y")}
    return None
