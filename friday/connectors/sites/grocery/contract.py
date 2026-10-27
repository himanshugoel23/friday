"""GROCERY use-case models. Money is integer paise; ``Cart`` (from the food contract) validates the
totals, so a bill that does not add up is rejected before it can reach the user."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from friday.connectors.contract import Cart, Paise


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Product(_M):
    item_id: str = Field(min_length=1)
    name: str
    brand: str = ""
    size: str = ""
    price_paise: Paise
    in_stock: bool


class Slot(_M):
    slot_id: str = Field(min_length=1)
    label: str
    fee_paise: Paise = 0
    available: bool = True


class StoreInfo(_M):
    logged_in: bool
    closed: bool = False
    address: str = ""
    eta: str = ""


class CartView(_M):
    """The cart as the site shows it, plus what is re-checked before the irreversible click."""

    cart: Cart
    address: str = ""
    eta: str = ""
    slot_id: str = ""
    substitutions_on: bool = False
