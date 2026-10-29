# ruff: noqa: E501
"""Plain words for internal status codes (no_result, blocked ...). A user never sees a code.

English and Roman Hinglish. PENDING founder approval (chat wording only, nothing spoken).
"""

from __future__ import annotations

import re

# code -> what happened (en / hinglish). The first clause of a failed-lookup message.
_PRICES = {"en": "I could not read live prices", "hinglish": "Live daam nahi padh paayi"}
_BLOCKED = {"en": "The site blocked us", "hinglish": "Site ne humein rok diya"}
_CHANGED = {"en": "The page looked different than I expected", "hinglish": "Page waisa nahi dikha jaisa socha tha"}
_LOCATION = {"en": "The site did not accept the location", "hinglish": "Site ne location accept nahi ki"}
_DOWN = {"en": "I can't look this up right now", "hinglish": "Abhi yeh check nahi ho pa raha"}
_WRONG = {"en": "Something went wrong on the page", "hinglish": "Page par kuch gadbad ho gayi"}
WHAT: dict[str, dict[str, str]] = {
    "no_result": _PRICES, "not_visible": _PRICES, "price_not_visible": _PRICES,
    "blocked": _BLOCKED, "captcha": _BLOCKED, "denied": _BLOCKED,
    "layout_changed": _CHANGED, "selector_missing": _CHANGED, "changed": _CHANGED,
    "location_rejected": _LOCATION, "pincode_rejected": _LOCATION,
    "timeout": {"en": "It took too long", "hinglish": "Isme bahut der lag gayi"},
    "unavailable": _DOWN, "browser_unavailable": _DOWN,
    "failed": _WRONG, "error": _WRONG,
}  # fmt: skip
DEFAULT_WHAT = {"en": "I could not finish this", "hinglish": "Yeh poora nahi ho paya"}
# what Friday can do next, by code of the next action
NEXT: dict[str, dict[str, str]] = {
    "retry": {"en": "I can try again in a minute", "hinglish": "main ek minute baad dobara try kar sakti hoon"},
    "compare_others": {"en": "I can check other stores instead", "hinglish": "main doosre stores par dekh sakti hoon"},
    "open_site": {"en": "you can open the site directly and I will help from there", "hinglish": "aap site seedha khol lijiye, aage main madad karungi"},
    "paste_details": {"en": "send me the product and your area and I will look again", "hinglish": "product aur area bata dein, main dobara dekhti hoon"},
}
DEFAULT_NEXT = ("retry", "open_site")
_CODE = re.compile(r"\b(?:lookup|status|code)\s*[:=]?\s*[a-z_]+\b|\b[a-z]+(?:_[a-z]+)+\b", re.I)


def _l(lang: str | None) -> str:
    return "en" if lang == "en" else "hinglish"


def _key(code: str | None) -> str:
    return re.sub(r"^(?:lookup|status|code)\s*[:=]?\s*", "", (code or "").strip().lower()).strip()


def what_happened(code: str | None, lang: str | None = "hinglish") -> str:
    return WHAT.get(_key(code), DEFAULT_WHAT)[_l(lang)]


def next_step(actions: list[str] | tuple[str, ...], lang: str | None = "hinglish") -> str:
    """'I can try again in a minute, or you can open the site...' from action codes (max two)."""
    keys = [a for a in actions if a in NEXT][:2] or list(DEFAULT_NEXT)
    parts = [NEXT[k][_l(lang)] for k in keys]
    return (", or " if lang == "en" else ", ya ").join(parts)


def is_code(text: str) -> bool:
    return bool(_CODE.search(text or ""))


def humanize(text: str, lang: str | None = "hinglish") -> str:
    """Replace any internal code in free text by its plain words; unknown codes are dropped."""

    def fix(m: re.Match[str]) -> str:
        key = _key(m.group(0))
        return WHAT[key][_l(lang)].lower() if key in WHAT else ""

    return re.sub(r"\s{2,}", " ", _CODE.sub(fix, text or "")).strip(" :-,.")
