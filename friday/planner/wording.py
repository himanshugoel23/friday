# ruff: noqa: E501
"""Chat wording of the approach planner (CHAT TEXT ONLY: no spoken line lives here).

Rule: a line mentions calling only when the chosen plan includes a call. Every line is listed in
docs/APPROACH_PLANNER.md for the founder's approval (status PENDING until then). ``guard_text``
enforces the rule for any text a model wrote (an LLM question or decline reason).
"""

from __future__ import annotations

from friday.planner.signals import mentions_call
from friday.planner.types import Approach

LINES: dict[str, dict[str, str]] = {
    # --- one short acknowledgement when a plan is slow (names the approach)
    "ack_web": {
        "en": "On it, checking {where} now. I'll send the result in a moment.",
        "hinglish": "Ek minute, {where} check kar rahi hoon. Result abhi bhejti hoon.",
    },
    "ack_answer": {
        "en": "One moment, thinking this through.",
        "hinglish": "Ek minute, soch rahi hoon.",
    },
    "ack_app": {
        "en": "On it, working on this in {where} now.",
        "hinglish": "{where} par kar rahi hoon, bas ek minute.",
    },
    "ack_call": {
        "en": "On it, lining up the vendors now. This can take a few minutes.",
        "hinglish": "Shuru kar diya, vendors ki taiyari kar rahi hoon. Thoda time lag sakta hai.",
    },
    # --- web lookup outcomes
    "web_timeout": {
        "en": "That took too long and I could not get a reliable answer. You can check {where} directly, or I can try again. Want me to try once more?",
        "hinglish": "Isme bahut der lag gayi aur pakka jawab nahi mil paya. Aap {where} par seedha dekh sakte hain, ya main ek baar aur try karun?",
    },
    "web_unavailable": {
        "en": "I can't look things up on the web right now. Please check {where} directly, and I'll help once it's back.",
        "hinglish": "Abhi main web par check nahi kar sakti. {where} par seedha dekh lijiye, wapas chalu hote hi madad karungi.",
    },
    "web_none": {
        "en": "I could not find a reliable result for that. Tell me the exact product and your pincode and I'll try again.",
        "hinglish": "Iska pakka result nahi mila. Exact product aur apna pincode bata dein, main dobara dekhti hoon.",
    },
    "web_as_of": {"en": "As of {time} IST.", "hinglish": "{time} IST ke hisaab se."},
    "web_sources": {"en": "Sources:", "hinglish": "Sources:"},
    "caveat_quick": {
        "en": "This is from public web pages, not the {store} app. {store} prices and stock can differ by pincode and store, so treat it as a guide.",
        "hinglish": "Yeh public web pages se hai, {store} app se nahi. {store} ke daam aur stock pincode aur store ke hisaab se alag ho sakte hain, isliye ise andaaza maaniye.",
    },
    "caveat_web": {
        "en": "This is from public web pages and may differ from the shop's own app or counter price.",
        "hinglish": "Yeh public web pages se hai, dukaan ke app ya counter ke daam se alag ho sakta hai.",
    },
    "ask_pincode": {
        "en": "Tell me your pincode and I'll narrow it down for your area.",
        "hinglish": "Apna pincode bata dein, main aapke area ke hisaab se dekh lungi.",
    },
    # --- ASK / DECLINE
    "ask_no_connector": {
        "en": "I can't place orders inside apps yet. I can look up prices or the menu on the web instead. Want that?",
        "hinglish": "Abhi main apps ke andar order nahi laga sakti. Web par daam ya menu dekh sakti hoon. Chahiye?",
    },
    "ask_generic": {
        "en": "I want to get this right. Could you tell me a little more about what you need?",
        "hinglish": "Main ise sahi karna chahti hoon. Thoda aur bata dein ki aapko kya chahiye?",
    },
    "ask_unsure_call": {
        "en": "Just to be sure before I act: what exactly should I find out, and for which place?",
        "hinglish": "Karne se pehle pakka kar lun: exactly kya pata karna hai, aur kis jagah ke liye?",
    },
    "decline": {
        "en": "I can't do that one myself yet. Tell me a bit more and I will find the nearest thing I can do, or you can paste the details here.",
        "hinglish": "Ye main abhi khud nahi kar sakti. Thoda aur bata dein, main sabse paas ka kaam dhoondhti hoon, ya details yahin paste kar dein.",
    },
    # --- engine "needs info" line: only the call variant says call
    "needs_info_call": {
        "en": "Before I call, I need: {missing}",
        "hinglish": "Call karne se pehle mujhe chahiye: {missing}",
    },
    "needs_info": {
        "en": "To get this done, I need: {missing}",
        "hinglish": "Yeh karne ke liye mujhe chahiye: {missing}",
    },
}  # fmt: skip


def line(key: str, lang: str | None = "hinglish", **kw: str) -> str:
    row = LINES[key]
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**kw) if kw else text


def where_label(retailer: str | None, lang: str | None = "hinglish") -> str:
    if retailer:
        return retailer.title()
    return "the web" if lang == "en" else "web"


def ack_line(approach: Approach, retailer: str | None = None, lang: str | None = "hinglish") -> str:
    """The one 'on it' line. Names the approach; mentions calls only for CALL_VENDORS."""
    if approach == Approach.WEB_LOOKUP:
        return line("ack_web", lang, where=where_label(retailer, lang))
    if approach == Approach.APP_OR_CONNECTOR:
        return line("ack_app", lang, where=where_label(retailer, lang))
    if approach == Approach.CALL_VENDORS:
        return line("ack_call", lang)
    return line("ack_answer", lang)


def needs_info_line(missing: list[str], *, call_in_plan: bool, lang: str | None = "en") -> str:
    items = ", ".join(m.replace("_", " ") for m in missing)
    return line("needs_info_call" if call_in_plan else "needs_info", lang, missing=items)


def guard_text(text: str | None, *, call_in_plan: bool, fallback: str) -> str:
    """Model-written text may not talk about calling unless the plan has a call."""
    if text and (call_in_plan or not mentions_call(text)):
        return text
    return fallback
