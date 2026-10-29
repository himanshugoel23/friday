# ruff: noqa: E501
"""Every user-facing line of the style layer. STATUS: PENDING_FOUNDER_APPROVAL for all of them.

Hear-before-change (CLAUDE.md rule 3): nothing here may reach a real user until the founder has read the
lines in docs/STYLE_GUIDE.md and approved them; the switch ``FRIDAY_STYLE_LAYER_ENABLED`` stays OFF until
then. Chat text only: no spoken line lives here. Friday is female in Hinglish ("rahi hoon", "sakti hoon").
Placeholders are ``{name}`` format fields. Languages: ``en`` and Roman ``hinglish`` (Devanagari users get the
Roman lines until a Hindi variant is approved).
"""

from __future__ import annotations

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "en")

TEXTS: dict[str, dict[str, str]] = {
    # 1. fast ack, then a short status only if it is slow
    "ack": {"en": "On it. Checking {what} now.", "hinglish": "Ek minute, {what} check kar rahi hoon."},
    "status_slow": {
        "en": "Still on it. {what} is slow, a couple more minutes.",
        "hinglish": "{what} slow hai, abhi kuch minute aur lagenge.",
    },
    "status_step": {"en": "Right now: {step}.", "hinglish": "Abhi: {step}."},
    # 3. result shape
    "pick": {"en": "My pick: {name}, because {reason}.", "hinglish": "Meri pick: {name}, kyunki {reason}."},
    # 4. grouped questions with defaults
    "grouped_head": {
        "en": "A few quick details. Reply 'yes' to keep these, or send the ones to change:",
        "hinglish": "Kuch chhoti baatein. Sab sahi hai to 'haan' likhiye, ya jo badalna ho woh bhejiye:",
    },
    "grouped_row": {"en": "{label}: {default}?", "hinglish": "{label}: {default}?"},
    "assume": {"en": "Taking this as {thing}. Right?", "hinglish": "Main ise {thing} maan rahi hoon. Sahi?"},
    # 5. before anything irreversible
    "confirm_head": {"en": "Please check this before I go ahead:", "hinglish": "Aage badhne se pehle yeh dekh lijiye:"},
    "confirm_item": {"en": "Item: {item}", "hinglish": "Cheez: {item}"},
    "confirm_place": {"en": "Place: {place}", "hinglish": "Jagah: {place}"},
    "confirm_address": {"en": "Address: {address}", "hinglish": "Pata: {address}"},
    "confirm_fees": {"en": "Fees: {fees}", "hinglish": "Charges: {fees}"},
    "confirm_total": {"en": "Total: {total}", "hinglish": "Kul: {total}"},
    "confirm_next": {"en": "Next: {next_step}", "hinglish": "Phir: {next_step}"},
    "confirm_ask": {"en": "Shall I go ahead?", "hinglish": "Aage badhun?"},
    "cancelled": {
        "en": "Cancelled. Nothing was charged or booked.",
        "hinglish": "Cancel kar diya. Kuch charge ya book nahi hua.",
    },
    "cancelled_order": {
        "en": "Cancelled. Nothing was charged or ordered.",
        "hinglish": "Cancel kar diya. Kuch charge ya order nahi hua.",
    },
    # 7. honest limits, corrections
    "limit": {
        "en": "I can't {cant}. Here is what I can do instead: {alt}.",
        "hinglish": "Main {cant} nahi kar sakti. Iske badle main yeh kar sakti hoon: {alt}.",
    },
    "correction": {"en": "Correction: {fix}", "hinglish": "Sudhar: {fix}"},
    # 6. proof card
    "proof_head_done": {"en": "Done. Proof:", "hinglish": "Ho gaya. Proof:"},
    "proof_head_attempted": {"en": "Tried, but not finished. Here is what I saw:", "hinglish": "Koshish ki, par poora nahi hua. Yeh dikha:"},
    "proof_head_checkout": {
        "en": "Stopped at the payment step. Nothing was charged. Here is what I saw:",
        "hinglish": "Payment step par ruk gayi. Kuch charge nahi hua. Yeh dikha:",
    },
    "proof_head_failed": {"en": "That did not go through. Here is what I saw:", "hinglish": "Yeh nahi ho paya. Yeh dikha:"},
    "proof_what": {"en": "What: {v}", "hinglish": "Kya: {v}"},
    "proof_where": {"en": "Where: {v}", "hinglish": "Kahan: {v}"},
    "proof_when": {"en": "When: {v}", "hinglish": "Kab: {v}"},
    "proof_amount": {"en": "Amount: {v}", "hinglish": "Raqam: {v}"},
    "proof_ref": {"en": "Reference: {v}", "hinglish": "Reference: {v}"},
    "proof_link": {"en": "Link: {v}", "hinglish": "Link: {v}"},
    "proof_seen": {"en": "Saw: {v}", "hinglish": "Dikha: {v}"},
    "proof_shot": {"en": "Screenshot attached.", "hinglish": "Screenshot saath mein hai."},
    "proof_keep": {
        "en": "I keep this proof for {days} days. Say 'delete everything' to erase it sooner.",
        "hinglish": "Yeh proof {days} din rakhti hoon. Jaldi hatana ho to 'delete everything' likhiye.",
    },
}


def t(key: str, lang: str | None = "hinglish", **fields: str) -> str:
    row = TEXTS[key]
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**fields) if fields else text
