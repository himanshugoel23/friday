# ruff: noqa: E501
"""Which user was this forwarded call for? Identify by the redirecting (diverting) number.

The provider field that carries it is UNVERIFIED for Vobiz, so this is an ADAPTER: a configurable
list of webhook keys (``FRIDAY_RECEPTIONIST_REDIRECT_FIELDS``) and a tolerant parser for the
formats a carrier or SIP trunk may use (plain number, ``tel:``, ``sip:`` URI, SIP ``Diversion`` and
``History-Info`` headers). TODO(vobiz-probe): once ``friday receptionist probe`` shows the real key
and format, pin them here and in docs/RECEPTIONIST.md.

A call whose user cannot be determined is NEVER attributed to a guessed user.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from friday.core.models import normalize_phone

_NUM = re.compile(r"(?:sip:|sips:|tel:)?\s*(\+?\d[\d\-\s().]{6,}\d)", re.I)
_REASON = re.compile(r"reason=\"?([a-z\-]+)", re.I)


def parse_numbers(raw: str) -> list[str]:
    """All phone numbers in a header-ish string, in order (digits kept, plus sign kept)."""
    out = []
    for m in _NUM.finditer(raw or ""):
        n = re.sub(r"[^\d+]", "", m.group(1))
        if len(re.sub(r"\D", "", n)) >= 10:
            out.append(n)
    return out


def parse_reason(raw: str) -> str | None:
    m = _REASON.search(raw or "")
    return m.group(1).lower() if m else None


def pick_original(field_name: str, raw: str) -> str | None:
    """With several numbers: History-Info lists the ORIGINAL target first; Diversion headers list
    the most recent diversion first and the original LAST. A single number is returned as is."""
    nums = parse_numbers(raw)
    if not nums:
        return None
    if len(nums) == 1 or "history" in field_name.lower():
        return nums[0]
    return nums[-1]


class Route(StrEnum):
    MATCHED = "matched"  # a known user with the receptionist on
    NOT_FORWARDED = "not_forwarded"  # no redirecting number at all (a direct call to Friday)
    UNKNOWN_NUMBER = "unknown_number"  # redirecting number present but no Friday user
    DISABLED = "disabled"  # the user exists but the receptionist is off for them
    TEST_RING = "test_ring"  # the user's declined test ring came back from Friday's own pool number
    REFUSED = "refused"  # receptionist-only number: unknown / missing redirect -> fixed refusal line


@dataclass
class Resolution:
    route: Route
    user_id: str | None = None
    redirecting: str | None = None  # E.164, never logged unmasked
    field: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class UserRef:
    user_id: str
    receptionist_enabled: bool


class UserDirectory(Protocol):
    async def user_for_phone(self, phone: str) -> UserRef | None: ...


def extract_redirecting(
    params: Mapping[str, str], fields: Iterable[str], *, default_cc: str = "+91"
) -> tuple[str, str, str | None] | None:
    """(E.164 number, field name, reason) from the first configured key that carries one."""
    low = {k.lower(): (k, v) for k, v in params.items()}
    for f in fields:
        hit = low.get(f.lower())
        if hit is None or not str(hit[1]).strip():
            continue
        n = pick_original(hit[0], str(hit[1]))
        if n:
            try:
                return normalize_phone(n, default_cc), hit[0], parse_reason(str(hit[1]))
            except ValueError:
                continue
    return None


def _hint_rank(key: str) -> int:
    k = key.lower()
    return 0 if any(h in k for h in ("diver", "history", "forward", "redirect")) else 1


def candidate_values(
    raw: str | None, call_fields: Mapping[str, str] | None, fields: Iterable[str]
) -> list[tuple[str, str]]:
    """(field name, raw value) in the order they are tried: the single raw value the adapter found,
    then the configured keys, then every other captured key (Diversion / History-Info / x-* headers
    first). Nothing is guessed: each value must still contain a phone number."""
    out: list[tuple[str, str]] = []
    if raw and str(raw).strip():
        out.append(("diversion", str(raw)))
    cf = {k: str(v) for k, v in (call_fields or {}).items() if str(v).strip()}
    low = {k.lower(): k for k in cf}
    seen: set[str] = set()
    for f in fields:
        k = low.get(f.lower())
        if k is not None and k not in seen:
            seen.add(k)
            out.append((k, cf[k]))
    for k in sorted((k for k in cf if k not in seen), key=lambda x: (_hint_rank(x), x.lower())):
        out.append((k, cf[k]))
    return out


class RedirectResolver:
    def __init__(
        self,
        directory: UserDirectory,
        *,
        fields: Iterable[str],
        default_cc: str = "+91",
        friday_numbers: Callable[[], Iterable[str]] = lambda: (),
        pool_numbers: Callable[[], Iterable[str]] = lambda: (),
    ) -> None:
        self.directory, self.fields, self.default_cc = directory, list(fields), default_cc
        self.friday_numbers = friday_numbers
        self.pool_numbers = pool_numbers  # Friday's own outbound caller-ID pool (test rings)

    def _norm(self, n: str | None) -> str | None:
        if not n:
            return None
        try:
            return normalize_phone(n, self.default_cc)
        except ValueError:
            return None

    async def resolve(
        self,
        redirecting_raw: str | None,
        caller: str | None = None,
        call_fields: Mapping[str, str] | None = None,
        dialled: str | None = None,
    ) -> Resolution:
        """``redirecting_raw`` is the raw value the telephony adapter found (or None);
        ``call_fields`` are the other captured webhook keys (Diversion, History-Info, x-* headers)."""
        own = {x for x in (self._norm(n) for n in self.friday_numbers() if n) if x}
        caller_n, dialled_n = self._norm(caller), self._norm(dialled)
        e164, reason = None, None
        for name, value in candidate_values(redirecting_raw, call_fields, self.fields):
            n = self._norm(pick_original(name, value))
            # Friday's own number, the caller's own number and the dialled number are not diversions
            if n is None or n in own or n in (caller_n, dialled_n):
                continue
            e164, reason = n, parse_reason(value)
            break
        if e164 is None:
            return Resolution(Route.NOT_FORWARDED)
        ref = await self.directory.user_for_phone(e164)
        if ref is None:
            return Resolution(Route.UNKNOWN_NUMBER, None, e164, reason=reason)
        if not ref.receptionist_enabled:
            return Resolution(Route.DISABLED, ref.user_id, e164, reason=reason)
        pool = {x for x in (self._norm(n) for n in self.pool_numbers() if n) if x}
        if caller_n is not None and caller_n in (pool | own):
            # the user's own declined test ring, forwarded back from Friday's pool number
            return Resolution(Route.TEST_RING, ref.user_id, e164, reason=reason)
        return Resolution(Route.MATCHED, ref.user_id, e164, reason=reason)
