# ruff: noqa: E501
"""User-facing lines of the TRAIN flows. PENDING founder approval (hear before change).

Nothing here is approved wording; it follows the conventions of sites/copy.py (``en`` + Roman
Hinglish ``hi``, no secrets by construction, ``render`` scrubs the result). The shared flow does not
know these keys yet: see docs/BROWSER_TRAIN_SHOP.md for the wiring.
"""

from __future__ import annotations

from friday.connectors.scrub import scrub_text

LANGS = ("en", "hi")
APPROVAL_PENDING = True

COPY: dict[str, dict[str, str]] = {
    "q_train_from": {"en": "Which station are you leaving from?", "hi": "Kis station se chalna hai?"},
    "q_train_to": {"en": "Which station are you going to?", "hi": "Kis station tak jaana hai?"},
    "q_train_date": {"en": "Which date? (for example 2026-11-08)", "hi": "Kaun si date? (jaise 2026-11-08)"},
    "q_train_cls": {"en": "Which class? SL, 3A, 2A, 1A, CC or EC.", "hi": "Kaun si class? SL, 3A, 2A, 1A, CC ya EC."},
    "q_train_quota": {"en": "General quota or Tatkal? I use Tatkal only if you say so.",
                      "hi": "General quota ya Tatkal? Tatkal tabhi lungi jab aap bolenge."},
    "q_train_passengers": {
        "en": "For each passenger I need the full name, age, gender and berth preference (lower, middle, upper, side lower, side upper or no preference). I will not guess any of these. Still needed: {what}",
        "hi": "Har passenger ka poora naam, umar, gender aur berth preference (lower, middle, upper, side lower, side upper ya no preference) chahiye. Main inme se kuch andaza nahi lagaungi. Abhi chahiye: {what}"},
    "q_train_pick": {"en": "Which train? Here is what I found:\n{options}", "hi": "Kaun si train? Yeh mili hain:\n{options}"},
    "approve_train": {
        "en": ("Please check:\nTrain: {lines}\nSite: {merchant}\nTickets: {subtotal}. Reservation and booking fees get added. "
               "I will go ahead only if the final amount is {max_total} or less. Extras like insurance are left unticked.\n"
               "I never pay: you pay in your own UPI app, or finish on the site. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\nTrain: {lines}\nSite: {merchant}\nTicket: {subtotal}. Reservation aur booking fee judte hain. "
               "Final amount {max_total} ya usse kam ho tabhi aage badhungi. Insurance jaise extras tick nahi karungi.\n"
               "Payment main kabhi nahi karti: aap apne UPI app se denge, ya site par khud poora kijiye. Aage badhun?")},
    "approve_train_waitlist": {
        "en": ("This ticket is {status}, so it may NOT be confirmed and the seat is not guaranteed. To go ahead, reply exactly: {phrase}"),
        "hi": ("Yeh ticket {status} hai, isliye confirm na bhi ho sakta hai aur seat pakki nahi hai. Aage badhne ke liye bilkul yeh likhiye: {phrase}")},
    "waitlist_phrase": {"en": "WAITLIST OK", "hi": "WAITLIST OK"},
    "handover_captcha": {
        "en": "{site} is showing a captcha. I never solve those, so I stopped. Nothing was booked. Finish here: {link}",
        "hi": "{site} captcha dikha raha hai. Main use kabhi solve nahi karti, isliye ruk gayi. Kuch book nahi hua. Yahan poora kijiye: {link}"},
    "handover_window": {
        "en": "Booking for that date has not opened yet on {site}. I did not try anything. You can book when it opens: {link}",
        "hi": "{site} par us date ki booking abhi khuli nahi hai. Maine kuch try nahi kiya. Khulne par yahan book kijiye: {link}"},
    "addon_stuck": {
        "en": "{site} kept an extra ticked ({names}) and I could not remove it, so it is included in the new total.",
        "hi": "{site} ne ek extra ({names}) tick rakha aur main use hata nahi paayi, isliye naye total mein judta hai."},
    "note_addon_unticked": {"en": " I unticked a pre-selected extra.", "hi": " Pehle se tick kiya hua ek extra maine hata diya."},
    "summary_train": {
        "en": "Done: {lines} on {merchant}. Total {amount}, paid by you through UPI.{notes}",
        "hi": "Ho gaya: {merchant} par {lines}. Total {amount}, UPI se aapne pay kiya.{notes}"},
    "info_train": {"en": "Here is what {site} shows:\n{lines}\nThis is information only; nothing was booked.",
                   "hi": "{site} par yeh dikh raha hai:\n{lines}\nYeh sirf jaankari hai; kuch book nahi hua."},
}
QUESTION_KEYS = {"from": "q_train_from", "to": "q_train_to", "date": "q_train_date", "cls": "q_train_cls",
                 "quota": "q_train_quota", "passengers": "q_train_passengers", "train": "q_train_pick"}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))
