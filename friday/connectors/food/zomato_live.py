"""Locator candidates and page-state rules for the REAL Zomato site: all UNVERIFIED.

!! Nothing here has ever been run against zomato.com. Every candidate is a guess from how
!! consumer sites usually look (visible text / ARIA role / placeholder), tried in order; the
!! explore run logs WHICH candidate name matched (names only) so the lead can tune this file from
!! the run folder. The fake-site markup matches some candidates on purpose (tests).
!! Tuning touches ONLY this file: CANDIDATES, BLOCK_PHRASES, BLOCK_MARKERS, FORBIDDEN_CLICK.

Candidate kinds: ``role`` (ARIA role = value, accessible-name regex = extra), ``text`` (regex),
``placeholder`` (regex), ``css``. ``{query}`` is replaced by the escaped search text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Cand:
    name: str  # logged when this candidate matches (never page content)
    kind: str  # role | text | placeholder | css
    value: str
    extra: str = ""


_LOGIN = r"^\s*(log ?in|sign ?in)\s*$"

CANDIDATES: dict[str, list[Cand]] = {  # UNVERIFIED
    "location_input": [
        Cand("placeholder-location", "placeholder", r"location|locality|area|deliver"),
        Cand("role-combobox-location", "role", "combobox", r"location|area|deliver"),
        Cand("css-input-location", "css", 'input[placeholder*="location" i]'),
    ],
    "location_option": [
        Cand("role-option", "role", "option"),
        Cand("css-role-option", "css", '[role="option"]'),
    ],
    "search_input": [
        Cand("placeholder-search", "placeholder", r"search"),
        Cand("role-searchbox", "role", "searchbox"),
        Cand("css-input-search", "css", "input[type=search]"),
        Cand("role-textbox-search", "role", "textbox", r"search"),
    ],
    "restaurant_result": [
        Cand("link-with-query", "role", "link", "{query}"),
        Cand("text-with-query", "text", "{query}"),
    ],
    "login_open": [
        Cand("button-login", "role", "button", _LOGIN),
        Cand("link-login", "role", "link", _LOGIN),
        Cand("text-login", "text", _LOGIN),
    ],
    "phone_input": [
        Cand("css-tel", "css", "input[type=tel]"),
        Cand("placeholder-phone", "placeholder", r"phone|mobile"),
        Cand("role-textbox-phone", "role", "textbox", r"phone|mobile"),
    ],
    "send_otp": [
        Cand("button-send-otp", "role", "button",
             r"send (one[- ]?time )?(otp|code|password)|get (otp|code)|continue|next|proceed"),
    ],
    "otp_input": [
        Cand("css-one-time-code", "css", "input[autocomplete=one-time-code]"),
        Cand("placeholder-otp", "placeholder", r"otp|code"),
        Cand("css-name-otp", "css", "input[name*=otp i]"),
        Cand("css-numeric", "css", "input[inputmode=numeric]"),
    ],
    "verify_otp": [
        Cand("button-verify", "role", "button", r"verify|submit|log ?in|sign ?in|continue"),
    ],
    "menu_rows": [  # one element per dish; parsed from visible text (parse_menu_rows)
        Cand("testid-menu-item", "css", "[data-testid=menu-item]"),
        Cand("testid-dish", "css", "[data-testid*=dish i]"),
        Cand("class-dish", "css", "[class*=dish i]"),
    ],
    "row_add": [
        Cand("button-add", "role", "button", r"^\s*add\b"),
    ],
    "cart_open": [
        Cand("link-cart", "role", "link", r"cart"),
        Cand("button-cart", "role", "button", r"view cart|cart"),
    ],
    "checkout": [  # goes toward the pay page only; the pay / place-order step is never clicked
        Cand("button-proceed", "role", "button", r"proceed( to (pay|checkout))?|checkout"),
        Cand("link-proceed", "role", "link", r"proceed( to (pay|checkout))?|checkout"),
    ],
    "qr_image": [
        Cand("img-alt-qr", "css", 'img[alt*="qr" i], img[alt*="scan" i], canvas'),
    ],
    "upi_link": [
        Cand("a-upi", "css", 'a[href^="upi://"]'),
    ],
}

# Anything whose visible name matches this is NEVER clicked (no payment, no order, no COD).
FORBIDDEN_CLICK = re.compile(
    r"place\s*order|pay\s*now|pay\s*(?:₹|rs\.?|inr)|confirm\s*order|cash on delivery|\bcod\b|"
    r"make payment|complete order",
    re.I,
)

# Plain-English page states that mean "stop, do not retry, do not evade".
BLOCK_PHRASES: dict[str, tuple[str, ...]] = {
    "bot_challenge": (
        "verify you are human", "verify you are a human", "are you a robot", "not a robot",
        "unusual traffic", "checking your browser", "just a moment", "press & hold",
        "press and hold", "security check", "attention required", "pardon our interruption",
        "request blocked", "automated queries",
    ),
    "access_denied": (
        "access denied", "you don't have permission to access", "forbidden", "403 error",
        "request could not be satisfied",
    ),
}
BLOCK_MARKERS = (  # CSS that only appears on challenge pages
    "iframe[src*=captcha i]", ".g-recaptcha", ".h-captcha", "#challenge-form",
    "iframe[src*=recaptcha i]", "iframe[src*=hcaptcha i]",
)

EXPLANATIONS = {
    "http_error": "The site answered with an error page (HTTP {status}) instead of the page.",
    "access_denied": "The site refused access ('access denied'). It may block this server "
                     "(for example a cloud IP) or automated visitors.",
    "bot_challenge": "The site showed a human-check / bot challenge (CAPTCHA or similar). "
                     "Friday does not try to get around it.",
    "empty_page": "The page came back empty (no visible content).",
}

_PRICE = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_NOISE = {"add", "veg", "non-veg", "non veg", "bestseller", "must try", "customisable",
          "customizable", "serves 1", "serves 2", "new"}


def classify_page(
    *, status: int | None, title: str, text: str, markers: list[str] | None = None
) -> tuple[str, str] | None:
    """(code, plain-English reason) if the page is not a normal page, else None."""
    if status is not None and status >= 400:
        low = f"{title} {text}".lower()
        if status in (401, 403, 429) or any(p in low for p in BLOCK_PHRASES["access_denied"]):
            return "access_denied", EXPLANATIONS["access_denied"] + f" (HTTP {status})"
        return "http_error", EXPLANATIONS["http_error"].format(status=status)
    low = f"{title}\n{text}".lower()
    if markers:
        return "bot_challenge", EXPLANATIONS["bot_challenge"]
    for code, phrases in BLOCK_PHRASES.items():
        if any(p in low for p in phrases):
            return code, EXPLANATIONS[code]
    if len(re.sub(r"\s+", "", text)) < 20:
        return "empty_page", EXPLANATIONS["empty_page"]
    return None


def parse_menu_rows(texts: list[str]) -> list[dict[str, object]]:
    """Dish rows from their visible text: first non-noise line = name, first rupee amount = price.
    Rows without both are skipped (never guessed)."""
    out: list[dict[str, object]] = []
    for raw in texts:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        price: str | None = None
        name: str | None = None
        for ln in lines:
            m = _PRICE.search(ln)
            if m:
                price = price or m.group(1)
                ln = ln[: m.start()].strip()  # text before the price on the same line
            if (name is None and ln and ln.lower() not in _NOISE
                    and not re.fullmatch(r"[\d.,\s]+", ln)):
                name = ln
        if not name or price is None:
            continue
        low = raw.lower()
        veg = bool(re.search(r"\bveg\b", low)) and "non-veg" not in low and "non veg" not in low
        out.append({"name": name[:120], "price_text": price, "veg": veg})
    return out


def phone_regex(local_digits: str) -> re.Pattern[str]:
    """Matches the phone however the page formats it (spaces, dashes, +91, brackets)."""
    sep = r"[\s\-().]*"
    return re.compile(r"(?:\+?\s*91" + sep + r")?" + sep.join(re.escape(d) for d in local_digits))
