"""Connection warm-up: the first live call turn must not pay a cold TLS handshake."""

from __future__ import annotations

from typing import Any


async def warm_llm(c: Any) -> None:
    """Best effort, never raises: opens the LLM provider's connection (a free request)."""
    try:
        llm = c.get("llm")
        warm = getattr(llm, "warm", None)
        if warm is not None:
            await warm()
    except Exception:  # noqa: BLE001 - warm-up is an optimisation only
        return
