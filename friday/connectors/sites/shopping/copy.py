# ruff: noqa: E501
"""User-facing lines of the SHOPPING flows. PENDING founder approval (hear before change).

Nothing here is approved wording; it follows the conventions of sites/copy.py (``en`` + Roman
Hinglish ``hi``, no secrets by construction, ``render`` scrubs the result). The shared flow does not
know these keys yet: see docs/BROWSER_TRAIN_SHOP.md for the wiring.
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

LANGS = ("en", "hi")
APPROVAL_PENDING = True

COPY: dict[str, dict[str, str]] = {
    "q_shop_query": {"en": "What would you like to buy?", "hi": "Kya kharidna hai?"},
    "q_shop_pick": {"en": "Which one? Reply with the number:\n{options}", "hi": "Kaun sa? Number bhejiye:\n{options}"},
    "q_shop_variant": {"en": "Which size or colour? I do not guess this. Options:\n{options}",
                       "hi": "Kaun sa size ya colour? Yeh main andaza nahi lagati. Options:\n{options}"},
    "q_shop_order": {"en": "Which order? Reply with its number:\n{options}", "hi": "Kaun sa order? Uska number bhejiye:\n{options}"},
    "q_shop_budget": {"en": "What is the most you want to pay in total, delivery included?",
                      "hi": "Delivery mila kar zyada se zyada kitna dena hai?"},
    "approve_shopping": {
        "en": ("Please check:\n{lines}\nSite: {merchant}\nDeliver to: {address}\nItem: {subtotal}. Delivery and any fees get added. "
               "I will go ahead only if the final total is {max_total} or less. I leave add-ons, plans and trials unticked.\n"
               "I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{lines}\nSite: {merchant}\nKahan bhejna hai: {address}\nItem: {subtotal}. Delivery aur fees judte hain. "
               "Final total {max_total} ya usse kam ho tabhi aage badhungi. Add-on, plan aur trial tick nahi karungi.\n"
               "Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?")},
    "approve_cancel_order": {
        "en": "{lines}\nCancelling cannot be undone. Do you want me to cancel this order?",
        "hi": "{lines}\nCancel karne ke baad wapas nahi hota. Kya yeh order cancel karun?"},
    "reprice": {"en": "The price changed: {reason}\nNew total: {total} (you approved up to {old_max}). Do you still want it?",
                "hi": "Price badal gaya: {reason}\nNaya total: {total} (aapne {old_max} tak ka kaha tha). Kya ab bhi chahiye?"},
    "addon_stuck": {"en": "{site} kept an extra ticked ({names}) and I could not remove it, so it is in the new total.",
                    "hi": "{site} ne ek extra ({names}) tick rakha aur main use hata nahi paayi, isliye naye total mein hai."},
    "note_addon_unticked": {"en": " I unticked pre-selected extras (plans, trials, add-ons).",
                            "hi": " Pehle se tick kiye extras (plan, trial, add-on) maine hata diye."},
    "summary_shopping": {"en": "Done: {lines} from {merchant}, to {address}. Total {amount}, paid by you through UPI.{notes}",
                         "hi": "Ho gaya: {merchant} se {lines}, {address} par. Total {amount}, UPI se aapne pay kiya.{notes}"},
    "track_order": {"en": "{lines}", "hi": "{lines}"},
    "cancelled_order": {"en": "Done: {lines}.", "hi": "Ho gaya: {lines}."},
    "over_budget": {"en": "That would cost more than your limit ({what}). Nothing was ordered.",
                    "hi": "Yeh aapki limit se zyada padega ({what}). Kuch order nahi hua."},
    "not_allowed": {"en": "That cannot be done: {what}.", "hi": "Yeh nahi ho sakta: {what}."},
}
QUESTION_KEYS = {"query": "q_shop_query", "pick": "q_shop_pick", "variant": "q_shop_variant",
                 "order_id": "q_shop_order", "address": "q_address", "budget": "q_shop_budget"}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))
