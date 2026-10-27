# ruff: noqa: E501
"""BUS use-case contract. Money is integer paise; a ``SeatHold`` checks its totals."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Charge, ConnectorError, Paise


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BusOption(_M):
    item_id: str = Field(min_length=1)
    operator: str
    bus_type: str  # normalised: "sleeper ac", "seater non ac" ...
    depart: str
    price_paise: Paise


class Seat(_M):
    seat_id: str = Field(min_length=1)
    label: str
    kind: str  # sleeper | seater
    price_paise: Paise
    available: bool


class Point(_M):
    point_id: str = Field(min_length=1)
    name: str
    time: str = ""


class PolicyRow(_M):
    window: str
    refund_pct: str  # "90" ... "0"


class SeatLine(_M):
    seat_id: str
    label: str
    price_paise: Paise


class SeatHold(_M):
    lines: list[SeatLine] = Field(min_length=1)
    fees: list[Charge] = []
    taxes: list[Charge] = []
    subtotal_paise: Paise
    total_paise: Paise
    seconds_left: int = 0

    @model_validator(mode="after")
    def _adds_up(self) -> SeatHold:
        if sum(x.price_paise for x in self.lines) != self.subtotal_paise:
            raise ValueError("subtotal != sum of seat prices")
        gross = self.subtotal_paise + sum(c.amount_paise for c in self.fees + self.taxes)
        if gross != self.total_paise:
            raise ValueError("total != subtotal + fees + taxes")
        return self


class HoldExpired(ConnectorError):
    """The site released the seats before the user finished (the hold is short on purpose)."""
