# ruff: noqa: E501
"""The vocabulary of the guardrails: categories, actions, the context and the decision.

Policy is decided by CODE from these closed lists, never improvised by a language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Category(StrEnum):
    EMERGENCY = "emergency"  # medical emergency (chest pain, cannot breathe, fire)
    MEDICAL_ADVICE = "medical_advice"  # which medicine / dose
    MINORS = "minors"  # the user says they are under 18
    SELF_HARM = "self_harm"  # wants to die / hurt themselves
    LEGAL_ADVICE = "legal_advice"
    FINANCIAL_ADVICE = "financial_advice"  # investments, loans, tax, insurance picks
    FAKE_DOCUMENTS = "fake_documents"  # fake bill, forged certificate, fraud
    HARASSMENT_ABUSE = "harassment_abuse"  # scare / threaten a person; slurs at Friday
    ADULT = "adult"
    ILLEGAL = "illegal"  # drugs, weapons, hacking, evading police
    PRIVACY_OTHERS = "privacy_others"  # someone else's data, tracking a person
    PROMPT_INJECTION = "prompt_injection"
    PROHIBITED_ACTION = "prohibited_action"  # send OTP, pay for me, save card number
    SENSITIVE_CODES = "sensitive_codes"  # OTP / PIN / CVV / card number / password typed in chat
    OUT_OF_SCOPE = "out_of_scope"
    SMALL_TALK = "small_talk"
    FACTUAL = "factual"  # sums, time, date: computed in code
    RATE_LIMITED = "rate_limited"  # abuse / volume gate
    IN_SCOPE = "in_scope"  # nothing matched: the normal flows run


class Action(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_DISCLAIMER = "allow_with_disclaimer"
    REDIRECT = "redirect"  # decline the ask, offer the closest useful thing
    REFUSE = "refuse"  # one calm line, no lecture
    ESCALATE = "escalate"  # to emergency numbers / a helpline / a human


@dataclass
class Context:
    """Who is asking and when. ``phase``: ``pre`` (before the flows: safety, harm, volume),
    ``post`` (after the flows, before the brain: out of scope, quick facts) or ``all``."""

    user_id: str | None = None
    lang: str = "hinglish"
    now: datetime | None = None
    phase: str = "all"
    # numbers the reply may contain (from tools or the user); None = do not check numbers
    known_numbers: frozenset[str] | None = None
    channel: str = "whatsapp"
    is_minor: bool = False  # the caller knows (profile) that the user is under 18


@dataclass
class Decision:
    category: Category
    action: Action
    rule: str = ""  # which rule fired (for the audit log and the eval report)
    reply_id: str | None = None  # id of the fixed wording (guardrails.copy or chatbot.copy)
    reply: str | None = None  # the rendered text in ``Context.lang`` (None: nothing to say)
    quick: tuple[str, dict[str, str]] | None = None  # (copy key, fields) for a factual answer
    silent: bool = False  # muted user: send nothing
    audit: dict[str, object] | None = None  # masked record for the audit log (None: nothing to log)
    route: str | None = None  # "browser_worker" when a login code was handed on (never the code)

    @property
    def handled(self) -> bool:
        """True when the pipeline must stop here and send ``reply`` (or stay silent)."""
        return (
            self.silent
            or self.action in (Action.REFUSE, Action.REDIRECT, Action.ESCALATE)
            or self.quick is not None
            or self.reply is not None
        )


@dataclass
class ReplyDecision:
    action: Action  # ALLOW, ALLOW_WITH_DISCLAIMER or REFUSE (replaced)
    text: str
    rules: list[str] = field(default_factory=list)
