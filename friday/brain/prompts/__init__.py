"""Persona + system prompts, and the ``<input>`` payload convention shared by the
real and the fake LLM: the brain puts all per-request data as JSON inside
``<input>...</input>`` in the user message; the deterministic fake LLM parses the
same block, so both paths see exactly the same request.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .persona import PERSONA, persona_block
from .system import system_prompt

__all__ = ["PERSONA", "extract_input", "persona_block", "render_input", "system_prompt"]

_INPUT = re.compile(r"<input>\s*(.*?)\s*</input>", re.S)


def render_input(payload: dict[str, Any], instruction: str = "") -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    head = f"{instruction.strip()}\n\n" if instruction else ""
    return f"{head}<input>\n{body}\n</input>"


def extract_input(text: str) -> dict[str, Any] | None:
    matches = _INPUT.findall(text or "")
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
