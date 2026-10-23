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


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    text = table.get(lang) or table["en"]
    return scrub_text(text.format(**kw))
