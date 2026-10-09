"""Redaction applied to every turn BEFORE it is stored (defence in depth: the front door
already keeps secrets out of what it says, but callers speak them).

Uses the existing helpers: ``redact_secrets`` (digits after OTP/PIN/CVV wording),
``normalize_spoken_digits`` (so "four eight two six" is caught like "4826") and
``mask_phone`` (phone numbers). Names: the caller's known name plus anything the
front door's own ``extract_name`` finds in what they said.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from friday.core.logging import mask_phone
from friday.core.safety import _SECRET_WORDS, normalize_spoken_digits
from friday.voice.text import redact_secrets

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\d)\d(?:[\s-]?\d){7,}(?!\d)")  # card / account / id numbers
_MAX_NAME_LEN = 40
_ASKS_NAME = re.compile(r"\bname\b|naam|नाम", re.I)


def _mask_phone_match(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group())
    return mask_phone("+91" + digits[-10:])


def redact_text(text: str, *, names: Iterable[str] = ()) -> str:
    """Secrets, phone numbers, long numbers and known names removed from ``text``."""
    if not text:
        return text
    out = text
    if _SECRET_WORDS.search(out):
        # catches spoken digits too ("four eight two six"); the redacted text keeps the words
        # around the secret but not the secret, in digits or words
        out = redact_secrets(normalize_spoken_digits(out))
    out = redact_secrets(out)
    out = _PHONE.sub(_mask_phone_match, out)
    out = _LONG_NUMBER.sub("[number]", out)
    for name in names:
        name = (name or "").strip()
        if 2 <= len(name) <= _MAX_NAME_LEN:
            out = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "[name]", out, flags=re.I)
    return out


def spoken_names(
    turns: Iterable[tuple[str, str]], known: Iterable[str | None] = ()
) -> set[str]:
    """Names to scrub: the profile name plus the caller's answer to "what is your name?"
    (``turns`` = (speaker, text) pairs; speaker is "friday" or "callee")."""
    names = {n.strip() for n in known if n and n.strip()}
    try:
        from friday.brain.frontdoor import extract_name

        asked = False
        for speaker, text in turns:
            if speaker == "friday":
                asked = bool(_ASKS_NAME.search(text))
            elif asked:
                asked = False
                got = extract_name(text)
                if got:
                    names.add(got)
    except Exception:  # noqa: BLE001 - the front door's helper may change; never block storing
        pass
    # also each word of a multi-word name ("Asha Verma" -> "Asha", "Verma")
    for n in list(names):
        names.update(p for p in n.split() if len(p) >= 3)
    return names
