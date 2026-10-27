# ruff: noqa: E501
"""Every USER-FACING line of the proof feature. STATUS: PENDING_FOUNDER_APPROVAL for all of them.

Hear-before-change (CLAUDE.md rule 3): nothing here may reach a real user until the founder has
approved the wording; the feature switch (``FRIDAY_PROOF_ENABLED``) stays OFF until then. No spoken
lines exist in this feature. Code builds user text only through ``t()``; evidence text from vendors
is never interpolated except the structured fields named below (reference, time, name).
"""

from __future__ import annotations

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "en")
DEFAULT_LANGUAGE = "en"

TEXTS: dict[str, dict[str, str]] = {
    # proof lines appended to a proven message (one line each)
    "proof.ref": {"hinglish": "Reference: {ref}", "en": "Reference: {ref}"},
    "proof.call": {
        "hinglish": "Proof: maine {who} ko call kiya ({when}), baat {duration} chali.",
        "en": "Proof: I called {who} ({when}); the call lasted {duration}.",
    },
    "proof.screen": {
        "hinglish": "Proof: confirmation page ka screenshot hai.",
        "en": "Proof: I have a screenshot of the confirmation page.",
    },
    "proof.vendor_said": {
        "hinglish": "{who} ne call par confirm kiya.",
        "en": "{who} confirmed on the call.",
    },
    "proof.no_ref_exists": {
        "hinglish": "Unhone koi reference number nahi diya.",
        "en": "They did not give a reference number.",
    },
    # partial / unproven heads (strict mode replaces the model's summary with these)
    "partial.head": {
        "hinglish": "Lagta hai ho gaya, lekin poora proof nahi mila.",
        "en": "It looks like this went through, but I do not have full proof yet.",
    },
    "unproven.head": {
        "hinglish": "Mujhe lagta hai kaam hua, par mere paas koi proof nahi hai.",
        "en": "I think it worked, but I have no proof.",
    },
    "unproven.offer": {
        "hinglish": "Kya main ek baar dobara check karun?",
        "en": "Want me to check once more?",
    },
    # what is missing (one line per code in policy.MISSING_*)
    "missing.reference": {
        "hinglish": "Kami: reference ya order number nahi mila.",
        "en": "Missing: a reference or order number.",
    },
    "missing.observed": {
        "hinglish": "Kami: meri taraf se koi record (call ya screenshot) nahi hai.",
        "en": "Missing: a record of my own (call or screenshot).",
    },
    "missing.vendor_word": {
        "hinglish": "Kami: dukaan ki taraf se saaf confirmation nahi mili.",
        "en": "Missing: a clear confirmation from the business.",
    },
    "missing.any": {
        "hinglish": "Kami: koi bhi sabut nahi mila.",
        "en": "Missing: any evidence at all.",
    },
    # soft claims (information tasks): the message is kept, one note is added
    "soft.note": {
        "hinglish": "Note: yeh jaankari call par boli gayi thi, usse alag koi proof nahi hai.",
        "en": "Note: this is what they said on the call; I have no separate proof.",
    },
    # human fallback after two failed attempts
    "fallback.human": {
        "hinglish": "Do koshish ke baad bhi nahi hua. Aap seedha {contact} se baat kar sakte hain.",
        "en": "Two tries did not work. You can talk to {contact} directly.",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **fields: str) -> str:
    row = TEXTS[key]
    text = row.get(lang) or row[DEFAULT_LANGUAGE]
    return text.format(**fields) if fields else text
