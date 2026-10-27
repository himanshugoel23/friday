# ruff: noqa: E501
"""User-facing lines for the grocery flows. PENDING founder approval (hear before change).

Same conventions as sites/copy.py: ``en`` plus Roman Hinglish ``hi``; no secrets by construction;
``render`` scrubs the result. Not wired into the flow yet (copy.py is a shared file).
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

APPROVAL_PENDING = True
COPY: dict[str, dict[str, str]] = {
    "q_grocery_items": {"en": "What groceries do you need? (item, brand and size if you care)",
                        "hi": "Kya-kya grocery chahiye? (item, brand aur size agar zaroori ho)"},
    "approve_grocery": {
        "en": ("Please check:\n{lines}\nFrom: {merchant}\nDeliver to: {address}\nArrives: {when}\n"
               "Items: {subtotal}. Delivery and handling fees get added. Substitutions are OFF: if "
               "something is out of stock I will ask you first. I will go ahead only if the final "
               "bill is {max_total} or less.\nI never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nKahan se: {merchant}\nKahan bhejna hai: {address}\n"
               "Kab aayega: {when}\nItems: {subtotal}. Delivery aur handling fee judti hai. "
               "Substitute BAND hai: koi cheez khatam hui to pehle poochungi. Final bill {max_total} "
               "ya kam ho tabhi aage badhungi.\nPayment main kabhi nahi karti: aap apne UPI app se "
               "denge. Aage badhun?")},
    "grocery_out_of_stock": {
        "en": "{name} is out of stock. I have not swapped anything. {options}Want one of these instead, or skip it?",
        "hi": "{name} khatam hai. Maine kuch badla nahi. {options}Inme se koi chalega, ya chhod dun?"},
    "grocery_options": {"en": "In stock instead: {options}. ", "hi": "Iski jagah available: {options}. "},
    "grocery_below_minimum": {
        "en": "{site} needs a bigger cart: add {what}. Nothing was ordered.",
        "hi": "{site} par cart thoda chhota hai: {what} aur jodiye. Kuch order nahi hua."},
    "grocery_closed": {"en": "{site} is closed or not delivering to you right now. Nothing was ordered.",
                       "hi": "{site} abhi band hai ya aapke yahan deliver nahi kar raha. Kuch order nahi hua."},
    "grocery_no_slot": {"en": "{site} has no delivery slot free right now. Nothing was ordered.",
                        "hi": "{site} par abhi koi delivery slot khaali nahi hai. Kuch order nahi hua."},
    "grocery_login_needed": {
        "en": "{site} has logged you out. Log in again on this private page, never in chat: {link}",
        "hi": "{site} ne aapko logout kar diya. Is private page par dobara login kijiye, chat mein kabhi nahi: {link}"},
}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))
