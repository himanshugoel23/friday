# ruff: noqa: E501
"""Per-site data for the ride adapters: selectors, alternates, paths, vehicle names.

!! Every selector targets the FAKE ride site (sites/fakes/ride_site.py). Real Uber, Ola and Rapido
!! markup is UNVERIFIED (their web booking may not exist at all): record real pages first; real
!! tuning touches only this file. The maps differ per site on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from friday.connectors.catalog import policy_hosts

KEYS = (
    "account_name", "service_closed", "pickup_input", "drop_input", "pickup_point_input",
    "drop_point_input", "point_confirm", "suggestion", "suggestion_pick", "see_prices_button",
    "vehicle_option", "vehicle_pick", "cancel_fee_notice", "quote_vehicle", "quote_pickup",
    "quote_drop", "quote_low", "quote_high", "quote_surge", "quote_cancel_fee",
    "request_ride_button", "ride_state", "driver_name", "driver_vehicle_no",
    "driver_vehicle_model", "driver_rating", "driver_eta", "ride_otp", "share_link",
    "cancel_request", "banner",
)
IRREVERSIBLE = frozenset({"request_ride_button"})  # the one click that needs an approval
VEHICLE_WORDS = {"auto": "auto", "rickshaw": "auto", "bike": "bike", "moto": "bike", "scooter": "bike",
                 "cab": "cab", "car": "cab", "taxi": "cab", "mini": "cab", "sedan": "cab",
                 "premium": "premium", "prime": "premium", "premier": "premium", "luxury": "premium"}


def norm_kind(word: str) -> str:
    return VEHICLE_WORDS.get(re.sub(r"[^a-z]", "", (word or "").lower()), "")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@dataclass(frozen=True)
class RideProfile:
    key: str
    name: str
    selectors: dict[str, str]
    fields: dict[str, dict[str, str]]
    alternates: dict[str, list[str]]
    paths: dict[str, str]
    vehicles: dict[str, str]  # the site's own vehicle name -> auto | bike | cab | premium
    extra_hosts: frozenset[str] = field(default_factory=lambda: frozenset(
        {"fake.invalid", "127.0.0.1", "localhost"}))

    def hosts(self) -> frozenset[str]:
        return frozenset(h.removeprefix("*.") for h in policy_hosts(self.key)) | self.extra_hosts

    def kind_of(self, vehicle_name: str) -> str:
        n = _norm(vehicle_name)
        return next((k for v, k in self.vehicles.items() if _norm(v) == n), "")


def _maps(style: str, attr_id: str, attr_pos: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    def s(name: str) -> str:
        return style.format(n=name.replace("_", "-"))

    sel = {k: s(k) for k in KEYS}
    sel["vehicle_pick"] = s("vehicle-pick") + f"[{attr_id}='{{vehicle_id}}']"
    sel["suggestion_pick"] = s("suggestion-pick") + f"[{attr_pos}='{{n}}']"
    fields = {
        "vehicle_option": {"vehicle_id": "@" + attr_id, "name": s("vehicle-name"), "eta": s("vehicle-eta"),
                           "low": s("fare-low"), "high": s("fare-high"), "surge": s("surge"),
                           "available": "@data-available"},
        "suggestion": {"label": s("suggestion-label"), "n": "@" + attr_pos},
        "share_link": {"href": "@href"},
    }
    return sel, fields


_UBER = _maps("[data-testid=ub-{n}]", "data-vid", "data-idx")
_OLA = _maps("[data-ola='{n}']", "data-cabid", "data-row")
_RAPIDO = _maps(".rp-{n}", "data-ride-type", "data-pos")

PROFILES: dict[str, RideProfile] = {
    "uber": RideProfile(
        "uber", "Uber", *_UBER,
        alternates={"request_ride_button": ["[data-testid=ub-confirm-ride]"]},
        paths={"home": "/", "ride": "/looking"},
        vehicles={"Uber Auto": "auto", "Uber Moto": "bike", "Uber Go": "cab", "Uber Premier": "premium"}),
    "ola": RideProfile(
        "ola", "Ola", *_OLA,
        alternates={"request_ride_button": ["[data-ola='book-now-step']"]},
        paths={"home": "/", "ride": "/book/ride"},
        vehicles={"Ola Auto": "auto", "Ola Bike": "bike", "Ola Mini": "cab", "Ola Prime": "premium"}),
    "rapido": RideProfile(
        "rapido", "Rapido", *_RAPIDO,
        alternates={"request_ride_button": [".rp-go-captain"]},
        paths={"home": "/", "ride": "/ride/new"},
        vehicles={"Auto": "auto", "Bike": "bike", "Cab Economy": "cab"}),  # no premium on Rapido
}
