"""Ride hand-off: a link the USER opens to book a cab. Friday books nothing, pays nothing and never
holds a ride-app login. The link format follows a widely used universal-link shape and is UNVERIFIED
against any provider's current terms (docs/TRIP_TIMELINE.md); the provider is not chosen.
"""

from __future__ import annotations

from urllib.parse import urlencode

from friday.docunderstand.safety import clean_text

RIDE_LINK_BASE = (
    "https://m.uber.com/ul/"  # provider-neutral hand-off; swap when a provider is chosen
)


def ride_link(pickup: str, drop: str | None = None) -> str:
    """A link pre-filled with the pickup (the user's own words) and, if known, the drop."""
    q = {"action": "setPickup", "pickup[formatted_address]": clean_text(pickup, 120)}
    if drop:
        q["dropoff[formatted_address]"] = clean_text(drop, 120)
    return f"{RIDE_LINK_BASE}?{urlencode(q)}"
