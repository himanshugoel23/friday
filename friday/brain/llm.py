"""Anthropic implementation of ``LLMClient`` (official ``anthropic`` SDK, async).

* Default model ``Settings.llm_model`` (claude-opus-5-5); live call turns pass
  ``Settings.llm_fast_model`` (claude-haiku-5-5).
* ``json_schema`` -> structured outputs (``output_config.format``); the brain
  passes schemas already made strict by ``friday.brain.schemas.strict_schema``.
* ``attachments`` -> image / PDF / plain-text content blocks (menus, quote photos).
* No ``temperature`` / ``budget_tokens`` (rejected by current models); depth is
  controlled with ``output_config.effort``.
* Opus/Sonnet/Fable requests opt into server-side refusal fallbacks
  (``fallbacks: "default"``); Haiku has none, so a refusal surfaces as a
  non-retryable ``ProviderError`` and the brain falls back to its deterministic path.
* Retries: the SDK retries 408/409/429/5xx/connection errors ``llm_max_retries``
  times; anything left is normalised to ``ProviderError``.
* Token + estimated cost accounting per ``purpose`` (``usage`` attribute, DEBUG log).
"""

from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anthropic

from friday.core.interfaces import Effort, LLMMessage, LLMResponse, ProviderError
from friday.core.logging import get_logger
from friday.core.models import MediaBlob

if TYPE_CHECKING:
    from friday.core.config import Settings
    from friday.core.container import Container

log = get_logger(__name__)

# USD per 1M tokens (input, output) - for internal cost estimates only.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
}
USD_TO_INR = 84.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Short, latency-critical purposes get a tight per-request timeout so the brain
# can fall back to its deterministic policy instead of leaving a caller in silence.
_FAST_TIMEOUT_S = {"call_turn": 6.0, "translate": 6.0, "sim_business": 8.0}


@dataclass
class UsageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_inr: float = 0.0


def estimate_cost_inr(model: str, input_tokens: int, output_tokens: int) -> float:
    price = next((p for k, p in PRICING_USD_PER_MTOK.items() if model.startswith(k)), (4.0, 20.0))
    usd = input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]
    return round(usd * USD_TO_INR, 4)


def _supports_server_fallback(model: str) -> bool:
    return model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5"))


def attachment_block(media: MediaBlob) -> dict[str, Any]:
    mime = (media.mime or "").split(";")[0].strip().lower()
    data = base64.standard_b64encode(media.data).decode("ascii")
    if mime in _IMAGE_MIMES:
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
    if mime == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    if mime.startswith("text/"):
        return {
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": media.data.decode("utf-8", errors="replace"),
            },
        }
    raise ProviderError("anthropic", f"unsupported attachment type {mime!r}")


class AnthropicLLM:
    """``LLMClient`` over the Anthropic Messages API."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        default_model: str = "claude-opus-5-5",
        fast_model: str = "claude-haiku-5-5",
        timeout_s: float = 30.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self.fast_model = fast_model
        self.timeout_s = timeout_s
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )
        self.usage: dict[str, UsageTotals] = defaultdict(UsageTotals)

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[LLMMessage],
        purpose: str = "general",
        model: str | None = None,
        max_tokens: int = 1024,
        effort: Effort | None = None,
        json_schema: dict | None = None,
        attachments: Sequence[MediaBlob] = (),
    ) -> LLMResponse:
        model = model or self.default_model
        api_messages = self._messages(messages, attachments)
        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": api_messages,
        }
        if output_config:
            kwargs["output_config"] = output_config
        timeout = _FAST_TIMEOUT_S.get(purpose)
        client = self._client.with_options(timeout=timeout) if timeout else self._client
        try:
            if _supports_server_fallback(model):
                response = await client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                response = await client.messages.create(**kwargs)
        except anthropic.BadRequestError as e:
            raise ProviderError("anthropic", f"bad request: {e.message}") from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise ProviderError("anthropic", "authentication failed") from e
        except anthropic.NotFoundError as e:
            raise ProviderError("anthropic", f"model or endpoint not found: {model}") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("anthropic", "rate limited", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(
                "anthropic", f"api error {e.status_code}", retryable=e.status_code >= 500
            ) from e
        except anthropic.APITimeoutError as e:
            raise ProviderError("anthropic", "timeout", retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic", "connection error", retryable=True) from e

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise ProviderError("anthropic", f"model declined ({purpose})")
        text = "".join(
            getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text"
        )
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        served = getattr(response, "model", model) or model
        totals = self.usage[purpose]
        totals.calls += 1
        totals.input_tokens += in_tok
        totals.output_tokens += out_tok
        totals.cost_inr += estimate_cost_inr(served, in_tok, out_tok)
        log.debug(
            "llm purpose=%s model=%s in=%d out=%d stop=%s cost_inr=%.4f",
            purpose, served, in_tok, out_tok, stop_reason,
            estimate_cost_inr(served, in_tok, out_tok),
        )
        if stop_reason == "max_tokens" and json_schema:
            raise ProviderError("anthropic", f"output truncated ({purpose})", retryable=True)
        return LLMResponse(
            text=text,
            model=served,
            input_tokens=in_tok,
            output_tokens=out_tok,
            stop_reason=stop_reason,
        )

    @staticmethod
    def _messages(
        messages: Sequence[LLMMessage], attachments: Sequence[MediaBlob]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in messages]
        if attachments:
            idx = next((i for i in range(len(out)) if out[i]["role"] == "user"), None)
            if idx is None:
                out.insert(0, {"role": "user", "content": ""})
                idx = 0
            blocks = [attachment_block(a) for a in attachments]
            blocks.append({"type": "text", "text": out[idx]["content"] or "See attached."})
            out[idx] = {"role": "user", "content": blocks}
        return out

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def build_anthropic_llm(c: Container) -> AnthropicLLM:
    s: Settings = c.settings
    key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
    return AnthropicLLM(
        api_key=key,
        default_model=s.llm_model,
        fast_model=s.llm_fast_model,
        timeout_s=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )
