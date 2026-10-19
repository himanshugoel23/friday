"""Last-line privacy guard for anything Friday writes about a call (approval text, reports, logs).

* A private fact is replaced by "[private]".
* The callee's number in any common spelling, and any other run of 10 or more digits, is replaced
  by a masked form ("number ending 3210"). The callee's name is fine to show to the user who asked.
"""

from __future__ import annotations

import re

from friday.calls.models import CallBrief, CallRequest
from friday.calls.numbers import digits_of

_LONG_RUN = re.compile(r"(?<!\d)(?:\+?\d[\s\-().]?){10,16}(?!\d)")


def _masked(digits: str) -> str:
    return f"number ending {digits[-4:]}"


def scrub(text: str, *, request: CallRequest | None = None, brief: CallBrief | None = None) -> str:
    out = text
    if brief is not None:
        for fact in sorted(brief.private_facts, key=len, reverse=True):
            if fact.strip():
                out = re.sub(re.escape(fact.strip()), "[private]", out, flags=re.I)
    if request is not None and request.callee_number:
        d = digits_of(request.callee_number)
        if d:
            national = d[-10:]
            sep = r"[\s\-().]*"
            pattern = r"(?<!\d)(?:\+?91" + sep + r")?0?" + sep.join(national) + r"(?!\d)"
            out = re.sub(pattern, _masked(d), out)
    return _LONG_RUN.sub(lambda m: _masked(digits_of(m.group())), out)


def leaks(text: str, *, request: CallRequest | None = None, brief: CallBrief | None = None) -> bool:
    """True if ``text`` still contains a private fact or a long number (for tests and asserts)."""
    return scrub(text, request=request, brief=brief) != text
