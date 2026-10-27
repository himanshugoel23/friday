"""SHOPPING use-case contract (Amazon India, Flipkart). Money is integer paise."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.connectors.contract import Charge, Paise
from friday.connectors.sites.train.contract import AddOn


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Product(_M):
    product_id: str = Field(min_length=1)
    title: str
    price_paise: Paise
    rating: float | None = None
    rating_count: int = 0
    seller: str = ""
    fulfilment: str = ""


class Variant(_M):
    variant_id: str = Field(min_length=1)
    label: str  # e.g. "Black, size 9"
    available: bool
    price_paise: Paise


class ProductPage(_M):
    product_id: str
    title: str
    price_paise: Paise
    in_stock: bool
    variants: list[Variant] = []
    return_policy: str = ""
    delivery_fee_paise: Paise = 0
    delivery_estimate: str = ""


class QuoteLine(_M):
    product_id: str
    variant_id: str = ""
    title: str
    qty: int = Field(ge=1)
    unit_paise: Paise
    total_paise: Paise

    @model_validator(mode="after")
    def _line(self) -> QuoteLine:
        if self.unit_paise * self.qty != self.total_paise:
            raise ValueError("line total != unit x qty")
        return self


class Quote(_M):
    lines: list[QuoteLine] = Field(min_length=1)
    fees: list[Charge] = []
    addons: list[AddOn] = []
    total_paise: Paise

    @model_validator(mode="after")
    def _adds_up(self) -> Quote:
        gross = sum(x.total_paise for x in self.lines) + sum(c.amount_paise for c in self.fees)
        gross += sum(a.amount_paise for a in self.addons if a.checked)
        if gross != self.total_paise:
            raise ValueError("total != lines + fees + ticked extras")
        return self

    @property
    def subtotal_paise(self) -> int:
        return sum(x.total_paise for x in self.lines)

    def ticked(self) -> list[AddOn]:
        return [a for a in self.addons if a.checked]


class OrderRow(_M):
    order_id: str
    title: str
    status: str
    amount_paise: Paise = 0
    cancellable: bool = False
