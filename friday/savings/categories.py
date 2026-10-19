"""Free-text purchase -> (amount, category, merchant), with deterministic keyword tables.

    parse_purchase("Zomato pe 640")            -> food_delivery / zomato / Rs 640
    parse_purchase("petrol 2000")              -> fuel / Rs 2,000
    parse_purchase("Amazon 12000 ka phone")    -> electronics / amazon / Rs 12,000
    parse_purchase("kuch kharidna hai")        -> ask: which category / how much

No model is involved. When the text is not clear enough the result carries ``ask`` (a question
key for friday/savings/copy.py) instead of a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from friday.savings.money import find_amounts

# Category keys used by card rules ("all" is the catch-all base rate in the rules table).
CATEGORY_KEYS: tuple[str, ...] = (
    "food_delivery",
    "dining",
    "grocery",
    "fuel",
    "travel",
    "cab",
    "online_shopping",
    "electronics",
    "bills_utilities",
    "mobile_recharge",
    "entertainment",
    "pharmacy",
    "rent",
    "wallet_load",
    "insurance",
    "education",
    "other",
)
ALL = "all"
RULE_CATEGORY_KEYS = frozenset({*CATEGORY_KEYS, ALL})

# merchant key -> (category, aliases). Aliases are matched on word boundaries, lowercase.
MERCHANTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "zomato": ("food_delivery", ("zomato", "zomatto")),
    "swiggy": ("food_delivery", ("swiggy", "swigy")),
    "eatsure": ("food_delivery", ("eatsure",)),
    "dominos": ("food_delivery", ("dominos", "domino's", "domino")),
    "blinkit": ("grocery", ("blinkit", "grofers")),
    "zepto": ("grocery", ("zepto",)),
    "instamart": ("grocery", ("instamart", "swiggy instamart")),
    "bigbasket": ("grocery", ("bigbasket", "big basket")),
    "dmart": ("grocery", ("dmart", "d mart", "d-mart")),
    "jiomart": ("grocery", ("jiomart", "jio mart")),
    "amazon": ("online_shopping", ("amazon", "amzn")),
    "flipkart": ("online_shopping", ("flipkart", "flipcart")),
    "myntra": ("online_shopping", ("myntra",)),
    "ajio": ("online_shopping", ("ajio",)),
    "nykaa": ("online_shopping", ("nykaa",)),
    "meesho": ("online_shopping", ("meesho",)),
    "croma": ("electronics", ("croma",)),
    "reliance digital": ("electronics", ("reliance digital",)),
    "uber": ("cab", ("uber",)),
    "ola": ("cab", ("ola cabs", "ola")),
    "rapido": ("cab", ("rapido",)),
    "irctc": ("travel", ("irctc",)),
    "makemytrip": ("travel", ("makemytrip", "make my trip", "mmt")),
    "goibibo": ("travel", ("goibibo",)),
    "cleartrip": ("travel", ("cleartrip",)),
    "indigo": ("travel", ("indigo",)),
    "netflix": ("entertainment", ("netflix",)),
    "spotify": ("entertainment", ("spotify",)),
    "hotstar": ("entertainment", ("hotstar", "jiohotstar")),
    "bookmyshow": ("entertainment", ("bookmyshow", "book my show")),
    "pharmeasy": ("pharmacy", ("pharmeasy",)),
    "1mg": ("pharmacy", ("1mg", "tata 1mg")),
    "apollo pharmacy": ("pharmacy", ("apollo pharmacy",)),
    "indian oil": ("fuel", ("indian oil", "iocl", "indianoil")),
    "bharat petroleum": ("fuel", ("bpcl", "bharat petroleum")),
    "hp petrol": ("fuel", ("hpcl", "hp petrol")),
    "shell": ("fuel", ("shell",)),
    "paytm wallet": ("wallet_load", ("paytm wallet",)),
}

# category -> keywords (single words or short phrases, lowercase, Hinglish and English)
KEYWORDS: dict[str, tuple[str, ...]] = {
    "food_delivery": ("food delivery", "khana order", "food order", "biryani order", "pizza order"),
    "dining": (
        "restaurant", "restaurants", "dinner", "lunch", "cafe", "dine in", "dine-in", "dhaba",
        "hotel mein khana", "bahar khana", "dinner out", "date night",
    ),
    "grocery": (
        "grocery", "groceries", "kirana", "sabzi", "sabji", "vegetables", "ration", "atta",
        "doodh", "milk", "supermarket", "fruits",
    ),
    "fuel": (
        "petrol", "diesel", "fuel", "cng", "petrol pump", "gas station", "tel bharwana",
        "पेट्रोल", "डीजल",
    ),
    "travel": (
        "flight", "flights", "train", "ticket", "tickets", "hotel", "hotels", "bus ticket",
        "holiday", "trip", "vacation", "flight ticket", "air ticket",
    ),
    "cab": ("cab", "taxi", "auto", "ride", "rickshaw"),
    "online_shopping": ("shopping", "kapde", "clothes", "shoes", "online order", "sale"),
    "electronics": (
        "phone", "mobile phone", "smartphone", "laptop", "tv", "television", "fridge",
        "refrigerator", "washing machine", "ac", "earbuds", "headphones", "tablet", "iphone",
        "watch", "camera", "appliance", "microwave",
    ),
    "bills_utilities": (
        "bill", "bijli", "electricity", "gas bill", "water bill", "broadband", "wifi", "internet",
        "dth", "piped gas", "maintenance", "utility", "utilities",
    ),
    "mobile_recharge": ("recharge", "prepaid", "postpaid", "mobile bill", "data pack"),
    "entertainment": ("movie", "movies", "film", "subscription", "ott", "concert", "show tickets"),
    "pharmacy": ("medicine", "medicines", "dawai", "dawa", "pharmacy", "chemist", "medical store"),
    "rent": ("rent", "kiraya", "house rent", "flat rent", "pg rent"),
    "wallet_load": ("wallet load", "wallet top up", "wallet topup", "add money", "gift card"),
    "insurance": ("insurance", "premium", "lic", "policy"),
    "education": ("school fees", "tuition", "college fees", "fees", "course", "exam fee"),
}

# a merchant's default category is overridden by these item categories ("Amazon ka phone")
ITEM_OVERRIDES = frozenset({"electronics"})

# words that are ambiguous alone: "ac" / "tv" need a word boundary (handled by the regex)
_WORD = r"(?<![a-z0-9]){}(?![a-z0-9])"


def _compile(words: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(words, key=len, reverse=True)
    return re.compile("|".join(_WORD.format(re.escape(w)) for w in ordered), re.IGNORECASE)


_MERCHANT_RE = {
    key: _compile(aliases) for key, (_cat, aliases) in MERCHANTS.items()
}
_KEYWORD_RE = {cat: _compile(words) for cat, words in KEYWORDS.items()}


@dataclass(frozen=True)
class ParsedPurchase:
    amount_paise: int | None
    category: str | None
    merchant: str | None
    ask: str | None = None  # "amount" | "category" | "which_amount" | "which_category"
    options: tuple[str, ...] = field(default_factory=tuple)  # category choices for the question

    @property
    def complete(self) -> bool:
        return self.ask is None and self.amount_paise is not None and self.category is not None


def find_merchant(text: str) -> str | None:
    """The merchant whose longest alias occurs in the text (ties broken by the table order)."""
    best: tuple[int, str] | None = None
    for key, rx in _MERCHANT_RE.items():
        for m in rx.finditer(text):
            size = len(m.group(0))
            if best is None or size > best[0]:
                best = (size, key)
    return best[1] if best else None


def find_keyword_categories(text: str) -> list[str]:
    return [cat for cat, rx in _KEYWORD_RE.items() if rx.search(text)]


def _pick_amount(text: str) -> tuple[int | None, bool]:
    """(paise, ambiguous). A single amount, or the only one with a currency marker."""
    hits = find_amounts(text)
    if not hits:
        return None, False
    if len(hits) == 1:
        return hits[0].paise, False
    marked = [h for h in hits if h.marked]
    if len(marked) == 1:
        return marked[0].paise, False
    if len({h.paise for h in hits}) == 1:
        return hits[0].paise, False
    return None, True


def parse_purchase(text: str) -> ParsedPurchase:
    """Deterministic parse of a short purchase message. Asks instead of guessing."""
    low = text.lower()
    amount, amount_ambiguous = _pick_amount(low)
    merchant = find_merchant(low)
    kw_cats = find_keyword_categories(low)
    merchant_cat = MERCHANTS[merchant][0] if merchant else None

    category: str | None = None
    options: tuple[str, ...] = ()
    if merchant_cat:
        overrides = [c for c in kw_cats if c in ITEM_OVERRIDES]
        category = overrides[0] if overrides and merchant_cat == "online_shopping" else merchant_cat
        if category == "online_shopping" and not overrides:
            # "Amazon 500" - keywords such as "grocery" could still refine it
            others = [c for c in kw_cats if c != "online_shopping"]
            if len(others) == 1:
                category = others[0]
    elif len(kw_cats) == 1:
        category = kw_cats[0]
    elif len(kw_cats) > 1:
        options = tuple(sorted(kw_cats))

    if amount_ambiguous:
        return ParsedPurchase(None, category, merchant, ask="which_amount")
    if amount is None:
        return ParsedPurchase(None, category, merchant, ask="amount", options=options)
    if category is None:
        return ParsedPurchase(
            amount, None, merchant, ask="which_category" if options else "category", options=options
        )
    return ParsedPurchase(amount, category, merchant)
