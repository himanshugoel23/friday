# ruff: noqa: E501
"""User-facing lines specific to SWIGGY. PENDING founder approval (hear before change).

Swiggy reuses the food lines of sites/copy.py (questions, approve_food, reapprove, payment_ready,
summary_food, out_of_stock, no_match, blocked ...). Only what is new is here: the extras notes.
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

LANGS = ("en", "hi")
APPROVAL_PENDING = True

COPY: dict[str, dict[str, str]] = {
    "addon_stuck": {"en": "{site} kept an extra ticked ({names}) and I could not remove it, so it is in the new total.",
                    "hi": "{site} ne ek extra ({names}) tick rakha aur main use hata nahi paayi, isliye naye total mein hai."},
    "note_addon_unticked": {"en": " I unticked pre-selected extras (membership trial, tip).",
                            "hi": " Pehle se tick kiye extras (membership trial, tip) maine hata diye."},
}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))
