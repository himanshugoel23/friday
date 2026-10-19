"""Phone-number helpers for consumer calls: canonical form, emergency block list, keyed hash, mask.

The plain number is only ever held in memory for the moment of dialling and in the encrypted
columns of the request/contact rows. Everything else (do-not-call, frequency counters, logs)
uses ``NumberHasher.hash`` or ``mask``.
"""

from __future__ import annotations

import re

from friday.core.crypto import FieldCipher, get_field_cipher
from friday.core.logging import mask_phone
from friday.core.models import normalize_phone

# India emergency and public-safety short codes (from general knowledge, unverified; see
# docs/LEGAL_MAP.md). Friday never dials these, in any written form.
EMERGENCY_NUMBERS = frozenset(
    {
        "100", "101", "102", "108", "112", "1091", "1098", "181", "1090", "1033", "1073",
        "1070", "1077", "1078", "139", "1930", "14567", "1092", "1095",
    }
)  # fmt: skip

_NON_DIGIT = re.compile(r"\D+")


def digits_of(raw: str) -> str:
    return _NON_DIGIT.sub("", raw or "")


def is_emergency(raw: str) -> bool:
    """True for a bare code (112), with the country code (+91 112, 0091112), a trunk 0 (0112) or
    with separators (1-1-2). Longer real numbers are never matched."""
    d = digits_of(raw)
    for _ in range(4):
        if d in EMERGENCY_NUMBERS:
            return True
        for prefix in ("00", "91", "0"):
            if d.startswith(prefix) and len(d) > len(prefix):
                d = d[len(prefix) :]
                break
        else:
            return False
    return d in EMERGENCY_NUMBERS


def canonical(raw: str) -> str | None:
    """E.164 for a plausible dialable number, else None (emergency codes are None too)."""
    if not raw or is_emergency(raw):
        return None
    bare = digits_of(raw)
    try:
        if not raw.strip().startswith("+") and bare.startswith(("1800", "1860")):
            e164 = "+91" + bare  # toll-free / shared-cost numbers
        else:
            e164 = normalize_phone(raw)
    except ValueError:
        return None
    d = e164[1:]
    if e164.startswith("+91"):
        national = d[2:]
        ok = len(national) == 10 or (national[:4] in ("1800", "1860") and len(national) in (10, 11))
        return e164 if ok else None
    return e164 if 8 <= len(d) <= 15 else None


def mask(number: str | None) -> str:
    return mask_phone(number)


class NumberHasher:
    """Keyed hash of a number (HMAC with the blind-index key); same key => same hash everywhere
    (do-not-call, frequency, contacts). Pass a cipher in tests; production uses the process one."""

    def __init__(self, cipher: FieldCipher | None = None) -> None:
        self._cipher = cipher

    @property
    def cipher(self) -> FieldCipher:
        return self._cipher or get_field_cipher()

    def hash(self, e164: str) -> str:
        return self.cipher.blind_index(e164, label="callee")
