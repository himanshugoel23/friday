"""The CLOSED vocabularies of the playbook engine.

Everything a playbook file may refer to is listed here. A playbook that uses a word outside
these sets is rejected by the loader, and the model that understands the salon's reply can
only answer with one of ``Intent`` (anything else becomes ``UNCLEAR``).
"""

from __future__ import annotations

from enum import StrEnum


class Intent(StrEnum):
    """What the other side just did, in a fixed list. Never free text."""

    YES = "YES"  # haan / theek hai / bilkul
    NO = "NO"  # nahi
    CONTINUE = "CONTINUE"  # boliye / bolo / hello, go on
    ACK = "ACK"  # ok / shukriya (a polite closing noise)
    BUSY_LATER = "BUSY_LATER"  # busy, call later
    WHO_IS_THIS = "WHO_IS_THIS"  # kaun bol raha hai? who is this
    ASKS_REPEAT = "ASKS_REPEAT"  # kya? sorry? phir se boliye (she did not hear Friday)
    ARE_YOU_BOT = "ARE_YOU_BOT"  # robot hai? AI hai?
    WRONG_NUMBER = "WRONG_NUMBER"  # this is not a salon / wrong number
    HOLD_ON = "HOLD_ON"  # ek minute, hold karo
    SLOT_FREE = "SLOT_FREE"  # a slot is free (time optional)
    SLOT_BUSY = "SLOT_BUSY"  # nothing free
    OFFERS_SLOTS = "OFFERS_SLOTS"  # alternative times (one or two)
    GIVES_TIME = "GIVES_TIME"  # just a time of day
    NEEDS_APPOINTMENT = "NEEDS_APPOINTMENT"  # appointment only, no walk-in
    ASKS_CUSTOMER_PHONE = "ASKS_CUSTOMER_PHONE"  # give me the customer's number
    GIVES_PRICE = "GIVES_PRICE"  # one price (duration optional)
    PRICE_RANGE = "PRICE_RANGE"  # "400 se 600"
    PRICE_DEPENDS = "PRICE_DEPENDS"  # depends on the stylist
    REFUSES_PRICE = "REFUSES_PRICE"  # not on the phone
    NEEDS_ADVANCE = "NEEDS_ADVANCE"  # an advance / deposit is needed
    NO_ADVANCE = "NO_ADVANCE"  # no advance
    GIVES_STYLIST = "GIVES_STYLIST"  # a stylist name
    ASKS_OFFTOPIC = "ASKS_OFFTOPIC"  # parking, products, anything not in the script
    ASKS_SECRET = "ASKS_SECRET"  # OTP / PIN / card details
    STOP_CALLING = "STOP_CALLING"  # do not call us again (DNC)
    RUDE = "RUDE"  # abuse / hostile
    UNCLEAR = "UNCLEAR"  # could not understand / noise / silence


INTENTS: frozenset[str] = frozenset(i.value for i in Intent)
ANY = "ANY"  # wildcard key in a step's ``branches`` (everything not listed there or in defaults)

# conditions a playbook may test (``when:``); a leading "!" negates. Evaluated in code.
CONDITIONS: frozenset[str] = frozenset(
    {
        "recording",  # call recording is on (say the notice)
        "has_budget",
        "over_budget",  # price_inr known and above the user's budget
        "may_negotiate",  # the user allowed asking for a lower price
        "has_stylist_pref",
        "time_known",  # one concrete time heard
        "slot_known",  # a time or at least one offered time
        "price_known",
        "duration_known",
        "is_range",  # the price was a range (upper number taken)
        "has_offered",  # alternatives were offered
        "can_commit",  # the user delegated AND the commit check passes for the offer
        "first_ask",  # this step's question has not been asked yet on this call
    }
)

# values the engine collects (outputs) and can substitute into lines as {name}
SLOT_NAMES: frozenset[str] = frozenset(
    {
        "slot_free",
        "offered_slots",
        "slot",
        "price_inr",
        "duration_min",
        "stylist",
        "advance_needed",
        "price_unknown",
    }
)
INPUT_NAMES: frozenset[str] = frozenset(
    {"user_first_name", "service", "for_whom", "date_window", "budget", "stylist_pref",
     "callback_number"}
)
PLACEHOLDERS: frozenset[str] = INPUT_NAMES | {"slot", "price_inr", "duration_min", "stylist"}

# what the engine may write into ``set:`` of a branch (fixed values only)
SETTABLE: frozenset[str] = frozenset(
    {"advance_needed", "price_unknown", "slot_free", "price_note", "do_not_call", "rude",
     "wrong_number"}
)
