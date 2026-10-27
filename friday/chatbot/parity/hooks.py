# ruff: noqa: E501
"""The service-side glue: one function that turns a text message into a parity reply or None.

Called from ``ChatbotService.pre`` only when at least one FRIDAY_PARITY_* switch is on. Pure apart
from the injected invite ledger.
"""

from __future__ import annotations

import re

from friday.chatbot.parity import copy, pricing, rides
from friday.chatbot.parity.invites import InviteLedger

_I = re.IGNORECASE
INVITES = re.compile(r"^\W*(?:my\s+)?invites?\W*$|^\W*(?:mere\s+)?invites?\s+(?:kitne|kitni|left|bache)\W*$", _I)
_RIDE = re.compile(r"\b(ola|rapido|uber)\b.*\b(?:book|ride|cab|bike|taxi|link)\b|\b(?:book|ride|cab|bike|taxi)\b.*\b(ola|rapido|uber)\b", _I)


def text_reply(settings, ledger: InviteLedger, user_id: str, text: str, lang: str) -> str | None:
    t = " ".join((text or "").split())
    if settings.parity_inr_only and (refusal := pricing.check_route(t, lang)):
        return refusal
    if settings.parity_invites and INVITES.match(t):
        link = ledger.issue(user_id, settings.public_base_url)
        if link is None:
            return copy.line("invite_none", lang)
        return copy.line(
            "invite_status", lang, left=str(ledger.left(user_id)), total=str(ledger.quota), link=link
        )
    if settings.parity_ride_links and (m := _RIDE.search(t)):
        app = (m.group(1) or m.group(2)).lower()
        if app != "uber":  # Uber needs pickup/drop coordinates from a flow; never guessed here
            return rides.ride_reply(app, None, None, lang)
    return None
