# ruff: noqa: E501
"""TRAIN use-case contract. Money is integer paise; a ``FareQuote`` checks its own totals.

Passenger details are NEVER defaulted: ``parse_passengers`` accepts only what the user said and
returns the first missing detail so the flow can ask for it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Charge, Paise

CLASSES = ("SL", "3A", "2A", "1A", "CC", "EC")
QUOTAS = ("general", "tatkal")
Status = Literal["confirmed", "waitlist", "rac", "regret", "unknown"]
BERTHS = {"lower": "Lower", "middle": "Middle", "upper": "Upper", "side lower": "Side Lower",
          "side upper": "Side Upper", "window": "Window", "aisle": "Aisle",
          "no preference": "No preference", "no choice": "No preference", "any": "No preference"}
GENDERS = {"m": "M", "male": "M", "man": "M", "f": "F", "female": "F", "woman": "F",
           "t": "T", "transgender": "T", "other": "T"}
MAX_PASSENGERS = 6


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrainOption(_M):
    train_no: str = Field(min_length=1)
    name: str
    depart: str
    arrive: str
    cls: str
    fare_paise: Paise
    status: Status
    availability: str = ""  # the site's own words, e.g. "AVAILABLE-0042", "GNWL12", "RAC 5"

    @property
    def bookable(self) -> bool:
        return self.status in {"confirmed", "waitlist", "rac"}


class Passenger(_M):
    name: str = Field(min_length=2, max_length=40)
    age: int = Field(ge=1, le=120)
    gender: Literal["M", "F", "T"]
    berth: str


class FareLine(_M):
    name: str
    amount_paise: Paise


class AddOn(_M):
    addon_id: str
    label: str
    amount_paise: Paise
    checked: bool


class FareQuote(_M):
    fares: list[FareLine] = Field(min_length=1)
    fees: list[Charge] = []
    addons: list[AddOn] = []
    total_paise: Paise

    @model_validator(mode="after")
    def _adds_up(self) -> FareQuote:
        gross = sum(f.amount_paise for f in self.fares) + sum(c.amount_paise for c in self.fees)
        gross += sum(a.amount_paise for a in self.addons if a.checked)
        if gross != self.total_paise:
            raise ValueError("total != fares + fees + ticked extras")
        return self

    @property
    def fare_paise(self) -> int:
        return sum(f.amount_paise for f in self.fares)

    def ticked(self) -> list[AddOn]:
        return [a for a in self.addons if a.checked]


def parse_passengers(raw: Any) -> tuple[list[Passenger], str | None]:
    """(passengers, None) when complete, else ([], the first missing detail, human words).
    Nothing is guessed: a missing age, gender or berth is asked, never filled in."""
    if not isinstance(raw, list) or not raw:
        return [], "passenger details (name, age, gender, berth preference)"
    if len(raw) > MAX_PASSENGERS:
        return [], f"at most {MAX_PASSENGERS} passengers"
    out: list[Passenger] = []
    for i, r in enumerate(raw, 1):
        r = r if isinstance(r, dict) else {}
        who = f"passenger {i}"
        name = " ".join(str(r.get("name") or "").split())
        if len(name) < 2 or any(c.isdigit() for c in name):
            return [], f"{who}: full name"
        try:
            age = int(r.get("age"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return [], f"{who}: age"
        if not 1 <= age <= 120:
            return [], f"{who}: age"
        gender = GENDERS.get(str(r.get("gender") or "").strip().lower())
        if gender is None:
            return [], f"{who}: gender"
        berth = BERTHS.get(str(r.get("berth") or "").strip().lower())
        if berth is None:
            return [], f"{who}: berth preference (lower, middle, upper, side lower, side upper or no preference)"
        out.append(Passenger(name=name, age=age, gender=gender, berth=berth))  # type: ignore[arg-type]
    return out, None
