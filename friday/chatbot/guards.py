"""Compatibility shim: the Instinct-review guards now live in ``friday.guardrails.legacy``
(docs/GUARDRAILS_MODULE.md). Same names, same behaviour; nothing is duplicated here."""

from friday.guardrails.legacy import language_request, quick_answer, safety_kind

__all__ = ["language_request", "quick_answer", "safety_kind"]
