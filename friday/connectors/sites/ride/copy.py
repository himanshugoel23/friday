# ruff: noqa: E501
"""User-facing lines for the ride flows. PENDING founder approval (hear before change).

Same conventions as sites/copy.py: ``en`` plus Roman Hinglish ``hi``; no secrets by construction
(the ride-start code is never a placeholder here: only the one-time link is); ``render`` scrubs.
Not wired into the flow yet (copy.py is a shared file).
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

APPROVAL_PENDING = True
COPY: dict[str, dict[str, str]] = {
    "q_ride_pickup": {"en": "Where should the driver pick you up? (a place name or a dropped pin)",
                      "hi": "Driver aapko kahan se lega? (jagah ka naam ya pin)"},
    "q_ride_drop": {"en": "Where to?", "hi": "Kahan jaana hai?"},
    "q_ride_vehicle": {"en": "Auto, bike, cab or premium?", "hi": "Auto, bike, cab ya premium?"},
    "approve_ride": {
        "en": ("Please check:\n{lines}\nPickup: {address}\n{when}. Fare is a range: {subtotal} to "
               "{max_total}. If the fare, surge or cancellation fee goes up I will ask you again "
               "before booking.\nYou pay the driver or in your own app: I never pay. This card is "
               "valid for 3 minutes. Book it?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nPickup: {address}\n{when}. Fare ek range hai: {subtotal} "
               "se {max_total}. Fare, surge ya cancellation fee badhi to booking se pehle phir "
               "poochungi.\nPayment aap driver ko ya apne app se karenge: main kabhi pay nahi karti. "
               "Yeh card 3 minute tak valid hai. Book kar dun?")},
    "ride_booked": {
        "en": ("Booked. Driver: {driver}. Your ride-start code is on this private page, open it only "
               "when the driver arrives: {otp_link}\nShare your live trip: {share_link}"),
        "hi": ("Book ho gaya. Driver: {driver}. Ride shuru karne ka code is private page par hai, "
               "driver aaye tabhi kholiye: {otp_link}\nLive trip share kijiye: {share_link}")},
    "ride_no_driver": {"en": "No driver accepted on {site}, so I cancelled the request. Nothing was charged.",
                       "hi": "{site} par kisi driver ne accept nahi kiya, isliye request cancel kar di. Kuch charge nahi hua."},
    "ride_unavailable": {"en": "{what} is not available on {site} right now. Try another vehicle type?",
                         "hi": "{site} par abhi {what} available nahi hai. Koi aur vehicle chalega?"},
    "ride_place_not_found": {"en": "I could not find {what} on {site}. Send a clearer place name or drop a pin.",
                             "hi": "{site} par {what} nahi mila. Jagah ka saaf naam bhejiye ya pin dalein."},
    "ride_closed": {"en": "{site} is not giving rides in your area right now.",
                    "hi": "{site} abhi aapke area mein ride nahi de raha."},
    "ride_login_needed": {
        "en": "{site} has logged you out. Log in again on this private page, never in chat: {link}",
        "hi": "{site} ne aapko logout kar diya. Is private page par dobara login kijiye, chat mein kabhi nahi: {link}"},
    "ride_expired": {"en": "That ride offer expired (3 minutes). Ask me again for a fresh price.",
                     "hi": "Woh ride offer expire ho gaya (3 minute). Naya price ke liye phir bolein."},
}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))
