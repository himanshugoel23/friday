"""Devanagari -> Roman transliteration for words the lexicon does not know.

A plain consonant / vowel / matra table plus a schwa-deletion rule (the inherent "a" of a Hindi
consonant is dropped at the end of a word and inside "VC_CV", so ``कितना`` -> ``kitna``, not
``kitana``). Names and rare words only need to come out readable; the words the rule banks
look for come from ``lexicon.py`` first.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

VIRAMA = "्"
NUKTA = "़"
ANUSVARA = "ं"
CANDRABINDU = "ँ"
VISARGA = "ः"

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}  # fmt: skip
# consonant + nukta
NUKTA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y",
}  # fmt: skip
INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}  # fmt: skip
MATRAS = {
    "ा": "aa", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}  # fmt: skip
LABIALS = ("p", "b", "m")
DEV_DIGITS = "०१२३४५६७८९"


def is_devanagari_char(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def is_devanagari_word(word: str) -> bool:
    return any(is_devanagari_char(c) and c not in DEV_DIGITS for c in word)


@dataclass
class _Unit:
    cons: str  # roman consonant(s), "" for an independent vowel
    vowel: str | None  # None = inherent "a"; "" = halant (no vowel); else explicit roman vowel
    tail: str = ""  # "N" = nasal (resolved to n/m later), "h" = visarga


def canon(word: str) -> str:
    """Lookup key: NFC-composed, no nukta, no zero-width joiners, chandrabindu = anusvara."""
    w = unicodedata.normalize("NFC", word)
    w = unicodedata.normalize("NFD", w).replace(NUKTA, "")
    w = w.replace("‍", "").replace("‌", "").replace(CANDRABINDU, ANUSVARA)
    return unicodedata.normalize("NFC", w)


def _units(word: str) -> list[_Unit]:
    w = unicodedata.normalize("NFD", unicodedata.normalize("NFC", word))
    w = w.replace("‍", "").replace("‌", "")
    out: list[_Unit] = []
    i, n = 0, len(w)
    while i < n:
        ch = w[i]
        if ch in INDEPENDENT_VOWELS:
            out.append(_Unit("", INDEPENDENT_VOWELS[ch]))
            i += 1
        elif ch in CONSONANTS:
            i += 1
            if i < n and w[i] == NUKTA:
                cons = NUKTA_CONSONANTS.get(ch, CONSONANTS[ch])
                i += 1
            else:
                cons = CONSONANTS[ch]
            vowel: str | None = None
            if i < n and w[i] in MATRAS:
                vowel = MATRAS[w[i]]
                i += 1
            elif i < n and w[i] == VIRAMA:
                vowel = ""
                i += 1
            out.append(_Unit(cons, vowel))
        elif ch in (ANUSVARA, CANDRABINDU):
            if out:
                out[-1].tail += "N"
            i += 1
        elif ch == VISARGA:
            if out:
                out[-1].tail += "h"
            i += 1
        else:  # a stray matra, nukta or sign: ignore
            i += 1
    return out


def transliterate_word(word: str) -> str:
    """Best-effort Roman spelling of one Devanagari word (no lexicon)."""
    units = _units(word)
    if not units:
        return ""
    last = len(units) - 1
    deleted: set[int] = set()
    for i, u in enumerate(units):
        if u.vowel is not None:
            continue
        if i == last and last > 0:
            deleted.add(i)
        elif 0 < i < last:
            nxt = units[i + 1]
            prev_ok = units[i - 1].vowel != "" and (i - 1) not in deleted
            if nxt.vowel not in (None, "") and prev_ok:
                deleted.add(i)
    parts: list[str] = []
    for i, u in enumerate(units):
        v = u.vowel
        if v is None:
            v = "" if i in deleted else "a"
        elif v == "aa" and i == last and u.cons and not u.tail:
            v = "a"  # word-final aa after a consonant is written "a": karna, mera
        s = u.cons + v
        if "N" in u.tail:
            nxt_cons = units[i + 1].cons if i < last else ""
            s += "m" if nxt_cons.startswith(LABIALS) else "n"
        if "h" in u.tail:
            s += "h"
        parts.append(s)
    return "".join(parts)
