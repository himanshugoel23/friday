"""Shared simulated world - ONE source of fake businesses for every simulator.

The directory simulator (Backend), geocoder simulator (Backend), hotel simulator
(Backend), number verifier simulator (Backend) and the telephony simulator (Voice)
all read the same ``world.json`` so that discovery -> shortlist -> call works end to
end offline: the number the directory returns is a number the telephony simulator
answers, with that business's persona, prices, slots, IVR tree and hold queue.

Owner: loader/schema = Engineering Manager (frozen, additive only);
       world.json data = QA Engineer (everyone may ADD entries; don't edit others').
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from friday.core.models import Language

WORLD_PATH = Path(__file__).with_name("world.json")


class SimIVRNode(BaseModel):
    """One IVR menu. ``options`` maps key -> next node id, or "agent" / "hangup"."""

    prompt: str
    options: dict[str, str] = Field(default_factory=dict)
    asks_for: str | None = None  # "registered mobile number" -> expects an identifier
    asks_otp: bool = False  # simulator demands OTP -> Friday must patch the user in


class SimPersona(BaseModel):
    """How the business behaves on a simulated call."""

    answer: str = "answers"  # answers | busy | no_answer | voicemail | callback_later
    language: Language = Language.HINGLISH  # what the rep speaks (tests language mirroring)
    switches_to: Language | None = None  # rep switches language mid-call
    greeting: str = "Hello?"
    rep_name: str | None = None
    asks_if_ai: bool = False  # tests honest disclosure
    hangs_up_after_turns: int | None = None  # tests HUNG_UP
    prices: dict[str, int] = Field(default_factory=dict)  # item/service -> INR
    max_discount_pct: int = 0  # negotiation room
    slots: list[str] = Field(default_factory=list)
    stock: dict[str, bool] = Field(default_factory=dict)  # A4 stock hunt
    holds_room_hours: int | None = None  # hotels: will hold a room for N hours
    ivr: dict[str, SimIVRNode] = Field(default_factory=dict)  # node id -> node; "root" first
    hold_seconds: int = 0  # queue wait before a human agent answers
    ticket_prefix: str | None = None  # care: issues tickets like "SR12345"
    notes: list[str] = Field(default_factory=list)  # free-form facts the persona knows


class SimReview(BaseModel):
    rating: int
    text: str


class SimBusiness(BaseModel):
    id: str
    name: str
    phone: str  # E.164; unique across the world
    whatsapp: bool = False
    category: str
    city: str
    area: str
    lat: float
    lng: float
    rating: float | None = None
    review_count: int = 0
    reviews: list[SimReview] = Field(default_factory=list)
    hours: dict[str, list[str]] = Field(default_factory=dict)  # "mon": ["10:00-13:00", ...]
    is_customer_care: bool = False
    company: str | None = None  # for care lines: "Airtel"
    official: bool = False  # appears in the official-numbers directory
    scam: bool = False  # number verifier must flag it
    hotel: dict | None = None  # hotel sim: {"rooms": {...}, "pay_at_hotel": true, ...}
    persona: SimPersona = Field(default_factory=SimPersona)


class SimPlace(BaseModel):
    """Geocoder fixtures: free text / maps link -> point."""

    query: str
    formatted_address: str
    city: str
    lat: float
    lng: float


class SimWorld(BaseModel):
    businesses: list[SimBusiness]
    places: list[SimPlace] = Field(default_factory=list)

    def by_phone(self, phone: str) -> SimBusiness | None:
        return next((b for b in self.businesses if b.phone == phone), None)

    def by_id(self, business_id: str) -> SimBusiness | None:
        return next((b for b in self.businesses if b.id == business_id), None)


@lru_cache(maxsize=4)
def load_world(path: str | None = None) -> SimWorld:
    p = Path(path) if path else WORLD_PATH
    return SimWorld.model_validate(json.loads(p.read_text(encoding="utf-8")))
