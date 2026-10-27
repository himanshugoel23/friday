# ruff: noqa: E501
"""ALL user-facing lines of the browser flows. PENDING founder approval (hear before change).

Nothing here is approved wording: docs/PRIVATE_BROWSER_FLOWS.md lists every line (generated from
this dict by ``friday browser-sim --print-copy``). ``hi`` is Roman-script Hinglish. Lines carry no
secrets by construction; ``render`` also scrubs the result.
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

LANGS = ("en", "hi")
APPROVAL_PENDING = True

COPY: dict[str, dict[str, str]] = {
    "ack": {
        "en": "On it. I'll message you only if I need something or when it's done.",
        "hi": "Theek hai, ho jayega. Kuch poochna hua ya kaam ho gaya, tabhi message aayega.",
    },
    "q_food_items": {"en": "What would you like to order?", "hi": "Kya order karna hai?"},
    "q_food_restaurant": {"en": "From which restaurant?", "hi": "Kaunse restaurant se?"},
    "q_address": {"en": "Which address should it go to?", "hi": "Kis address par bhejna hai?"},
    "q_movie_title": {"en": "Which movie?", "hi": "Kaun si film?"},
    "q_movie_seats": {"en": "How many seats?", "hi": "Kitni seats chahiye?"},
    "q_movie_time": {"en": "Which show time? (for example 7 pm)",
                     "hi": "Kaun sa show? (jaise 7 baje)"},
    "q_movie_area": {"en": "Which area or cinema?", "hi": "Kis area ya cinema mein?"},
    "approve_food": {
        "en": ("Please check:\n{lines}\nFrom: {merchant}\nDeliver to: {address}\n"
               "Items: {subtotal}. Delivery fee and taxes get added at checkout. I will go ahead "
               "only if the final bill is {max_total} or less.\nI never pay: you pay in your own "
               "UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nKahan se: {merchant}\nKahan bhejna hai: {address}\n"
               "Items: {subtotal}. Delivery fee aur tax checkout par judte hain. Final bill "
               "{max_total} ya usse kam ho tabhi aage badhungi.\nPayment main kabhi nahi karti: "
               "aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_movie": {
        "en": ("Please check:\nMovie: {movie}\nCinema: {merchant}\nShow: {when}\nSeats: {lines}\n"
               "Tickets: {subtotal}. Booking fee and taxes get added. I will go ahead only if the "
               "final amount is {max_total} or less.\nI never pay: you pay in your own UPI app. "
               "Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\nFilm: {movie}\nCinema: {merchant}\nShow: {when}\nSeats: {lines}\n"
               "Tickets: {subtotal}. Booking fee aur tax judte hain. Final amount {max_total} ya "
               "usse kam ho tabhi aage badhungi.\nPayment main kabhi nahi karti: aap apne UPI app "
               "se denge. Aage badhun?"),
    },
    "q_grocery_items": {"en": "What should I order? (for example 2 milk, 1 bread)",
                        "hi": "Kya mangwana hai? (jaise 2 doodh, 1 bread)"},
    "q_pickup": {"en": "Where should the ride pick you up?", "hi": "Gaadi aapko kahan se leni hai?"},
    "q_drop": {"en": "Where do you want to go?", "hi": "Kahan jaana hai?"},
    "q_origin": {"en": "From which city or place?", "hi": "Kahan se?"},
    "q_dest": {"en": "To which city or place?", "hi": "Kahan tak?"},
    "q_date": {"en": "On which date? (for example tomorrow, or 5 Nov)", "hi": "Kis tareekh ko? (jaise kal, ya 5 Nov)"},
    "q_city": {"en": "In which city?", "hi": "Kaunse shehar mein?"},
    "q_checkin": {"en": "Check-in date? (for example tomorrow, or 5 Nov)", "hi": "Check-in kab? (jaise kal, ya 5 Nov)"},
    "q_nights": {"en": "How many nights?", "hi": "Kitni raat?"},
    "q_guests": {"en": "How many guests?", "hi": "Kitne log?"},
    "q_passengers": {"en": "How many passengers?", "hi": "Kitne yatri?"},
    "q_query": {"en": "What would you like to buy?", "hi": "Kya kharidna hai?"},
    "q_generic": {"en": "One more detail please: {slot}", "hi": "Ek detail aur chahiye: {slot}"},
    "approve_grocery": {
        "en": ("Please check:\n{lines}\nFrom: {merchant}\nDeliver to: {address}\n"
               "Items: {subtotal}. Delivery and handling fees get added. No substitutions. I will go "
               "ahead only if the final bill is {max_total} or less.\nI never pay: you pay in your own "
               "UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nKahan se: {merchant}\nKahan bhejna hai: {address}\n"
               "Items: {subtotal}. Delivery aur handling fee judti hai. Koi substitute nahi. Final bill "
               "{max_total} ya usse kam ho tabhi aage badhungi.\nPayment main kabhi nahi karti: aap apne "
               "UPI app se denge. Aage badhun?"),
    },
    "approve_ride": {
        "en": ("Please check the ride:\n{lines}\nVia: {merchant}\nPickup: {address}\n{when}"
               "Fare estimate {subtotal}. Fares can change; I will go ahead only if it stays at "
               "{max_total} or less. A cancellation fee may apply.{extra}\nI never pay: you pay the "
               "driver or in your own UPI app. Go ahead?"),
        "hi": ("Ride ek baar dekh lijiye:\n{lines}\nKiske through: {merchant}\nPickup: {address}\n{when}"
               "Fare ka andaza {subtotal}. Fare badal sakta hai; {max_total} ya usse kam rahe tabhi aage "
               "badhungi. Cancel karne par fee lag sakti hai.{extra}\nPayment main kabhi nahi karti: aap "
               "driver ko ya apne UPI app se denge. Aage badhun?"),
    },
    "approve_hotel": {
        "en": ("Please check the stay:\n{lines}\nHotel: {merchant}\n{when}\nPrice: {subtotal}. Taxes get "
               "added. I will go ahead only if the final amount is {max_total} or less.{extra}\nI never "
               "pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Stay ek baar dekh lijiye:\n{lines}\nHotel: {merchant}\n{when}\nPrice: {subtotal}. Tax judta "
               "hai. Final amount {max_total} ya usse kam ho tabhi aage badhungi.{extra}\nPayment main "
               "kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_flight": {
        "en": ("Please check the flight:\n{lines}\nVia: {merchant}\n{when}\nFare: {subtotal}. Taxes and fees "
               "get added. I will go ahead only if the final amount is {max_total} or less.{extra}\nI never "
               "pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Flight ek baar dekh lijiye:\n{lines}\nKiske through: {merchant}\n{when}\nFare: {subtotal}. "
               "Tax aur fee judti hai. Final amount {max_total} ya usse kam ho tabhi aage badhungi.{extra}\n"
               "Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_bus": {
        "en": ("Please check the bus:\n{lines}\nOperator and site: {merchant}\n{when}\nFare: {subtotal}. "
               "Fees get added. I will go ahead only if the final amount is {max_total} or less.{extra}\n"
               "I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Bus ek baar dekh lijiye:\n{lines}\nOperator aur site: {merchant}\n{when}\nFare: {subtotal}. "
               "Fee judti hai. Final amount {max_total} ya usse kam ho tabhi aage badhungi.{extra}\n"
               "Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_train": {
        "en": ("Please check the train ticket:\n{lines}\nVia: {merchant}\n{when}\nFare: {subtotal}. Fees get "
               "added. I will go ahead only if the final amount is {max_total} or less.{extra}\nI never "
               "pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Train ticket ek baar dekh lijiye:\n{lines}\nKiske through: {merchant}\n{when}\nFare: {subtotal}. "
               "Fee judti hai. Final amount {max_total} ya usse kam ho tabhi aage badhungi.{extra}\n"
               "Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_shopping": {
        "en": ("Please check:\n{lines}\nFrom: {merchant}\nDeliver to: {address}\nItems: {subtotal}. Delivery "
               "and taxes get added. I will go ahead only if the final amount is {max_total} or less.\n"
               "I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nKahan se: {merchant}\nKahan bhejna hai: {address}\nItems: "
               "{subtotal}. Delivery aur tax judte hain. Final amount {max_total} ya usse kam ho tabhi "
               "aage badhungi.\nPayment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "summary_generic": {
        "en": "Done: {lines} via {merchant}. Total {amount}, paid by you through UPI.{notes}",
        "hi": "Ho gaya: {lines}, {merchant} par. Total {amount}, UPI se aapne pay kiya.{notes}",
    },
    "summary_ride": {
        "en": "Done: ride requested, {lines} via {merchant}. Fare {amount}, paid by you.{notes}",
        "hi": "Ho gaya: ride request ho gayi, {lines}, {merchant}. Fare {amount}, aapne pay kiya.{notes}",
    },
    "handover": {
        "en": ("I can't do this on {site} for you directly yet, so here is the link. You can finish it "
               "there yourself: {link}"),
        "hi": ("Abhi main {site} par yeh seedha nahi kar sakti, isliye link bhej rahi hoon. Aap wahan khud "
               "poora kar sakte hain: {link}"),
    },
    "reapprove": {
        "en": ("Something changed: {reason}\nNew total: {total} (you approved up to {old_max}).\n"
               "{lines}\nDo you still want it?"),
        "hi": ("Kuch badal gaya: {reason}\nNaya total: {total} (aapne {old_max} tak ka kaha tha).\n"
               "{lines}\nKya ab bhi chahiye?"),
    },
    "btn_yes": {"en": "Yes, go ahead", "hi": "Haan, aage badho"},
    "btn_no": {"en": "No, cancel", "hi": "Nahi, rehne do"},
    "btn_retry": {"en": "Try again", "hi": "Phir se try karo"},
    "btn_paid": {"en": "I have paid", "hi": "Pay kar diya"},
    "login_needed": {
        "en": ("{site} needs you to log in. A code was sent to your phone by {site}. Type it on "
               "this private page, never in chat: {link}\nFriday never asks for bank or payment codes."),
        "hi": ("{site} par login chahiye. {site} ne aapke phone par code bheja hai. Use sirf is "
               "private page par daaliye, chat mein kabhi nahi: {link}\nBank ya payment ka code "
               "Friday kabhi nahi maangti."),
    },
    "login_timeout": {
        "en": "The login code did not arrive in time. Tap below to try again.",
        "hi": "Login code time par nahi mila. Phir se try karne ke liye neeche dabaiye.",
    },
    "login_failed": {
        "en": "{site} did not accept that code. Tap below to try again.",
        "hi": "{site} ne woh code nahi manaa. Phir se try karne ke liye neeche dabaiye.",
    },
    "payment_ready": {
        "en": ("All set. Pay {amount} to {merchant} in your own UPI app: scan this QR{link_part}. "
               "I have not paid anything."),
        "hi": ("Sab taiyaar hai. {amount} {merchant} ko apne UPI app se dijiye: yeh QR scan "
               "kijiye{link_part}. Maine kuch pay nahi kiya hai."),
    },
    "link_part": {"en": " or open {link}", "hi": " ya {link} kholiye"},
    "paid_thanks": {"en": "Thanks. {status}", "hi": "Shukriya. {status}"},
    "summary_food": {
        "en": ("Done: {lines} from {merchant}, to {address}. Total {amount}, paid by you through "
               "UPI.{notes}"),
        "hi": ("Ho gaya: {merchant} se {lines}, {address} par. Total {amount}, UPI se aapne "
               "pay kiya.{notes}"),
    },
    "summary_movie": {
        "en": ("Done: {movie}, {when} at {merchant}, seats {lines}. Total {amount}, paid by you "
               "through UPI.{notes}"),
        "hi": ("Ho gaya: {movie}, {when}, {merchant}, seats {lines}. Total {amount}, UPI se aapne "
               "pay kiya.{notes}"),
    },
    "note_injection": {
        "en": " The site showed some odd instructions in its text; I ignored them.",
        "hi": " Site ke text mein kuch ajeeb instructions the; maine unhe ignore kiya.",
    },
    "note_repaired": {
        "en": " The site layout changed a little; I adapted and logged it for review.",
        "hi": " Site ka layout thoda badla tha; maine adjust kiya aur review ke liye note kiya.",
    },
    "out_of_stock": {
        "en": "Sorry, {names} is not available right now, so I stopped before adding anything.",
        "hi": "Maaf kijiye, {names} abhi available nahi hai, isliye kuch add kiye bina ruk gayi.",
    },
    "no_match": {
        "en": "I could not find {what} on {site}. Nothing was ordered.",
        "hi": "{site} par {what} nahi mila. Kuch order nahi hua.",
    },
    "degraded": {
        "en": "I can't use {site} reliably right now. You can finish it yourself here: {link}",
        "hi": "Abhi {site} ko bharose se use nahi kar pa rahi. Aap khud yahan poora kar sakte hain: {link}",
    },
    "blocked": {
        "en": "{site} is asking for a human check, so I stopped. Nothing was ordered. Finish here: {link}",
        "hi": "{site} human check maang raha hai, isliye ruk gayi. Kuch order nahi hua. Yahan poora kijiye: {link}",
    },
    "cancelled": {
        "en": "Okay, cancelled. Nothing was ordered or paid.",
        "hi": "Theek hai, cancel kar diya. Kuch order ya pay nahi hua.",
    },
    "expired": {
        "en": "That request timed out, so I stopped. Nothing was ordered or paid. Ask me again any time.",
        "hi": "Request ka time khatam ho gaya, isliye ruk gayi. Kuch order ya pay nahi hua. Kabhi bhi phir bolein.",
    },
    "error": {
        "en": "I hit a problem and stopped safely. Nothing was ordered or paid.",
        "hi": "Kuch gadbad hui, isliye surakshit roop se ruk gayi. Kuch order ya pay nahi hua.",
    },
    "not_available": {
        "en": "Browser ordering is not switched on yet.",
        "hi": "Browser se order abhi chalu nahi hai.",
    },
}


class _Loose(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return ""


def render(key: str, lang: str, *, loose: bool = False, **kw: object) -> str:
    """``loose=True``: a placeholder the caller did not supply renders empty (approval cards, where
    each category's adapter supplies its own extra fields in ``Proposal.details``)."""
    table = COPY[key]
    text = table.get(lang) or table["en"]
    return scrub_text(text.format_map(_Loose(kw)) if loose else text.format(**kw))


def register_copy(table: dict[str, dict[str, str]]) -> None:
    """Merge a category package's own lines (its ``copy.COPY``). Later packages win on a clash."""
    for key, langs in table.items():
        COPY[key] = dict(langs)
