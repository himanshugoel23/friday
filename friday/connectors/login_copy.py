# ruff: noqa: E501
"""ALL user-facing text of the saved-logins commands and the login-code-in-chat path.

PENDING_FOUNDER_APPROVAL: no line below has been approved. Under the hear-before-change rule
(CLAUDE.md rule 3) none may be shown to a real person until the founder has read and approved it.
Tests check structure (every id in en and hi, placeholders, no secret words echoed), never the
exact words, so the words can change freely after review.

Ids (listed in docs/CHATBOT_PILOT.md for the approval list): ``login.line.<key>``.
Languages: ``en`` and ``hi`` (Roman Hinglish, like the rest of the browser flow).
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

LINES: dict[str, dict[str, str]] = {
    "none": {"en": "I have no saved logins for you.",
             "hi": "Aapke koi saved login mere paas nahi hain."},
    "list": {"en": "Saved logins (passwords are never shown): {sites}. Say \"forget my logins\" to delete them all, or \"forget <site>\" for one.",
             "hi": "Saved logins (password kabhi nahi dikhate): {sites}. Sab hatane ke liye \"forget my logins\" likhiye, ek ke liye \"forget <site>\"."},
    "off": {"en": "Saved logins are not switched on.", "hi": "Saved logins abhi chalu nahi hain."},
    "link": {"en": "Open this private page to save your {site} login. Never type it in chat: {link}",
             "hi": "Apna {site} login save karne ke liye yeh private page kholiye. Chat mein kabhi mat likhiye: {link}"},
    "refused": {"en": "I can't save that kind of login.", "hi": "Is tarah ka login main save nahi kar sakti."},
    "unknown_site": {"en": "I don't know that site.", "hi": "Yeh site main nahi jaanti."},
    # forget (with confirmation)
    "confirm_all": {"en": "Delete all {n} saved login(s) and your saved browser sessions? This cannot be undone.",
                    "hi": "Saare {n} saved login aur saved browser sessions delete kar doon? Yeh wapas nahi aayega."},
    "confirm_site": {"en": "Delete your saved {site} login? This cannot be undone.",
                     "hi": "Aapka saved {site} login delete kar doon? Yeh wapas nahi aayega."},
    "forgotten": {"en": "Done. I deleted {n} saved login(s) and your saved browser sessions.",
                  "hi": "Ho gaya. Maine {n} saved login aur aapke saved browser sessions hata diye."},
    "forgotten_site": {"en": "Done. I deleted your saved {site} login.",
                       "hi": "Ho gaya. Maine aapka saved {site} login hata diya."},
    "forget_none": {"en": "I have no saved login for {site}.", "hi": "{site} ka koi saved login mere paas nahi hai."},
    "forget_cancelled": {"en": "Okay, I kept your saved logins.", "hi": "Theek hai, aapke saved logins rakh liye."},
    "btn_forget_yes": {"en": "Yes, delete", "hi": "Haan, delete"},
    "btn_forget_no": {"en": "No, keep", "hi": "Nahi, rehne do"},
    # login code in chat
    "chat_hint": {"en": "You can also just reply here with that login code. I use it once and do not keep it. I never ask for bank or payment codes.",
                  "hi": "Aap woh login code seedha yahin bhej sakte hain. Main use ek baar karti hoon, rakhti nahi. Bank ya payment ka code main kabhi nahi maangti."},
    "code_taken": {"en": "Got it, using the code now. (The copy in your WhatsApp stays on your phone and WhatsApp; I cannot delete that one, so you may delete the message.)",
                   "hi": "Mil gaya, code abhi use kar rahi hoon. (Aapke WhatsApp mein jo copy hai woh aapke phone aur WhatsApp mein rehti hai, use main delete nahi kar sakti; aap message delete kar sakte hain.)"},
    "refused_payment": {"en": "I can't take bank or payment codes. Please keep it to yourself and finish the payment in your own bank or UPI app.",
                        "hi": "Bank ya payment ka code main nahi le sakti. Use apne paas rakhiye aur payment apne bank ya UPI app mein poora kijiye."},
    "refused_upi_pin": {"en": "Never share your UPI PIN with anyone, including me. Enter it only in your own UPI app.",
                        "hi": "Apna UPI PIN kisi ko mat bataiye, mujhe bhi nahi. Sirf apne UPI app mein daaliye."},
    "refused_card": {"en": "Please don't send card numbers or CVV here. Pay in your own app or on the bank's page.",
                     "hi": "Card number ya CVV yahan mat bhejiye. Payment apne app ya bank ke page par kijiye."},
    "refused_aadhaar": {"en": "I can't take Aadhaar numbers or Aadhaar codes. Please keep them to yourself.",
                        "hi": "Aadhaar number ya Aadhaar ka code main nahi le sakti. Use apne paas rakhiye."},
    "refused_password": {"en": "Please don't type passwords in chat. If I need a site password, I will send a private page where only you can type it.",
                         "hi": "Password chat mein mat likhiye. Zarurat hui to main ek private page bhejungi jahan sirf aap likh sakte hain."},
}


def line(key: str, lang: str = "en", **kw: object) -> str:
    row = LINES[key]
    return row.get(lang, row["en"]).format(**kw)


def all_ids() -> list[str]:
    return [f"login.line.{k}" for k in LINES]


REFUSAL_LINE = {
    "refuse_payment_otp": "refused_payment",
    "refuse_upi_pin": "refused_upi_pin",
    "refuse_card": "refused_card",
    "refuse_aadhaar": "refused_aadhaar",
    "refuse_password": "refused_password",
}
