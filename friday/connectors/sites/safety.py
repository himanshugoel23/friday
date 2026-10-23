# ruff: noqa: E501
"""Safety gate for the browser layer: code decides, the model never does.

* Domain allow-list: the browser may only open hosts of the site (plus explicit test hosts).
* Never type secrets: card numbers, CVV, PIN, passwords are refused anywhere; a 4-8 digit code goes
  only into the login-OTP field and a phone number only into the phone field.
* No payment clicks: selectors that look like pay / place-order / buy-now are refused outright.
* Irreversible steps (e.g. the checkout click) need an approval ``armed`` by the flow AFTER the
  ``ActionGate`` allowed the matching tool with a user-approved ``Grant`` (see ``approved``).
* Page text found to carry instructions is logged and ignored (``injection``).
``ExtendedGate`` reuses ``gate.py`` for the movie tools so one gate logic covers both use cases.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from friday.connectors.gate import ActionGate, Grant, Verdict
from friday.connectors.sites.errors import DomainNotAllowed, UnsafeAction

_PAY_CLICK = re.compile(
    r"(?i)(?:^|[^a-z])(?:pay[-_ ]?now|pay[-_ ]?(?:btn|button)|place[-_ ]?order|confirm[-_ ]?"
    r"(?:order|payment|pay)|buy[-_ ]?now|upi[-_ ]?pin|make[-_ ]?payment|submit[-_ ]?payment)(?:$|[^a-z])"
)
_SECRET_KEY = re.compile(r"(?i)(cvv|cvc|pin\b|password|passwd|card|expiry|upi[-_ ]?id|vpa)")
OTP_KEYS = frozenset({"otp_input"})
PHONE_KEYS = frozenset({"phone_input"})


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


@dataclass
class SafetyEvent:
    kind: str  # "refused" | "injection" | "domain" | "armed"
    detail: str  # a key / reason / short scrubbed sentence, never a typed value


@dataclass
class SiteSafety:
    allowed_hosts: frozenset[str]
    irreversible_keys: frozenset[str] = frozenset()
    events: list[SafetyEvent] = field(default_factory=list)
    _armed: set[str] = field(default_factory=set)

    # ---- domains
    def host_ok(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return False
        host = parts.hostname.lower()
        return any(host == h or host.endswith("." + h) for h in self.allowed_hosts)

    def check_goto(self, url: str) -> None:
        if not self.host_ok(url):
            self.events.append(SafetyEvent("domain", "blocked host"))
            raise DomainNotAllowed("that address is not on the allow-list for this site")

    # ---- typing
    def check_fill(self, key: str | None, value: str) -> None:
        digits = re.sub(r"[ -]", "", value)
        name = key or "unknown"
        why = None
        if _SECRET_KEY.search(name):
            why = "secret field"
        elif digits.isdigit() and 13 <= len(digits) <= 19 and luhn_ok(digits):
            why = "card-like number"
        elif name in OTP_KEYS:
            if not (digits.isdigit() and 4 <= len(digits) <= 8):
                why = "login code must be 4-8 digits"
        elif name in PHONE_KEYS:
            if not (digits.isdigit() and 10 <= len(digits) <= 13):
                why = "not a phone number"
        elif digits.isdigit() and len(digits) >= 4:
            why = "long number in a non-code field"
        if why:
            self.events.append(SafetyEvent("refused", f"fill {name}: {why}"))
            raise UnsafeAction(f"refused to type into '{name}': {why}")

    # ---- clicking
    def check_click(self, key: str | None, selector: str) -> None:
        if _PAY_CLICK.search(selector) or (key and _PAY_CLICK.search(key)):
            self.events.append(SafetyEvent("refused", f"click {key or 'unknown'}: payment"))
            raise UnsafeAction("Friday never clicks a payment control")
        if key in self.irreversible_keys and key not in self._armed:
            self.events.append(SafetyEvent("refused", f"click {key}: not approved"))
            raise UnsafeAction(f"'{key}' needs the user's approval first")

    @contextmanager
    def approved(self, *keys: str) -> Iterator[None]:
        """Arm irreversible keys for one block. The flow enters this only after the gate said allow."""
        self._armed.update(keys)
        self.events.append(SafetyEvent("armed", ",".join(keys)))
        try:
            yield
        finally:
            self._armed.difference_update(keys)

    # ---- injection
    def note_injection(self, sentences: Iterable[str]) -> None:
        for s in sentences:
            if not any(e.kind == "injection" and e.detail == s for e in self.events):
                self.events.append(SafetyEvent("injection", s))

    @property
    def injection_count(self) -> int:
        return sum(1 for e in self.events if e.kind == "injection")


# ------------------------------------------------------------------ gate for the movie tools
MOVIE_READ_TOOLS = frozenset({"search_shows", "get_seats", "track_booking"})


class ExtendedGate(ActionGate):
    """``ActionGate`` + the movie tools. Movie ``hold_seats`` is checked as ``build_cart`` with the
    show as the 'restaurant' and the seats as one-quantity items, so the same Grant rules apply."""

    def explain(
        self, tool_name: str, args: Mapping[str, Any], grants: Iterable[Grant]
    ) -> tuple[Verdict, str]:
        if tool_name in MOVIE_READ_TOOLS:
            return Verdict.allow, "read-only tool"
        if tool_name == "hold_seats":
            mapped = {**args, "restaurant_id": args.get("show_id"),
                      "items": [{"item_id": s, "qty": 1} for s in args.get("seat_ids", [])]}
            return super().explain("build_cart", mapped, grants)
        if tool_name == "get_payment_handoff" and "show_id" in args:
            mapped = {**args, "restaurant_id": args.get("show_id"),
                      "items": [{"item_id": s, "qty": 1} for s in args.get("seat_ids", [])]}
            return super().explain(tool_name, mapped, grants)
        return super().explain(tool_name, args, grants)
