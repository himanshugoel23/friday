# ruff: noqa: E501
"""Sarvam chat model for the live call-turn job, plus the router that sends ONLY that job to it.

Why: the call-turn job (classify the vendor's reply into the closed intent set) is tiny, but from the
Bangalore server a tiny OpenAI request takes 1.3-1.5 s (docs/LATENCY.md). Sarvam hosts models in
India. Measured 2026-10-12 on the playbook understanding task with ``sarvam-105b-conversations``
+ structured output: 10/10 correct, p50 ~455 ms even from a US machine.

Facts that shaped this file (checked against the live API):
* ``POST https://api.sarvam.ai/v1/chat/completions`` with ``api-subscription-key`` works; ``/v2`` needs beta access.
* ``sarvam-105b`` is a reasoning model: with a small ``max_tokens`` it spends everything thinking and returns an
  EMPTY answer. ``sarvam-105b-conversations`` answers directly, so that is the model used here.
* ``response_format`` json_schema (non-strict) is honoured.

Safety: ``RoutedLLM`` falls back to the normal provider if Sarvam errors or times out, so a Sarvam problem
costs time on that turn, never the call. Only the purposes in ``fast_purposes`` are routed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

import httpx

from friday.brain.openai_llm import _validate_json
from friday.core.interfaces import LLMMessage, LLMResponse, MediaBlob, ProviderError
from friday.core.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.sarvam.ai"
DEFAULT_MODEL = "sarvam-105b-conversations"
_NOTE = (
    "\nReply with ONLY the JSON object. OMIT every field that does not apply (never write null "
    "or []). No explanations."
)


class SarvamLLM:
    provider = "sarvam"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 3.0,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._client = httpx.AsyncClient(
            base_url=base_url, headers={"api-subscription-key": api_key}, transport=transport
        )
        self.repairs = 0
        self.latency_ms: list[float] = []

    async def warm(self) -> None:
        """Open the connection (a free request) so the first live turn skips the handshake."""
        try:
            await self._client.get("/", timeout=3.0)
        except Exception as e:  # noqa: BLE001
            log.info("sarvam llm warm-up skipped: %s", type(e).__name__)

    async def _once(self, body: dict[str, Any]) -> tuple[str, str | None, int, int]:
        t0 = time.perf_counter()
        try:
            r = await self._client.post("/v1/chat/completions", json=body, timeout=self.timeout_s)
        except httpx.HTTPError as e:
            raise ProviderError("sarvam", f"network error: {type(e).__name__}", retryable=True) from e
        ms = (time.perf_counter() - t0) * 1000
        self.latency_ms.append(ms)
        if r.status_code >= 400:
            raise ProviderError(
                "sarvam", f"HTTP {r.status_code}", retryable=r.status_code in (408, 429, 500, 502, 503)
            )
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        log.info(
            "llm sarvam model=%s in=%s out=%s latency_ms=%.0f",
            body.get("model"), usage.get("prompt_tokens"), usage.get("completion_tokens"), ms,
        )
        return (
            text, choice.get("finish_reason"),
            int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
        )

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        purpose: str = "general",
        model: str | None = None,
        max_tokens: int = 1024,
        effort: Any = None,
        json_schema: dict | None = None,
        attachments: Sequence[MediaBlob] = (),
    ) -> LLMResponse:
        if attachments:
            raise ProviderError("sarvam", "attachments are not supported")
        from friday.brain.prompts import CACHE_BREAK

        head, _, tail = system.partition(CACHE_BREAK)
        sys_text = head.rstrip() + (_NOTE if json_schema else "") + (
            ("\n" + tail.replace(CACHE_BREAK, "\n")) if tail else ""
        )
        schema = None
        if json_schema:
            schema = dict(json_schema)
            if "intent" in schema.get("properties", {}):
                schema["required"] = ["intent"]  # everything else may be omitted (fewer tokens)
        body: dict[str, Any] = {
            "model": self.model,  # the router's model name is an OpenAI/Claude one: not ours
            "temperature": 0,
            "max_tokens": max(max_tokens, 160),
            "messages": [
                {"role": "system", "content": sys_text},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "friday_output", "strict": False, "schema": schema},
            }
        text, finish, in_tok, out_tok = await self._once(body)
        if schema is not None and (err := _validate_json(text, schema)):
            self.repairs += 1
            log.warning("sarvam %s: structured output invalid (%s); one repair retry", purpose, err)
            body["messages"] = [
                *body["messages"],
                {"role": "assistant", "content": text[:1500]},
                {"role": "user", "content": f"That did not match the schema ({err}). Reply again "
                 "with ONLY the corrected JSON object."},
            ]
            text, finish, in2, out2 = await self._once(body)
            in_tok, out_tok = in_tok + in2, out_tok + out2
            if err2 := _validate_json(text, schema):
                raise ProviderError("sarvam", f"invalid structured output ({purpose}): {err2}")
        return LLMResponse(
            text=text, model=self.model, input_tokens=in_tok, output_tokens=out_tok,
            stop_reason=finish,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class RoutedLLM:
    """Sends the fast purposes to ``fast`` and everything else to ``primary``; falls back to
    ``primary`` when ``fast`` fails, so the call never depends on the spare vendor."""

    def __init__(self, primary: Any, fast: Any, fast_purposes: frozenset[str]) -> None:
        self.primary = primary
        self.fast = fast
        self.fast_purposes = fast_purposes
        self.fallbacks = 0

    async def complete(self, *, purpose: str = "general", **kw: Any) -> LLMResponse:
        if purpose in self.fast_purposes:
            try:
                return await self.fast.complete(purpose=purpose, **kw)
            except ProviderError as e:
                self.fallbacks += 1
                log.warning("fast llm failed for %s (%s); using %s", purpose, e, "primary")
        return await self.primary.complete(purpose=purpose, **kw)

    async def warm(self) -> None:
        await asyncio.gather(
            *(x.warm() for x in (self.primary, self.fast) if hasattr(x, "warm")),
            return_exceptions=True,
        )

    def __getattr__(self, item: str) -> Any:  # usage, repairs, batch helpers ... from the primary
        return getattr(self.primary, item)

    async def aclose(self) -> None:
        for x in (self.primary, self.fast):
            close = getattr(x, "aclose", None)
            if close is not None:
                await close()


def route_call_turns(llm: Any, settings: Any) -> Any:
    """Wrap ``llm`` so call turns go to Sarvam when ``FRIDAY_LLM_CALL_TURN_PROVIDER=sarvam``."""
    if getattr(settings, "llm_call_turn_provider", "default") != "sarvam" or not settings.sarvam_api_key:
        return llm
    if getattr(llm, "provider", None) == "fake":  # tests and the simulator never call a real vendor
        return llm
    fast = SarvamLLM(
        settings.sarvam_api_key.get_secret_value(),
        model=settings.sarvam_llm_model,
        timeout_s=settings.sarvam_llm_timeout_s,
    )
    return RoutedLLM(llm, fast, frozenset({"call_turn"}))
