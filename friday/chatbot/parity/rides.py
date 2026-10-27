# ruff: noqa: E501
"""Item 6: ride deep links. Only the Uber format is verified; Ola and Rapido get no link.

Uber mobile web deep link (needs no login, opens the app or m.uber.com):
    https://m.uber.com/looking?pickup=<urlencoded JSON>&drop[0]=<urlencoded JSON>
where each JSON is ``{"addressLine1": ..., "latitude": ..., "longitude": ...}``.
The format was confirmed in the founder's Instinct chat (docs/INSTINCT_CHAT_3.md); it is NOT
verified against a live Uber app here, so it is covered by unit tests only (docs/INSTINCT_PARITY.md).
Never send a link whose format is not listed in VERIFIED_FORMATS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

from friday.chatbot.parity import copy

UBER_BASE = "https://m.uber.com/looking"
VERIFIED_FORMATS = frozenset({"uber"})


@dataclass(frozen=True)
class Place:
    address: str
    lat: float
    lng: float

    def valid(self) -> bool:
        return bool(self.address.strip()) and -90 <= self.lat <= 90 and -180 <= self.lng <= 180


def _place_json(p: Place) -> str:
    obj = {"addressLine1": p.address.strip(), "latitude": round(p.lat, 6), "longitude": round(p.lng, 6)}
    return quote(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), safe="")


def uber_link(pickup: Place, drop: Place) -> str | None:
    if not (pickup.valid() and drop.valid()):
        return None
    return f"{UBER_BASE}?pickup={_place_json(pickup)}&drop%5B0%5D={_place_json(drop)}"


def ride_reply(app: str, pickup: Place | None, drop: Place | None, lang: str = "hinglish") -> str:
    """The message for a ride request on ``app`` (uber / ola / rapido / anything else)."""
    key = app.strip().lower()
    if key in VERIFIED_FORMATS and key == "uber" and pickup and drop:
        link = uber_link(pickup, drop)
        if link:
            return copy.line("ride_uber", lang, link=link)
    return copy.line("ride_no_link", lang, app=app.strip().title() or "App")
