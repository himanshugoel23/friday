"""Compatibility shim: the scope test and the masking helper now live in
``friday.guardrails.scope`` (docs/GUARDRAILS_MODULE.md). Same names, same behaviour."""

from friday.guardrails.scope import IN_SCOPE, is_out_of_scope, mask_numbers

__all__ = ["IN_SCOPE", "is_out_of_scope", "mask_numbers"]
