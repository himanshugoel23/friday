"""Chatbot guardrails: code, not the language model, decides what Friday will and will not do.

Entry points: :func:`check` (every inbound message, before any model) and :func:`check_reply`
(every outgoing model reply). See docs/GUARDRAILS_MODULE.md.
"""

from friday.guardrails.engine import (
    LEGACY_CATEGORIES,
    NEW_CATEGORIES,
    Guardrails,
    GuardrailsConfig,
    check,
    check_reply,
    default_engine,
)
from friday.guardrails.models import Action, Category, Context, Decision, ReplyDecision

__all__ = [
    "LEGACY_CATEGORIES", "NEW_CATEGORIES", "Action", "Category", "Context", "Decision",
    "Guardrails", "GuardrailsConfig", "ReplyDecision", "check", "check_reply", "default_engine",
]
