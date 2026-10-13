"""Facts about the user's request that a call script may need to say or to answer from.

The project manager collects them from the user BEFORE a call; a playbook may use any of them as
a ``{placeholder}`` and test ``has_<fact>``. Friday only ever answers a business's question from
these (or says she will ask the user): she never invents one. Founder, 13 Oct 2026.
"""

from __future__ import annotations

FACTS: dict[str, str] = {
    # events, weddings, banquets, parlour/makeup at the venue
    "event_type": "what the event is (shaadi, birthday, corporate ...)",
    "event_date": "the event date",
    "event_venue": "venue name",
    "event_city": "city / area of the venue",
    "guests": "number of guests",
    "veg_nonveg": "veg or non-veg",
    "rooms_needed": "number of rooms needed for guests",
    "extras_needed": "decoration / DJ / sound ... the user asked for",
    "people_count": "number of people to be served (makeup, table ...)",
    # cab
    "from_place": "pickup place",
    "to_place": "drop place",
    "pickup_time": "pickup date and time",
    "trip_type": "one way / round trip",
    "luggage": "bags / luggage",
    # PG
    "sharing_type": "single / double / triple sharing",
    "move_in_date": "move-in date",
    "occupant_name": "who the room is for",
    "occupant_from": "where they come from",
    "occupant_job": "where they work / study",
    "occupant_location": "where they live now",
    # hotel
    "checkin_date": "check-in date",
    "checkout_date": "check-out date",
    "room_count": "number of rooms",
    "room_type": "room type (deluxe, suite ...)",
    # packers and movers / home service
    "items_description": "what needs to move / what the work is",
    "floor_info": "floor and lift at both ends",
    # electronics exchange
    "old_phone_model": "the old phone to exchange",
    "old_phone_year": "year of purchase",
    "old_phone_condition": "does it work fully, any damage",
    # florist
    "delivery_area": "area for home delivery",
    # generic date / time (table booking, packers and movers, florist)
    "date": "the date the booking / shifting / delivery is needed",
    "time": "the time",
    # negotiation (never above the user's maximum)
    "target_price": "first push: a little below the user's budget",
    "max_price": "the most Friday may agree to",
}

# Switches the project manager may also set from the user's own words (never invented).
# ``q_exchange``: the user wants to exchange an old phone. ``q_ask_advance``: the user's own
# request mentions a booking amount / advance.
EXTRA_INPUTS = (
    "q_exchange", "q_ask_advance",
    # callbacks started by the user's decision (the task layer): the mode and what the earlier
    # call already learned, so a retry / negotiation / confirmation call never re-asks it
    "playbook_mode", "resume", "prior_price_inr", "prior_estimate_inr", "prior_slot_free",
    "prior_slot", "prior_notes", "prior_flags",
)
PLAYBOOK_INPUT_NAMES = frozenset(FACTS) | set(EXTRA_INPUTS)

_PREFIX = "fact:"


def clean_fact(value: object, limit: int = 80) -> str:
    return " ".join(str(value).split())[:limit]


def fact_constraints(facts: dict[str, object]) -> list[str]:
    """TaskSpec.constraints entries (``"fact: name=value"``) that carry the user's facts to the
    call brief; empty / unknown names are dropped."""
    return [
        f"{_PREFIX} {k}={clean_fact(v)}" for k, v in facts.items()
        if k in PLAYBOOK_INPUT_NAMES and clean_fact(v)
    ]


def facts_from_constraints(constraints: list[str]) -> dict[str, str]:
    """Inverse of ``fact_constraints``: the playbook inputs a brief's constraints carry."""
    out: dict[str, str] = {}
    for c in constraints:
        c = c.strip()
        if not c.lower().startswith(_PREFIX):
            continue
        name, _, val = c[len(_PREFIX):].strip().partition("=")
        name, val = name.strip(), clean_fact(val)
        if name in PLAYBOOK_INPUT_NAMES and val:
            out[name] = val
    return out
