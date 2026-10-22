"""Devanagari (or mixed-script) text -> canonical Roman Hinglish for the existing rule banks.

    normalise_text("कल 2 बजे interview है")        -> "kal 2 baje interview hai"
    normalise_text("पाँच सौ रुपये का बिल")          -> "500 rupaye ka bill"
    normalise_text("मुझे डेढ़ सौ का रिचार्ज चाहिए")  -> "mujhe 150 ka recharge chahiye"

Rules, in order: Devanagari digits and the danda become ASCII; a multi-word phrase from the
lexicon wins ("मत पूछो" -> "mat poocho"); then a Hindi number phrase (written as digits when it
is an amount, a time or a date, kept as a word when it is a verb: "bata do"); then the lexicon
word; then the transliteration table. Latin words, digits and punctuation pass through untouched,
so a text with no Devanagari comes back unchanged (``changed`` is False). The original text is
always kept on the result: logs and the displayed message use it, only the parsers see the Roman.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from friday.lang_dev.lexicon import LEXICON, MAX_PHRASE, PHRASES
from friday.lang_dev.numbers import (
    DEDH,
    DHAI,
    PAUNE,
    SAADE,
    SAWA,
    format_value,
    scan_number,
)
from friday.lang_dev.translit import (
    DEV_DIGITS,
    canon,
    is_devanagari_char,
    is_devanagari_word,
    transliterate_word,
)

Script = Literal["roman", "devanagari", "mixed"]

_DIGIT_TABLE = str.maketrans(DEV_DIGITS, "0123456789")
_TOKEN = re.compile(
    r"[ऀ-ॿ‌‍]+|[A-Za-z0-9₹%@+#/&.:'_\-]+|\s+|.", re.S
)

# Hindi words that make the number before them a quantity (digits), not a verb ("do")
_UNIT_AFTER = {
    canon(w)
    for w in (
        "बजे", "रुपये", "रुपए", "रूपये", "रुपया", "रूपए", "रु", "तारीख", "घंटे", "घंटा", "मिनट",
        "दिन", "हफ्ते", "हफ्ता", "महीने", "महीना", "साल", "प्रतिशत", "पैसे", "का", "की", "के",
        "बजकर", "तक", "को",
    )
}  # fmt: skip
_TIME_UNIT_AFTER = {canon(w) for w in ("घंटे", "घंटा", "मिनट", "घण्टे")}
_BAJE = {canon("बजे"), canon("बजकर")}
_LATIN_UNIT_AFTER = {
    "baje", "bje", "rs", "rs.", "rupees", "rupaye", "rupee", "inr", "ghante", "ghanta", "min",
    "minute", "minutes", "hours", "hour", "days", "din", "tarikh", "am", "pm",
}  # fmt: skip
_CURRENCY_BEFORE = {"₹", "rs", "rs.", "inr"}
_ROMAN_FRACTION = {DEDH: "dedh", DHAI: "dhai", SAWA: "sawa"}
_ROMAN_FRACTION.update({w: "saade" for w in SAADE})
_ROMAN_FRACTION.update({w: "paune" for w in PAUNE})


@dataclass(frozen=True)
class Normalised:
    text: str  # what the parsers should read
    original: str  # what the user wrote (logs, display)
    script: Script  # of the original
    changed: bool  # text != original

    @property
    def had_devanagari(self) -> bool:
        return self.script != "roman"


def _ascii_digits(text: str) -> str:
    return text.translate(_DIGIT_TABLE)


def script_counts(text: str) -> tuple[int, int]:
    """(Devanagari words, Latin words); numbers and punctuation are not counted."""
    deva = latin = 0
    for tok in _TOKEN.findall(_ascii_digits(text or "")):
        if is_devanagari_word(tok):
            deva += 1
        elif re.search(r"[A-Za-z]", tok):
            latin += 1
    return deva, latin


def detect_script(text: str) -> Script:
    """roman | devanagari | mixed (both scripts present)."""
    deva, latin = script_counts(text)
    if deva and latin:
        return "mixed"
    return "devanagari" if deva else "roman"


def mirror_script(text: str) -> Literal["roman", "devanagari"]:
    """The script a reply should use: Devanagari when the user wrote at least as many Devanagari
    words as Roman ones ('कल 2 बजे interview है' -> Devanagari), else Roman."""
    deva, latin = script_counts(text)
    return "devanagari" if deva and deva >= latin else "roman"


def _lookahead(tokens: list[str], i: int, limit: int = 8) -> list[tuple[int, str]]:
    """(index, word) of the Devanagari words from ``i``, crossing single spaces only."""
    out: list[tuple[int, str]] = []
    j = i
    while j < len(tokens) and len(out) < limit:
        t = tokens[j]
        if is_devanagari_word(t):
            out.append((j, t))
            j += 1
            if j < len(tokens) and tokens[j].isspace() and "\n" not in tokens[j]:
                j += 1
                continue
        break
    return out


def _next_word(tokens: list[str], j: int) -> str:
    """The first word after index ``j`` (skipping spaces), '' when none."""
    k = j + 1
    while k < len(tokens) and tokens[k].isspace():
        k += 1
    return tokens[k] if k < len(tokens) else ""


def _prev_word(out: list[str]) -> str:
    for piece in reversed(out):
        if piece.strip():
            return piece.strip().lower()
    return ""


def _is_unit(after: str) -> bool:
    if not after:
        return False
    if is_devanagari_word(after):
        return canon(after) in _UNIT_AFTER
    return after.lower().strip(".,") in _LATIN_UNIT_AFTER


def _number_piece(ph, after: str, prev: str) -> str | None:  # noqa: ANN001
    """Roman/digit text for a number phrase, or None to leave the first word as a plain word."""
    after_c = canon(after) if after and is_devanagari_word(after) else (after or "").lower()
    baje = after_c in _BAJE or after_c in {"baje", "bje"}
    money_prev = prev in _CURRENCY_BEFORE
    if ph.kind == "fraction":
        first = ph.prefix or ""
        roman = _ROMAN_FRACTION.get(first, "")
        if ph.base is not None and ph.used <= 2:  # sawa/saade/paune N  (a clock time)
            return f"{roman} {ph.base}"
        if ph.base is None and ph.used == 1 and first in (DEDH, DHAI):
            if baje or after_c in _TIME_UNIT_AFTER:
                return roman  # "dedh baje", "dhai baje", "dedh ghante baad"
            return format_value(ph.value)
        return format_value(ph.value)
    if ph.kind == "multiplier":
        return format_value(ph.value)
    # a plain number: digits when a unit follows, an amount precedes, or it is above twelve
    if ph.value > 12 or _is_unit(after) or money_prev:
        return format_value(ph.value)
    return None


def _word(tok: str) -> str:
    c = canon(tok)
    if c in LEXICON:
        return LEXICON[c]
    if "-" in tok:
        return "-".join(_word(p) for p in tok.split("-"))
    return transliterate_word(tok)


_BUS = canon("बस")
_BUS_NEXT = {canon(w) for w in ("स्टैंड", "स्टॉप", "टिकट", "में", "से", "पकड़नी", "पकड़ना")}


def _word_in_context(tok: str, tokens: list[str], i: int, out: list[str]) -> str:
    """One word, with the few homographs settled by their neighbours: ``बस`` is "bas" (enough,
    stop) in "बस करो" and "bus" in "रात 11 बजे बस है" or "बस स्टैंड"."""
    if canon(tok) == _BUS:
        nxt = _next_word(tokens, i)
        if _prev_word(out) in ("baje", "bje") or (nxt and canon(nxt) in _BUS_NEXT):
            return "bus"
    return _word(tok)


def normalise_text(text: str) -> Normalised:
    """See the module docstring. Never raises; an empty or Roman-only text is returned as is."""
    original = text or ""
    script = detect_script(original)
    if script == "roman" and not any(c in original for c in DEV_DIGITS + "।॥"):
        return Normalised(original, original, "roman", False)
    s = _ascii_digits(original).replace("।", ".").replace("॥", ".")
    tokens = _TOKEN.findall(s)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not is_devanagari_word(tok):
            out.append(tok)
            i += 1
            continue
        ahead = _lookahead(tokens, i)
        words = [w for _, w in ahead]
        # 1. phrases from the lexicon
        hit = None
        for n in range(min(MAX_PHRASE, len(words)), 1, -1):
            key = tuple(canon(w) for w in words[:n])
            if key in PHRASES:
                hit = (n, PHRASES[key])
                break
        if hit:
            n, roman = hit
            out.append(roman)
            i = ahead[n - 1][0] + 1
            continue
        # 2. number phrases
        ph = scan_number(words)
        if ph is not None:
            last_idx = ahead[ph.used - 1][0]
            piece = _number_piece(ph, _next_word(tokens, last_idx), _prev_word(out))
            if piece is not None:
                out.append(piece)
                i = last_idx + 1
                continue
        # 3. one word
        out.append(_word_in_context(tok, tokens, i, out))
        i += 1
    result = _tidy("".join(out))
    return Normalised(result, original, script, result != original)


def _tidy(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s).strip()


__all__ = [
    "Normalised",
    "detect_script",
    "is_devanagari_char",
    "mirror_script",
    "normalise_text",
    "script_counts",
]
