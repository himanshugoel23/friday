# ruff: noqa: E501
"""The ONE tool surface every site server exposes (same names and schemas on every site, so agents stay generic).

There is deliberately no pay / place-order / confirm-order tool. ``assert_no_payment_tools`` is run when a server is
built and by a test; adding such a name raises.
"""

from __future__ import annotations

from typing import Any

# every status a tool may return in result["status"]
STATUSES = (
    "ok", "needs_location", "location_not_found", "needs_login", "otp_required", "logged_in", "logged_out",
    "blocked", "busy", "rate_limited", "not_found", "unavailable", "error",
)

FORBIDDEN_TOOL_WORDS = ("pay", "order", "purchase", "buy", "confirm", "submit", "card", "upi", "wallet", "refund")

_STR = {"type": "string"}


def _schema(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "set_location": {
        "description": "Set the delivery location (a 6 digit pincode or a place/area name). Prices and stock depend on it. "
                       "Status location_not_found when the site does not serve it.",
        "inputSchema": _schema({"place": _STR, "pincode": {"type": "string", "pattern": "^[1-9][0-9]{5}$"}}),
    },
    "search_products": {
        "description": "Search the site for products. Returns items exactly as the site prints them (title, price text, pack, rating, stock, url, id). Needs a location.",
        "inputSchema": _schema({"query": {"type": "string", "minLength": 1, "maxLength": 80}}, ["query"]),
    },
    "get_product": {
        "description": "Details of one product by the id returned from search_products.",
        "inputSchema": _schema({"id": {"type": "string", "minLength": 1, "maxLength": 120}}, ["id"]),
    },
    "add_to_cart": {
        "description": "Stage a product in the user's cart on the site (nothing is bought).",
        "inputSchema": _schema({"id": {"type": "string", "minLength": 1, "maxLength": 120}, "qty": {"type": "integer", "minimum": 1, "maximum": 10}}, ["id"]),
    },
    "view_cart": {"description": "The current cart: lines, quantities and printed prices.", "inputSchema": _schema()},
    "checkout_preview": {
        "description": "Read the bill (items, fees, total) and report which step was reached. It STOPS BEFORE PAYMENT; the user pays in the app themselves.",
        "inputSchema": _schema(),
    },
    "login_start": {
        "description": "Start a login on the user's own account with their phone number. The site sends a one-time code to the user, who types it on Friday's secure page (never in this tool).",
        "inputSchema": _schema({"phone": {"type": "string", "pattern": "^[0-9+ ]{10,15}$"}}, ["phone"]),
    },
    "login_status": {
        "description": "After login_start: finish the login if the user has entered the code, else say it is still pending.",
        "inputSchema": _schema(),
    },
    "logout": {"description": "Log out on the site and erase the stored session for this user.", "inputSchema": _schema()},
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOL_SPECS)


def assert_no_payment_tools(names: Any) -> None:
    for n in names:
        low = n.lower()
        if n not in TOOL_SPECS or any(w in low for w in FORBIDDEN_TOOL_WORDS):
            raise ValueError(f"tool {n!r} is not allowed: site servers have no pay / place-order surface")
