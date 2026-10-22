"""Hindi number words -> values: ``पाँच सौ`` = 500, ``डेढ़ सौ`` = 150, ``सवा पाँच`` = 5.25.

Pure and exact (``Decimal``). ``scan_number`` reads the longest number phrase at the start of a
token list; ``normalise.py`` decides whether the phrase is written as digits (an amount, a time,
a date) or stays a word ("do" in "bata do" is a verb, not 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from friday.lang_dev.translit import canon

_UNITS = """
शून्य 0
एक 1
दो 2
तीन 3
चार 4
पाँच 5 पांच 5
छह 6 छः 6 छे 6 छ 6
सात 7
आठ 8
नौ 9
दस 10
ग्यारह 11 ग्यारा 11
बारह 12 बारा 12
तेरह 13
चौदह 14
पंद्रह 15 पन्द्रह 15 पंदरह 15
सोलह 16
सत्रह 17
अठारह 18 अट्ठारह 18
उन्नीस 19
बीस 20
इक्कीस 21
बाईस 22 बाइस 22
तेईस 23 तेइस 23
चौबीस 24
पच्चीस 25
छब्बीस 26
सत्ताईस 27 सत्ताइस 27
अट्ठाईस 28 अठाईस 28 अट्ठाइस 28
उनतीस 29 उन्तीस 29
तीस 30
इकतीस 31 इकत्तीस 31
बत्तीस 32
तैंतीस 33 तेंतीस 33
चौंतीस 34 चौतीस 34
पैंतीस 35 पैंतिस 35
छत्तीस 36
सैंतीस 37 सैतीस 37
अड़तीस 38 अड़तिस 38
उनतालीस 39 उन्तालीस 39
चालीस 40
इकतालीस 41
बयालीस 42 बयालिस 42
तैंतालीस 43 तेंतालीस 43
चौवालीस 44 चौआलीस 44
पैंतालीस 45
छियालीस 46
सैंतालीस 47
अड़तालीस 48
उनचास 49
पचास 50
इक्यावन 51
बावन 52
तिरपन 53 तिरेपन 53
चौवन 54
पचपन 55
छप्पन 56
सत्तावन 57
अट्ठावन 58 अठावन 58
उनसठ 59
साठ 60
इकसठ 61
बासठ 62
तिरसठ 63 तिरेसठ 63
चौंसठ 64 चौसठ 64
पैंसठ 65
छियासठ 66
सड़सठ 67
अड़सठ 68
उनहत्तर 69
सत्तर 70
इकहत्तर 71
बहत्तर 72
तिहत्तर 73
चौहत्तर 74
पचहत्तर 75
छिहत्तर 76
सतहत्तर 77
अठहत्तर 78
उन्यासी 79
अस्सी 80
इक्यासी 81
बयासी 82
तिरासी 83
चौरासी 84
पचासी 85
छियासी 86
सत्तासी 87
अट्ठासी 88 अठासी 88
नवासी 89
नब्बे 90
इक्यानवे 91
बानवे 92
तिरानवे 93
चौरानवे 94
पंचानवे 95
छियानवे 96
सत्तानवे 97
अट्ठानवे 98 अठानवे 98
निन्यानवे 99
"""

SMALL: dict[str, int] = {}
for _line in _UNITS.strip().splitlines():
    _parts = _line.split()
    for _w, _n in zip(_parts[0::2], _parts[1::2], strict=True):
        SMALL[canon(_w)] = int(_n)

MULTIPLIERS: dict[str, int] = {
    canon("सौ"): 100,
    canon("हज़ार"): 1000,
    canon("हजार"): 1000,
    canon("लाख"): 100_000,
    canon("करोड़"): 10_000_000,
    canon("करोड"): 10_000_000,
}
DEDH = canon("डेढ़")
DHAI = canon("ढाई")
SAWA = canon("सवा")
SAADE = {canon("साढ़े"), canon("साढे"), canon("साढ़ें")}
PAUNE = {canon("पौने"), canon("पौन")}
FRACTION_WORDS = {DEDH, DHAI, SAWA, *SAADE, *PAUNE}

_Q = Decimal("0.25")


@dataclass(frozen=True)
class NumberPhrase:
    value: Decimal
    used: int  # tokens consumed
    kind: str  # "plain" | "multiplier" | "fraction"
    prefix: str | None = None  # the fraction word (canon) when kind == "fraction"
    base: int | None = None  # for sawa/saade/paune N: N


def _small(tok: str) -> int | None:
    return SMALL.get(canon(tok))


def _mult(tok: str) -> int | None:
    return MULTIPLIERS.get(canon(tok))


def is_number_word(tok: str) -> bool:
    c = canon(tok)
    return c in SMALL or c in MULTIPLIERS or c in FRACTION_WORDS


def _plain(tokens: list[str]) -> tuple[Decimal, int, bool] | None:
    """Standard Hindi grouping: ``दो हज़ार पाँच सौ बीस`` = 2520. -> (value, used, has_multiplier)."""
    total = 0
    cur = 0
    used = 0
    prev_small = False
    has_mult = False
    for tok in tokens:
        n = _small(tok)
        m = _mult(tok)
        if n is not None:
            if prev_small:
                break  # two plain numbers in a row are two numbers ("2 3")
            cur += n
            prev_small = True
        elif m is not None:
            has_mult = True
            if m == 100:
                cur = (cur or 1) * 100 if cur < 100 else cur * 100
            else:
                total += (cur or 1) * m
                cur = 0
            prev_small = False
        else:
            break
        used += 1
    if used == 0:
        return None
    return Decimal(total + cur), used, has_mult


def scan_number(tokens: list[str]) -> NumberPhrase | None:
    """The number phrase at the start of ``tokens`` (Devanagari words), or None."""
    if not tokens:
        return None
    first = canon(tokens[0])
    rest = tokens[1:]
    if first in (DEDH, DHAI):
        factor = Decimal("1.5") if first == DEDH else Decimal("2.5")
        if rest and (m := _mult(rest[0])):
            return NumberPhrase(factor * m, 2, "fraction", first)
        return NumberPhrase(factor, 1, "fraction", first)
    if first == SAWA:
        if rest and (m := _mult(rest[0])):
            return NumberPhrase(Decimal("1.25") * m, 2, "fraction", first)
        if rest and (n := _small(rest[0])) is not None:
            used = 2
            value = Decimal(n) + _Q
            if len(rest) > 1 and (m := _mult(rest[1])):
                value, used = value * m, 3
            return NumberPhrase(value, used, "fraction", first, n)
        return None
    if first in SAADE or first in PAUNE:
        sign = Decimal("0.5") if first in SAADE else -_Q
        if rest and (n := _small(rest[0])) is not None:
            used = 2
            value = Decimal(n) + sign
            if len(rest) > 1 and (m := _mult(rest[1])):
                value, used = value * m, 3
            return NumberPhrase(value, used, "fraction", first, n)
        return None
    plain = _plain(tokens)
    if plain is None:
        return None
    value, used, has_mult = plain
    return NumberPhrase(value, used, "multiplier" if has_mult else "plain")


def format_value(value: Decimal) -> str:
    """500, 5.25 -> '500', '5.25' (no trailing zeros)."""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def parse_number_phrase(text: str) -> Decimal | None:
    """Value of a whole phrase such as ``'पाँच सौ'`` or ``'सवा पाँच'``; None when ``text`` is not
    entirely a number phrase."""
    from friday.lang_dev.normalise import _ascii_digits

    toks = _ascii_digits(text).split()
    if not toks:
        return None
    if len(toks) == 1 and toks[0].replace(".", "", 1).isdigit():
        return Decimal(toks[0])
    ph = scan_number(toks)
    if ph is None or ph.used != len(toks):
        return None
    return ph.value
