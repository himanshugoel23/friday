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
    # negotiation (never above the user's maximum)
    "target_price": "first push: a little below the user's budget",
    "max_price": "the most Friday may agree to",
}
