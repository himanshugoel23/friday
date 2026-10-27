# ruff: noqa: E501
"""STAY (hotel + flight) contract. Money is integer paise, INR only; a ``Quote`` checks its totals."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Charge, ConnectorError, Paise


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Option(_M):
    """One search result (a hotel or a flight). ``price_paise`` is the headline price on the card."""

    item_id: str = Field(min_length=1)
    name: str
    price_paise: Paise
    rating: str = ""


class Variant(_M):
    """A bookable choice on the detail page (a room type, or a fare). Everything is INR paise."""

    variant_id: str = Field(min_length=1)
    name: str
    base_paise: Paise
    fees_paise: Paise = 0
    taxes_paise: Paise = 0
    sold_out: bool = False
    free_until: str = ""  # ISO datetime of the free-cancellation deadline; "" = no free cancellation
    nonrefundable: tuple[str, ...] = ()

    @property
    def total_paise(self) -> int:
        return self.base_paise + self.fees_paise + self.taxes_paise


class Policy(_M):
    free_until: str = ""
    nonrefundable: tuple[str, ...] = ()

    def worse_than(self, old: Policy) -> bool:
        """True when the cancellation terms got worse than what the user approved."""
        if old.free_until and not self.free_until:
            return True
        if old.free_until and self.free_until:
            try:
                if datetime.fromisoformat(self.free_until) < datetime.fromisoformat(old.free_until):
                    return True
            except ValueError:
                return True
        return bool(set(self.nonrefundable) - set(old.nonrefundable))


class QuoteLine(_M):
    variant_id: str
    name: str
    price_paise: Paise


class Quote(_M):
    """The booking summary the site shows before the last click. Must add up."""

    lines: list[QuoteLine] = Field(min_length=1)
    fees: list[Charge] = []
    taxes: list[Charge] = []
    total_paise: Paise
    policy: Policy = Policy()

    @model_validator(mode="after")
    def _adds_up(self) -> Quote:
        gross = sum(x.price_paise for x in self.lines)
        gross += sum(c.amount_paise for c in self.fees + self.taxes)
        if gross != self.total_paise:
            raise ValueError("total != lines + fees + taxes")
        return self

    @property
    def subtotal_paise(self) -> int:
        return sum(x.price_paise for x in self.lines)


_FOREIGN = re.compile(r"(?i)([$€£¥]|\b(?:usd|us\$|eur|gbp|aed|sgd|thb|myr|jpy|aud|cad|chf|cny)\b)")
_INR = re.compile(r"(?i)(₹|\brs\b\.?|\binr\b)")


def is_inr(text: str, currency: str = "") -> bool:
    """Positive evidence of rupees, and no sign of another currency. Unknown counts as NOT INR."""
    both = f"{text} {currency}"
    if _FOREIGN.search(both):
        return False
    return bool(_INR.search(both))


class ForeignCurrency(ConnectorError):
    """The site prices in a currency other than INR (or a foreign-card route). Friday hands over."""
