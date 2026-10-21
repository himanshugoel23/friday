# ruff: noqa: E501
"""Streaming adapters for the existing chat clients, and a fake for tests.

``OpenAIChatStream`` and ``SarvamChatStream`` wrap an already-built ``OpenAILLM`` / ``SarvamLLM``
(same key, same model routing, same prompts) and expose ``stream(...)``: an async generator of text
deltas. They add NOTHING to the normal ``complete`` path and never retry: on any error they raise,
and the caller (``FridayBrain.next_call_action_streamed``) runs the ordinary non-streaming call.

UNVERIFIED against the live vendors in this workstream (no network in tests): the wire format is
the documented OpenAI Chat Completions ``stream=true`` (SSE ``choices[0].delta.content``) and the
OpenAI-compatible Sarvam ``/v1/chat/completions`` with ``stream: true``. Whether Sarvam honours
``response_format`` json_schema together with ``stream`` is exactly what a live probe must show.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- OpenAI
class OpenAIChatStream:
    provider = "openai"

    def __init__(self, llm: Any) -> None:
        self.llm = llm  # a friday.brain.openai_llm.OpenAILLM

    async def stream(
        self, *, system: str, messages: Sequence[Any], purpose: str = "call_turn",
        model: str | None = None, max_tokens: int = 1024, effort: Any = None,
        json_schema: dict | None = None,
    ) -> AsyncIterator[str]:
        from friday.brain import openai_llm as o

        llm = self.llm
        model = model or llm.default_model
        notes = ""
        strict = True
        relaxed = bool(json_schema and purpose == "call_turn" and llm.relaxed_call_schema)
        if relaxed:
            json_schema, strict = o.relax_call_schema(json_schema), False
        if json_schema:
            notes = (o._NOTES_FORMAT_RELAXED if relaxed else o._NOTES_FORMAT) + (
                o._NOTES_CALL_TURN if purpose == "call_turn" else ""
            )
        api_messages = llm._messages(system, messages, (), notes)
        reasoning = llm._effort_for(purpose, model, effort)
        cap = max_tokens + (o._REASONING_HEADROOM.get(reasoning or "none", 0) if reasoning else 0)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_completion_tokens": cap,
            "prompt_cache_key": f"friday:{purpose}",
            "stream": True,
        }
        if reasoning:
            kwargs["reasoning_effort"] = reasoning
        if json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "friday_output", "strict": strict, "schema": json_schema},
            }
        t0 = time.monotonic()
        try:
            resp = await llm._client.with_options(timeout=llm._budget_s(purpose)).chat.completions.create(**kwargs)
            first = True
            async for chunk in resp:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0].delta, "content", None)
                if getattr(choices[0].delta, "refusal", None):
                    raise ProviderError("openai", f"model declined ({purpose})")
                if delta:
                    if first:
                        first = False
                        log.info("llm openai stream first token %.0f ms (purpose=%s)",
                                 (time.monotonic() - t0) * 1000, purpose)
                    yield delta
                if getattr(choices[0], "finish_reason", None) == "length":
                    raise ProviderError("openai", f"output truncated ({purpose})", retryable=True)
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 - normalised; the caller falls back to complete()
            raise ProviderError("openai", f"stream failed: {type(e).__name__}", retryable=True) from e


# --------------------------------------------------------------------------- Sarvam
class SarvamChatStream:
    provider = "sarvam"

    def __init__(self, llm: Any) -> None:
        self.llm = llm  # a friday.brain.sarvam_llm.SarvamLLM

    async def stream(
        self, *, system: str, messages: Sequence[Any], purpose: str = "call_turn",
        model: str | None = None, max_tokens: int = 1024, effort: Any = None,
        json_schema: dict | None = None,
    ) -> AsyncIterator[str]:
        from friday.brain import sarvam_llm as s
        from friday.brain.prompts import CACHE_BREAK

        llm = self.llm
        head, _, tail = system.partition(CACHE_BREAK)
        sys_text = head.rstrip() + (s._NOTE if json_schema else "") + (
            ("\n" + tail.replace(CACHE_BREAK, "\n")) if tail else ""
        )
        body: dict[str, Any] = {
            "model": llm.model,
            "temperature": 0,
            "max_tokens": max(max_tokens, 160),
            "stream": True,
            "messages": [
                {"role": "system", "content": sys_text},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
        }
        if json_schema is not None:
            schema = dict(json_schema)
            if "intent" in schema.get("properties", {}):
                schema["required"] = ["intent"]
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "friday_output", "strict": False, "schema": schema},
            }
        t0 = time.monotonic()
        try:
            async with llm._client.stream("POST", "/v1/chat/completions", json=body, timeout=llm.timeout_s) as r:
                if r.status_code >= 400:
                    raise ProviderError("sarvam", f"HTTP {r.status_code}", retryable=r.status_code in (408, 429, 500, 502, 503))
                first = True
                async for line in r.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = ((json.loads(data).get("choices") or [{}])[0].get("delta") or {}).get("content")
                    except (ValueError, AttributeError, IndexError) as e:
                        raise ProviderError("sarvam", "bad stream chunk") from e
                    if delta:
                        if first:
                            first = False
                            log.info("llm sarvam stream first token %.0f ms (purpose=%s)",
                                     (time.monotonic() - t0) * 1000, purpose)
                        yield delta
        except ProviderError:
            raise
        except (httpx.HTTPError, TimeoutError) as e:
            raise ProviderError("sarvam", f"stream failed: {type(e).__name__}", retryable=True) from e


# --------------------------------------------------------------------------- picking one
def streaming_for(llm: Any, purpose: str = "call_turn") -> Any | None:
    """A streaming adapter for the client that would serve ``purpose`` (the OpenAI client, or the
    India-hosted Sarvam model when call turns are routed there). None = no streaming support
    (Anthropic client, the offline fake): the caller uses the normal path."""
    name = type(llm).__name__
    if name == "RoutedLLM":
        if purpose in getattr(llm, "fast_purposes", ()):
            return streaming_for(llm.fast, purpose)
        return streaming_for(llm.primary, purpose)
    if name == "OpenAILLM":
        return OpenAIChatStream(llm)
    if name == "SarvamLLM":
        return SarvamChatStream(llm)
    return None


# --------------------------------------------------------------------------- the fake
def json_chunks(text: str, size: int = 6) -> list[str]:
    """A JSON string cut into small deltas, the way a stream arrives."""
    return [text[i : i + size] for i in range(0, len(text), size)]


class FakeStreamingLLM:
    """Scripted stream for tests and the latency simulator: no network.

    ``chunks`` are yielded in order; ``delay_s`` is slept before each (``first_delay_s`` before the
    first = time to first token). ``fail_at=N`` raises ``ProviderError`` before chunk N (0 = at the
    start); ``fail_with`` overrides the exception. ``sleep`` can be a fake clock's sleep."""

    provider = "fake-stream"

    def __init__(
        self, chunks: Sequence[str], *, delay_s: float = 0.0, first_delay_s: float = 0.0,
        fail_at: int | None = None, fail_with: Exception | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.delay_s = delay_s
        self.first_delay_s = first_delay_s
        self.fail_at = fail_at
        self.fail_with = fail_with
        self.calls: list[dict[str, Any]] = []
        self.closed = 0
        self.yielded = 0

    async def stream(self, **kw: Any) -> AsyncIterator[str]:
        self.calls.append(kw)
        try:
            if self.fail_at == 0:
                raise self.fail_with or ProviderError("fake", "stream failed at start", retryable=True)
            await asyncio.sleep(self.first_delay_s)
            for i, c in enumerate(self.chunks):
                if self.fail_at is not None and i == self.fail_at:
                    raise self.fail_with or ProviderError("fake", "stream failed mid-way", retryable=True)
                if i:
                    await asyncio.sleep(self.delay_s)
                self.yielded += 1
                yield c
        finally:
            self.closed += 1
