"""The FOOD use-case contract: typed models and the Protocol every site implements.

All money is integer paise. A ``Cart`` is validated by code (line totals, subtotal, grand total
must add up), so a price the page showed wrongly - or a page an attacker tampered with - is
rejected instead of reaching the user. Nothing here can carry a credential: ``PaymentHandoff``
only holds a QR image and/or a credential-free UPI intent link.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal, Protocol
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

Paise = Annotated[int, Field(strict=True, ge=0)]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# The only query keys a UPI intent link may carry (NPCI deep-link spec). Anything else is refused.
UPI_ALLOWED_KEYS = frozenset({"pa", "pn", "am", "cu", "tn", "tr", "mc", "url"})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------ errors


class ConnectorError(Exception):
    """Base class. Messages never contain page text, tokens or codes."""


class LoginRequired(ConnectorError):
    """No usable session and no way to log in (no phone, no OTP channel, or no code in time)."""


class LoginFailed(ConnectorError):
    """The site rejected the login (wrong or expired code)."""


class LayoutChanged(ConnectorError):
    """A selector did not match: the page layout changed. The registry should mark us degraded."""


class CartMismatch(ConnectorError):
    """The cart on the page is not what was asked for."""


class TotalsMismatch(ConnectorError):
    """Prices on the page are inconsistent (parts do not add up to the total)."""


# ------------------------------------------------------------------ money


def rupees_to_paise(text: str) -> int:
    """'₹1,234.50' / 'Rs. 99' / '-₹20.00' -> paise (absolute value). Raises ValueError on junk."""
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not cleaned or cleaned.count(".") > 1 or cleaned in {"."}:
        raise ValueError("not a money amount")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError("not a money amount") from e
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_rupees(paise: int) -> str:
    return f"₹{paise // 100:,}.{paise % 100:02d}"


# ------------------------------------------------------------------ models


class Restaurant(_Model):
    restaurant_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    area: str = ""
    rating: float | None = None


class MenuItem(_Model):
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    price_paise: Paise
    veg: bool


class Menu(_Model):
    restaurant_id: str
    items: list[MenuItem]

    def by_id(self, item_id: str) -> MenuItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)


class ItemQty(_Model):
    item_id: str = Field(min_length=1)
    qty: int = Field(strict=True, ge=1, le=50)


class CartLine(_Model):
    item_id: str
    name: str
    qty: int = Field(strict=True, ge=1)
    unit_price_paise: Paise
    line_total_paise: Paise

    @model_validator(mode="after")
    def _line_adds_up(self) -> CartLine:
        if self.unit_price_paise * self.qty != self.line_total_paise:
            raise ValueError("line total != unit price x qty")
        return self


class Charge(_Model):
    name: str
    amount_paise: Paise


class Cart(_Model):
    restaurant_id: str
    lines: list[CartLine] = Field(min_length=1)
    subtotal_paise: Paise
    fees: list[Charge] = []
    taxes: list[Charge] = []
    discount_paise: Paise = 0
    grand_total_paise: Paise

    @model_validator(mode="after")
    def _totals_add_up(self) -> Cart:
        subtotal = sum(line.line_total_paise for line in self.lines)
        if subtotal != self.subtotal_paise:
            raise ValueError("subtotal != sum of line totals")
        gross = subtotal + sum(f.amount_paise for f in self.fees)
        gross += sum(t.amount_paise for t in self.taxes)
        if self.discount_paise > gross:
            raise ValueError("discount larger than the bill")
        if gross - self.discount_paise != self.grand_total_paise:
            raise ValueError("grand total != subtotal + fees + taxes - discount")
        return self

    def items(self) -> list[ItemQty]:
        return [ItemQty(item_id=line.item_id, qty=line.qty) for line in self.lines]


class PaymentHandoff(_Model):
    """What the user needs to pay in their own UPI app. Never any credential."""

    kind: Literal["qr", "upi_intent"]
    amount_paise: int = Field(strict=True, gt=0)
    merchant: str = Field(min_length=1)
    order_ref: str | None = None
    qr_png: bytes | None = Field(default=None, repr=False)
    upi_link: str | None = None

    @model_validator(mode="after")
    def _safe_handoff(self) -> PaymentHandoff:
        if self.qr_png is None and self.upi_link is None:
            raise ValueError("a handoff needs a QR image or a UPI link")
        if self.qr_png is not None and not self.qr_png.startswith(PNG_MAGIC):
            raise ValueError("QR must be a PNG image")
        if self.upi_link is not None:
            parts = urlsplit(self.upi_link)
            if parts.scheme != "upi" or parts.netloc != "pay":
                raise ValueError("not a upi://pay link")
            if not set(parse_qs(parts.query)) <= UPI_ALLOWED_KEYS:
                raise ValueError("UPI link carries a field that is not allowed")
        return self


class OrderStatus(_Model):
    order_ref: str
    state: str
    eta_minutes: int | None = None


class DeepLinkResult(_Model):
    """Degraded / killed connector: we cannot drive the site, so hand the user the link."""

    url: str
    message: str = "Finish this one in the app"


# ------------------------------------------------------------------ protocol


class FoodConnector(Protocol):
    """Every site (Zomato, Swiggy, ...) implements exactly this for the food use case."""

    async def search_restaurants(self, query: str, area: str) -> list[Restaurant]: ...

    async def get_menu(self, restaurant_id: str) -> Menu: ...

    async def build_cart(self, restaurant_id: str, items: list[ItemQty]) -> Cart: ...

    async def get_payment_handoff(self, cart: Cart) -> PaymentHandoff: ...

    async def track_order(self, order_ref: str) -> OrderStatus: ...
