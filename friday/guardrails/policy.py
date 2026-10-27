# ruff: noqa: E501
"""The policy table: category -> action, decided by code (docs/CHATBOT_GUARDRAILS.md).

``legacy`` categories are behaviours that already shipped (they stay ON under
``FRIDAY_GUARDRAILS_ENABLED``); the rest are NEW and run only when
``FRIDAY_GUARDRAILS_NEW_CATEGORIES`` is on. ``phase``: ``pre`` runs before the chatbot flows,
``post`` after them (so a pending question still gets its answer) and before the brain.
"""

from __future__ import annotations

from dataclasses import dataclass

from friday.guardrails.models import Action, Category


@dataclass(frozen=True)
class Policy:
    action: Action
    legacy: bool
    phase: str  # pre | post
    reply_key: str | None  # id in guardrails.copy (or chatbot.copy for legacy); None: no reply
    strike: bool = False  # counts toward the abuse mute
    audit_snippet: bool = True  # False: never keep even a masked snippet (sensitive topics)
    note: str = ""


POLICY: dict[Category, Policy] = {
    Category.EMERGENCY: Policy(Action.ESCALATE, True, "pre", "safety_emergency", audit_snippet=False,
                               note="112 line before anything else; new extra phrases need the new-categories switch"),
    Category.SELF_HARM: Policy(Action.ESCALATE, False, "pre", "self_harm", audit_snippet=False,
                               note="caring line + Tele-MANAS/112 (numbers to be verified); legacy emergency still covers the old phrases"),
    Category.MEDICAL_ADVICE: Policy(Action.REFUSE, True, "pre", "safety_medicine",
                                    note="no medicine or dose; offers a clinic call"),
    Category.MINORS: Policy(Action.REDIRECT, False, "pre", "minors", audit_snippet=False,
                            note="stops calls, payments, bookings for a user who says they are under 18"),
    Category.LEGAL_ADVICE: Policy(Action.REDIRECT, False, "pre", "legal_advice", note="lawyer, not advice"),
    Category.FINANCIAL_ADVICE: Policy(Action.REDIRECT, False, "pre", "financial_advice",
                                      note="no investment, loan or tax advice"),
    Category.FAKE_DOCUMENTS: Policy(Action.REFUSE, True, "pre", "refuse_forgery", strike=True,
                                    note="legacy fake-bill rule; new forgery and scam phrases use guardrails.fake_documents"),
    Category.HARASSMENT_ABUSE: Policy(Action.REFUSE, False, "pre", "harassment_abuse", strike=True),
    Category.ADULT: Policy(Action.REFUSE, False, "pre", "adult", strike=True),
    Category.ILLEGAL: Policy(Action.REFUSE, False, "pre", "illegal", strike=True),
    Category.PRIVACY_OTHERS: Policy(Action.REFUSE, False, "pre", "privacy_others", strike=True),
    Category.PROMPT_INJECTION: Policy(Action.REFUSE, False, "pre", "prompt_injection", strike=True),
    Category.PROHIBITED_ACTION: Policy(Action.REDIRECT, False, "pre", "prohibited_action",
                                       note="Friday never pays or handles OTP/PIN/card; offers a QR or link"),
    Category.SENSITIVE_CODES: Policy(Action.REFUSE, False, "pre", "sensitive_payment", audit_snippet=False,
                                     note="login OTP accepted only with a pending login; everything else refused"),
    Category.OUT_OF_SCOPE: Policy(Action.REDIRECT, True, "post", "offtopic",
                                  note="legacy general-knowledge redirect; politics/religion and identity are new"),
    Category.SMALL_TALK: Policy(Action.ALLOW, False, "post", None, note="one warm line, no long chit-chat (flows decide)"),
    Category.FACTUAL: Policy(Action.ALLOW, True, "post", None, note="sums, time and date computed in code"),
    Category.RATE_LIMITED: Policy(Action.REFUSE, False, "pre", "rate_limited", note="volume and repeat gate, strikes mute"),
    Category.IN_SCOPE: Policy(Action.ALLOW, True, "pre", None),
}

# reply-side disclaimers (check_reply): domain -> copy key
DISCLAIMERS = {
    "medical": "disclaimer_medical",
    "legal": "disclaimer_legal",
    "financial": "disclaimer_financial",
}
