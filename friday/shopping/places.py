# ruff: noqa: E501
"""Delivery place: Home / PG (Office only when the user asked for it), read from the saved places.

The pincode comes from the saved address; it is never asked for while a saved place exists. With no saved
place the user is asked ONE question and the answer is saved as a normal Place (the same store that
"what do you remember" lists and "delete everything" erases)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from friday.core.models import Place, PlaceSource
from friday.planner import signals as sg

KINDS = ("home", "pg", "office")
_WORDS = {
    "home": ("home", "ghar", "house", "flat", "apartment"),
    "pg": ("pg", "p.g", "paying guest", "hostel"),
    "office": ("office", "work", "workplace", "daftar", "dafter"),
}  # fmt: skip
_CANON = {"home": "Home", "pg": "PG", "office": "Office"}


class DeliveryPlace(BaseModel):
    kind: str  # home | pg | office
    place_id: str | None = None
    pincode: str | None = None
    area: str | None = None

    @property
    def where(self) -> str:
        return self.pincode or self.area or ""


def kind_of(text: str) -> str | None:
    low = (text or "").lower()
    for kind in ("pg", "office", "home"):  # pg first: "pg near home" is a PG
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) for w in _WORDS[kind]):
            return kind
    return None


def _kind_of_place(p: Place) -> str | None:
    return kind_of(" ".join([p.label, *p.aliases]))


def _to_delivery(p: Place, kind: str) -> DeliveryPlace:
    addr = " ".join(x for x in (p.formatted_address, p.address_text) if x)
    pin = sg.pincode_in(addr)
    area = None if pin else ((p.address_text or p.formatted_address or "")[:60] or p.city)
    return DeliveryPlace(kind=kind, place_id=p.id, pincode=pin, area=area)


async def saved_places(repos: Any, user_id: str, *, include_office: bool) -> list[DeliveryPlace]:
    """Saved Home / PG (and Office only if asked), one each, with the pincode read from the address.
    A place whose label IS the word ("Home", "PG") beats one that only contains it ("Mom's home")."""
    best: dict[str, tuple[int, Place]] = {}
    for p in await repos.places.list_for_owner(user_id):
        if p.ephemeral or p.person_id:  # one-off pins and other people's places are never delivery places
            continue
        kind = _kind_of_place(p)
        if kind is None or (kind == "office" and not include_office):
            continue
        rank = 0 if p.label.strip().lower() in _WORDS[kind] else 1
        if kind not in best or rank < best[kind][0]:
            best[kind] = (rank, p)
    return [_to_delivery(best[k][1], k) for k in KINDS if k in best]


def parse_answer(text: str) -> DeliveryPlace | None:
    """'PG, Koramangala 560034' / 'ghar 110001' / 'Indiranagar' -> a place; None when nothing usable."""
    t = (text or "").strip()
    pin = sg.pincode_in(t)
    kind = kind_of(t) or "home"
    area = re.sub(r"(?<!\d)\d{6}(?!\d)", " ", t)
    for words in _WORDS.values():
        for w in words:
            area = re.sub(rf"(?<![a-z]){re.escape(w)}(?![a-z])", " ", area, flags=re.I)
    area = re.sub(r"\b(is|hai|mera|meri|my|the|at|in|me|mein|par|pe|ka|ki|ke|near|pincode|area|ye|yeh|it)\b", " ", area, flags=re.I)
    area = re.sub(r"[^\w\s,.-]", " ", area)
    area = re.sub(r"\s+", " ", area).strip(" ,.-")
    if not pin and (len(area) < 3 or len(area.split()) > 8 or not re.search(r"[a-zA-Z]", area)):
        return None
    return DeliveryPlace(kind=kind, pincode=pin, area=area[:60] or None)


async def save_place(repos: Any, user_id: str, place: DeliveryPlace) -> DeliveryPlace:
    """Save (or update) the user's Home / PG / Office. The address text holds the pincode or area the user gave."""
    label = _CANON[place.kind]
    existing = next(
        (p for p in await repos.places.list_for_owner(user_id) if _kind_of_place(p) == place.kind and not p.person_id),
        None,
    )
    address = " ".join(x for x in (place.area, place.pincode) if x)
    p = existing or Place(owner_user_id=user_id, label=label)
    p.address_text = address
    p.formatted_address = None
    p.source = PlaceSource.TYPED
    if place.kind == "pg" and "pg" not in [a.lower() for a in p.aliases] and p.label.lower() != "pg":
        p.aliases = [*p.aliases, "pg"]
    saved = await repos.places.upsert(p)
    return place.model_copy(update={"place_id": saved.id})
