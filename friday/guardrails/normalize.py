# ruff: noqa: E501
"""Text folding so the rules also see the usual evasions.

Handled: Unicode look-alikes (NFKC: full-width letters and digits), zero-width and soft-hyphen
characters, Indic digits (Devanagari ४८२१ -> 4821), letters spread out with spaces or dots
("s u i c i d e", "s.u.i.c.i.d.e"), letter repeats ("suiciiiide") and light leet-speak inside a
word ("h4ck", "su1cide", "p0rn"). Never used to *rewrite* what the user sees, only to match.
"""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­᠎"))
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_SPREAD = re.compile(r"(?<![^\W_])(?:[^\W\d_][ .\-_*]){3,}[^\W\d_](?![^\W_])")
_REPEAT = re.compile(r"([^\W\d_])\1{2,}")
_WS = re.compile(r"\s+")


def digits_to_ascii(text: str) -> str:
    """Devanagari / Arabic-Indic / full-width digits to 0-9; everything else untouched."""
    out = []
    for ch in text:
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except ValueError:
                pass
        out.append(ch)
    return "".join(out)


def fold(text: str | None) -> str:
    """Case-folded, invisible characters removed, digits ASCII, spread-out words joined."""
    t = unicodedata.normalize("NFKC", text or "").translate(_INVISIBLE)
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = digits_to_ascii(t).casefold()
    t = _SPREAD.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), t)
    t = _REPEAT.sub(r"\1\1", t)
    return _WS.sub(" ", t).strip()


def _leet_token(tok: str) -> str:
    has_letter = any(c.isalpha() for c in tok)
    has_leet = any(c in "013457@$!" for c in tok)
    if len(tok) >= 3 and has_letter and has_leet:
        return tok.translate(_LEET)
    return tok


def fold_leet(text: str | None) -> str:
    """:func:`fold` plus leet-speak undone inside mixed letter/digit words."""
    t = fold(text)
    return " ".join(_leet_token(tok) for tok in t.split(" "))


def squash(text: str | None) -> str:
    """:func:`fold_leet` with every space and punctuation mark removed (for a few high-risk terms
    that are typed with stray gaps, "kh u d ko khatam"). Only matched against short term lists."""
    return re.sub(r"[\W_]+", "", fold_leet(text))


def variants(text: str | None) -> list[str]:
    """The distinct views of a message the rules are matched against."""
    out: list[str] = []
    for v in (fold(text), fold_leet(text)):
        if v and v not in out:
            out.append(v)
    return out
