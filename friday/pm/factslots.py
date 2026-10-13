# ruff: noqa: E501
"""Fact slots: what the project manager asks the user BEFORE any call (docs/LEARNING_AND_BUILD_PLAN.md).

The names are the fact names of ``friday.vendors.facts`` so the answers reach the playbook inputs
unchanged. Everything here is rules (no model): silent derivations from the user's own words, the
two gate questions (makeup at the venue? exchange?), skip words for optional questions, and the
export of the collected slots as playbook facts. Nothing is ever invented: a fact the user did not
give stays unset.
"""

from __future__ import annotations

import re
from typing import Any

from friday.vendors.facts import PLAYBOOK_INPUT_NAMES, clean_fact

# category -> the fact slot that holds the date (or pickup time) of the request
DATE_SLOT = {
    "restaurant_table": "date", "packers_movers": "date", "florist_gift": "date",
    "hotel_stay": "checkin_date", "event_services": "event_date", "wedding_vendors": "event_date",
    "banquet_hall": "event_date", "salon": "event_date", "pg_rental": "move_in_date",
    "cab_travel": "pickup_time",
}
# category -> slot that holds a head count found in the request ("50 guests", "4 log")
COUNT_SLOT = {
    "restaurant_table": "people_count", "salon": "people_count", "cab_travel": "people_count",
    "hotel_stay": "guests", "event_services": "guests", "wedding_vendors": "guests",
    "banquet_hall": "guests",
}

_COUNT = re.compile(
    r"\b(\d{1,4})\s*(?:guests?|mehmaan|mehman|log|logon|logo|people|persons?|members?|pax|"
    r"aadmi|admi)\b", re.I)
_ADVANCE = re.compile(
    r"\b(advance|booking amount|token amount|token|deposit|booking fee|booking charges)\b", re.I)
_MAKEUP = re.compile(
    r"makeup|make up|make-up|bridal|dulhan|dulhin|mehendi|mehndi|haldi|sangeet|engagement|"
    r"reception|party look", re.I)
_VENUE = re.compile(
    r"venue|ghar par|ghar pe|ghar aa|home visit|at home|at my place|aayegi|aaye|aayenge|ayegi|"
    r"aa sakti|aa sakte|come to|hotel mein|banquet|hall mein|location par|location pe|wahan aakar",
    re.I)
_PARLOUR = re.compile(
    r"parlou?r|salon|saloon|studio|jaungi|jaunga|jaaungi|jaaunga|jayenge|jaenge|jana hai|"
    r"jaungi|jaoongi|go to|visit the|aap ke yahan|aapke yahan|shop par", re.I)
_EXCH_NO = re.compile(r"no exchange|exchange nahi|without exchange|bina exchange|exchange nhi", re.I)
_EXCH_YES = re.compile(r"exchange|trade[- ]?in|purana phone|old phone|puraana phone", re.I)
_SKIP = re.compile(
    r"^\s*(skip|nahi|nahin|nhi|no|none|nope|na|koi nahi|pata nahi|not sure|abhi nahi|not now|"
    r"dont know|don't know|ignore|no idea|-+)\s*[.!]?\s*$", re.I)

GATE_AT_VENUE = "at_venue"
GATE_EXCHANGE = "exchange"


def is_skip(text: str) -> bool:
    return bool(_SKIP.match(text or ""))


def parse_venue_choice(text: str) -> bool | None:
    """True = the person comes to the venue; False = the user goes to the parlour."""
    v, p = bool(_VENUE.search(text)), bool(_PARLOUR.search(text))
    if v == p:
        return None
    return v


def derive_from_text(category: str | None, text: str, slots: dict[str, Any]) -> dict[str, Any]:
    """Silent facts read from the user's FIRST message (setdefault-style: never overrides)."""
    out: dict[str, Any] = {}
    if _ADVANCE.search(text):
        out["q_ask_advance"] = "yes"  # asked about ONLY because the user's own words mention it
    if category in COUNT_SLOT and (m := _COUNT.search(text)):
        out[COUNT_SLOT[category]] = m.group(1)
    if category == "salon":
        if not _MAKEUP.search(text):
            out[GATE_AT_VENUE] = False  # a plain haircut: nothing to ask about a venue
        elif (v := parse_venue_choice(text)) is not None:
            out[GATE_AT_VENUE] = v
    if category == "electronics_dealer":
        if _EXCH_NO.search(text):
            out[GATE_EXCHANGE] = False
        elif _EXCH_YES.search(text):
            out[GATE_EXCHANGE] = True
    return {k: v for k, v in out.items() if k not in slots}


def derive(category: str | None, slots: dict[str, Any], assumed: dict[str, Any] | None = None) -> None:
    """Fill facts that other slots already answer (idempotent, in place)."""
    assumed = assumed or {}
    ds = DATE_SLOT.get(category or "")
    if ds and ds not in slots and slots.get("when") and "when" not in assumed:
        slots[ds] = slots["when"]
    if (category == "restaurant_table" and "time" not in slots and slots.get("when")
            and "when" not in assumed
            and (m := re.search(r"\d{1,2}(?::\d{2})?\s*(?:baje|am|pm)\b", str(slots["when"]), re.I))):
        slots["time"] = m.group(0)
    if category == "packers_movers" and "from_place" not in slots and slots.get("where"):
        slots["from_place"] = slots["where"]
    if category == "cab_travel" and "where" not in slots and slots.get("from_place"):
        slots["where"] = slots["from_place"]


def export_facts(slots: dict[str, Any]) -> dict[str, str]:
    """The collected slots as playbook facts: fact names only, clean one-line strings."""
    out = {
        k: clean_fact(v) for k, v in slots.items()
        if k in PLAYBOOK_INPUT_NAMES and clean_fact(v) and not isinstance(v, bool)
    }
    if slots.get(GATE_EXCHANGE) is True:
        out["q_exchange"] = "yes"
    return out


def when_text_from(slots: dict[str, Any], category: str | None) -> str | None:
    """The request's date/time in the user's words: the category's date fact, else ``when``."""
    ds = DATE_SLOT.get(category or "")
    parts = [str(slots[k]) for k in (ds, "time") if k and slots.get(k) and not (
        k == "time" and ds == "pickup_time")]
    if parts:
        return " ".join(parts)
    return str(slots["when"]) if slots.get("when") else None
