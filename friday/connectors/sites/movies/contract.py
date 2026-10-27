"""MOVIE use-case contract. Money is integer paise; a ``SeatHold`` checks its totals."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Charge, Paise, PaymentHandoff


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Show(_M):
    show_id: str = Field(min_length=1)
    movie: str
    cinema: str
    area: str = ""
    starts_at: str  # "19:00"
    minutes: int = Field(ge=0, lt=1440)  # minutes after midnight, for matching "7 pm"
    from_paise: Paise = 0


class Seat(_M):
    seat_id: str = Field(min_length=1)
    label: str
    price_paise: Paise
    available: bool


class SeatLine(_M):
    seat_id: str
    label: str
    price_paise: Paise


class SeatHold(_M):
    show_id: str
    lines: list[SeatLine] = Field(min_length=1)
    subtotal_paise: Paise
    fees: list[Charge] = []
    taxes: list[Charge] = []
    total_paise: Paise
    expires_in_s: int = 600

    @model_validator(mode="after")
    def _adds_up(self) -> SeatHold:
        if sum(line.price_paise for line in self.lines) != self.subtotal_paise:
            raise ValueError("subtotal != sum of seat prices")
        gross = self.subtotal_paise + sum(c.amount_paise for c in self.fees + self.taxes)
        if gross != self.total_paise:
            raise ValueError("total != subtotal + fees + taxes")
        return self

    def seat_ids(self) -> list[str]:
        return [line.seat_id for line in self.lines]


class MovieConnector(Protocol):
    async def search_shows(self, query: str, area: str) -> list[Show]: ...

    async def get_seats(self, show_id: str) -> list[Seat]: ...

    async def hold_seats(self, show_id: str, seat_ids: list[str]) -> SeatHold: ...

    async def get_payment_handoff(self, hold: SeatHold) -> PaymentHandoff: ...

    async def track_booking(self, ref: str) -> str: ...
