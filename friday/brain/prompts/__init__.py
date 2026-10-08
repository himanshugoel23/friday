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

__all__ = [
    "CACHE_BREAK",
    "PERSONA",
    "dump_json",
    "extract_input",
    "persona_block",
    "render_input",
    "system_prompt",
]

# Marker splitting a system prompt into cacheable blocks: [static rules] [per-call
# stable data]. AnthropicLLM turns each block into a cache_control breakpoint.
CACHE_BREAK = "\n<<<FRIDAY_CACHE_BREAK>>>\n"

_INPUT = re.compile(r"<input>\s*(.*?)\s*</input>", re.S)


def dump_json(payload: dict[str, Any]) -> str:
    """Compact, deterministic JSON with ``<``/``>`` escaped (``\\u003c``), so untrusted
    text inside the payload can never close or forge a ``<input>``/``<data>`` block."""
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    return body.replace("<", "\\u003c").replace(">", "\\u003e")


def render_input(payload: dict[str, Any], instruction: str = "", tag: str = "input") -> str:
    head = f"{instruction.strip()}\n\n" if instruction else ""
    return f"{head}<{tag}>\n{dump_json(payload)}\n</{tag}>"


def extract_input(text: str, tag: str = "input") -> dict[str, Any] | None:
    rx = _INPUT if tag == "input" else re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.S)
    matches = rx.findall(text or "")
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
