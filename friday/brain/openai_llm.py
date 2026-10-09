"""OpenAI (GPT) implementation of ``LLMClient`` (official ``openai`` SDK, async, Chat Completions).

Same contract and behaviours as ``AnthropicLLM`` (friday/brain/llm.py):

* Models are routed per purpose by the brain (``Settings.model_for`` -> GPT names when the
  provider is openai); ``default_model`` / ``fast_model`` apply only when ``model`` is missing.
* ``json_schema`` -> ``response_format`` json_schema with ``strict: true`` (the brain passes
  schemas already made strict by ``friday.brain.schemas.strict_schema``). The reply is parsed and
  validated against the schema; one repair retry, then ``ProviderError`` (the brain then uses its
  deterministic fallback).
* ``attachments`` -> ``image_url`` data-URI parts (jpeg/png/gif/webp), ``file`` parts for PDFs
  (``file_data`` data URI) and plain-text parts. Anything else raises ``ProviderError``.
* GPT-5 family: ``max_completion_tokens`` (reasoning tokens count against it, so a small
  per-effort headroom is added), no ``temperature``, ``reasoning_effort`` per purpose.
  Non-reasoning models (gpt-4.x) get neither ``reasoning_effort`` nor the headroom.
* Caching is automatic on OpenAI (prefix >= 1024 tokens). The brain already orders prompts
  [static rules][per-call stable data][volatile message]; ``CACHE_BREAK`` markers are stripped and
  ``prompt_cache_key`` keeps one purpose's requests on the same cache shard.
* Timeouts/retries: own loop (SDK retries off) with exponential backoff + jitter on 429/5xx/
  connection errors inside a TOTAL budget per purpose: live ``call_turn`` 8 s (default), so the
  brain degrades gracefully (deterministic policy) instead of leaving a caller in silence.
* Token, cached-token and ESTIMATED INR cost per purpose (``usage``; INFO log). Logs carry
  purpose/model/counts/latency only: never prompts, replies, attachments or keys.
* Every failure is normalised to ``ProviderError``. Message Batches are not implemented (the
  Anthropic-only ``submit_batch`` is absent; ``LLMDocumentExtractor.submit_batch`` reports that).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
import time
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import openai

from friday.core.interfaces import Effort, LLMMessage, LLMResponse, ProviderError
from friday.core.logging import get_logger
from friday.core.models import MediaBlob

from .llm import UsageTotals

if TYPE_CHECKING:
    from friday.core.config import Settings
    from friday.core.container import Container

log = get_logger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Purposes that run while a person is waiting on the phone (or similarly latency critical).
_FAST_BUDGET_S = {"translate": 6.0, "sim_business": 8.0}  # call_turn: Settings
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
# Extra completion tokens so hidden reasoning cannot eat the visible JSON budget.
_REASONING_HEADROOM = {"none": 0, "minimal": 128, "low": 256, "medium": 1024, "high": 2048}
_BACKOFF_BASE_S = 0.3
_MAX_RETRY_AFTER_S = 2.0
# Additive, GPT-only clarifications appended to the system prompt (the Claude prompts are
# unchanged). They restate output format and two points GPT got wrong in the live sample
# (language mirroring of Devanagari Hindi; ask_user is for the USER, not the business). They never
# relax a rule: the untrusted-data rule, approval rule and persona stay exactly as written.
_NOTES_FORMAT = (
    "\nProvider notes (output format only; the rules above still decide everything):\n"
    "Reply with ONLY the JSON object for the schema. Use null (or []) for fields that do not "
    "apply. Plain speakable words in any `text`: no markdown, no emojis, no lists.\n"
)
_NOTES_CALL_TURN = (
    "Language mirroring: if the last callee turn carries a `language` tag, your `language` MUST "
    "equal that tag and `text` must be in it (tag hi -> Hindi in Devanagari, en -> English, "
    "hinglish -> Roman-script Hindi-English mix).\n"
    "type=ask_user pauses the call to ask YOUR USER something. To ask the business a question "
    "(price, inclusions, slots) use type=say.\n"
)
_NOTES_INTERPRET = (
    "Task-type choices (when two fit): doctor/clinic/lab/pharmacy/physio appointments -> "
    "healthcare, not booking. Asking ONE named business a question (price, hours, availability) "
    "-> enquiry; quote only when the user wants quotes from several businesses to compare. "
    "Finding which shop has an item in stock -> stock_hunt; discovery is for finding "
    "businesses in general. running_late is only when the USER is late. A vendor/worker who "
    "is late or has not turned up (\"chase him\") -> service_coordination; "
    "chasing the status of finished/pending work -> status_chase. "
    "Problems with a company's service (telecom, bank, broadband, airline, e-commerce: Airtel, "
    "Jio, ...) -> customer_care; complaint is for a local vendor. A request to regularly call or "
    "check in on a family member -> new_task wellbeing_checkin (not remember).\n"
)
# Call turns need only these keys (the rest default safely when omitted: commits_booking=false).
_CALL_TURN_REQUIRED = ("type", "text", "language", "outcome", "commits_booking")
# Fallback when a model has no row in the price table (a mini-class guess; ESTIMATE).
_DEFAULT_PRICE = (0.75, 0.075, 4.50)


def relax_call_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Call-turn latency: output tokens dominate, and a strict schema forces ~10 null fields.
    Keep only the essential keys required (the brain's pydantic model defaults the rest)."""
    out = dict(schema)
    props = out.get("properties", {})
    out["required"] = [k for k in _CALL_TURN_REQUIRED if k in props]
    return out


def is_reasoning_model(model: str) -> bool:
    return model.startswith(_REASONING_PREFIXES)


def estimate_cost_inr(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    *,
    prices: dict[str, Sequence[float]],
    usd_to_inr: float = 84.0,
) -> float:
    """Internal ESTIMATE (never shown to users). ``input_tokens`` includes ``cached_tokens``;
    ``prices`` maps a model-name prefix to (input, cached input, output) USD per 1M tokens (the
    longest matching prefix wins). Verify the table against OpenAI's current pricing page."""
    match = max((k for k in prices if model.startswith(k)), key=len, default=None)
    p_in, p_cached, p_out = prices[match] if match else _DEFAULT_PRICE
    fresh = max(input_tokens - cached_tokens, 0)
    usd = (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1e6
    return round(usd * usd_to_inr, 4)


# ------------------------------------------------------------------ attachments
def attachment_part(media: MediaBlob) -> dict[str, Any]:
    mime = (media.mime or "").split(";")[0].strip().lower()
    if mime in _IMAGE_MIMES:
        data = base64.standard_b64encode(media.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{data}", "detail": "auto"},
        }
    if mime == "application/pdf":
        data = base64.standard_b64encode(media.data).decode("ascii")
        return {
            "type": "file",
            "file": {
                "filename": "document.pdf",
                "file_data": f"data:application/pdf;base64,{data}",
            },
        }
    if mime.startswith("text/"):
        text = media.data.decode("utf-8", errors="replace")
        return {"type": "text", "text": f"<data>\n{text}\n</data>"}
    raise ProviderError("openai", f"unsupported attachment type {mime!r}")


# ------------------------------------------------------------------ JSON-schema validation
def _resolve(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = root.get("$defs", {}).get(node["$ref"].split("/")[-1], {})
    return node


_TYPES: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def schema_error(value: Any, schema: dict[str, Any], root: dict[str, Any] | None = None,
                 path: str = "$") -> str | None:
    """First violation of the (strict-subset) JSON schema, as a path + reason that never
    contains the offending value; None when valid. Covers what ``strict_schema`` emits."""
    root = root or schema
    node = _resolve(schema, root)
    if "anyOf" in node:
        errs = [schema_error(value, o, root, path) for o in node["anyOf"]]
        return None if any(e is None for e in errs) else f"{path}: matches no allowed shape"
    if "enum" in node and value not in node["enum"]:
        return f"{path}: not an allowed value"
    if "const" in node and value != node["const"]:
        return f"{path}: not the allowed value"
    types = node.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_TYPES.get(t, lambda _v: True)(value) for t in names):
            return f"{path}: expected {'/'.join(names)}"
    if isinstance(value, dict):
        props = node.get("properties", {})
        for k in node.get("required", []):
            if k not in value:
                return f"{path}: missing '{k}'"
        if node.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    return f"{path}: unexpected '{k}'"
        for k, sub in props.items():
            if k in value and (e := schema_error(value[k], sub, root, f"{path}.{k}")):
                return e
    if isinstance(value, list) and "items" in node:
        for i, item in enumerate(value):
            if e := schema_error(item, node["items"], root, f"{path}[{i}]"):
                return e
    return None


def _validate_json(text: str, schema: dict[str, Any]) -> str | None:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return "not valid JSON"
    return schema_error(data, schema)


class OpenAILLM:
    """``LLMClient`` over the OpenAI Chat Completions API."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        default_model: str = "gpt-5.4-mini",
        fast_model: str = "gpt-5.4-mini",
        timeout_s: float = 30.0,
        call_turn_timeout_s: float = 8.0,
        max_retries: int = 2,
        reasoning_effort: dict[str, str] | None = None,
        default_reasoning_effort: str = "none",
        prices: dict[str, Sequence[float]] | None = None,
        usd_to_inr: float = 84.0,
        relaxed_call_schema: bool = False,
        client: Any | None = None,
    ) -> None:
        from friday.core.config import DEFAULT_OPENAI_PRICES_USD_PER_MTOK

        self.default_model = default_model
        self.fast_model = fast_model
        self.timeout_s = timeout_s
        self.call_turn_timeout_s = call_turn_timeout_s
        self.max_retries = max_retries
        self.reasoning_effort = dict(reasoning_effort or {})
        self.default_reasoning_effort = default_reasoning_effort
        self.prices = prices or DEFAULT_OPENAI_PRICES_USD_PER_MTOK
        self.usd_to_inr = usd_to_inr
        self.relaxed_call_schema = relaxed_call_schema
        # SDK retries are off: this class retries inside one total budget per request.
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout_s, max_retries=0
        )
        self.usage: dict[str, UsageTotals] = defaultdict(UsageTotals)
        self.latency_ms: dict[str, list[float]] = defaultdict(list)
        self.repairs = 0  # structured outputs that needed the repair retry

    # ------------------------------------------------------------------ helpers
    def _budget_s(self, purpose: str) -> float:
        if purpose == "call_turn":
            return self.call_turn_timeout_s
        return _FAST_BUDGET_S.get(purpose, self.timeout_s)

    def _effort_for(self, purpose: str, model: str, hint: Effort | None) -> str | None:
        """The configured per-purpose reasoning effort; the brain's generic ``effort`` hint is not
        used (it is a Claude-shaped knob: 'low' for everything)."""
        if not is_reasoning_model(model):
            return None
        return self.reasoning_effort.get(purpose, self.default_reasoning_effort)

    @staticmethod
    def _messages(
        system: str,
        messages: Sequence[LLMMessage],
        attachments: Sequence[MediaBlob],
        notes: str = "",
    ) -> list[dict[str, Any]]:
        from .prompts import CACHE_BREAK

        # notes go after the static rules but BEFORE the per-call data so the prefix stays cacheable
        head, _, tail = system.partition(CACHE_BREAK)
        text = head.rstrip() + "\n" + notes if notes else head
        if tail:
            text += ("" if notes else "\n") + tail.replace(CACHE_BREAK, "\n")
        out: list[dict[str, Any]] = [{"role": "system", "content": text}]
        out += [{"role": m.role, "content": m.content} for m in messages]
        if attachments:
            idx = next((i for i in range(1, len(out)) if out[i]["role"] == "user"), None)
            if idx is None:
                out.append({"role": "user", "content": ""})
                idx = len(out) - 1
            parts = [attachment_part(a) for a in attachments]
            parts.append({"type": "text", "text": out[idx]["content"] or "See attached."})
            out[idx] = {"role": "user", "content": parts}
        return out

    @staticmethod
    def _error(e: Exception, model: str) -> ProviderError:
        # Messages deliberately omit the API's text (it can echo request content).
        if isinstance(e, openai.BadRequestError):
            code = getattr(e, "code", None) or "invalid_request"
            param = getattr(e, "param", None)
            return ProviderError("openai", f"bad request ({code}, param={param})")
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ProviderError("openai", "authentication failed")
        if isinstance(e, openai.NotFoundError):
            return ProviderError("openai", f"model or endpoint not found: {model}")
        if isinstance(e, openai.RateLimitError):
            return ProviderError("openai", "rate limited", retryable=True)
        if isinstance(e, openai.APITimeoutError):
            return ProviderError("openai", "timeout", retryable=True)
        if isinstance(e, openai.APIConnectionError):
            return ProviderError("openai", "connection error", retryable=True)
        if isinstance(e, openai.APIStatusError):
            return ProviderError(
                "openai", f"api error {e.status_code}", retryable=e.status_code >= 500
            )
        return ProviderError("openai", f"unexpected {type(e).__name__}")

    @staticmethod
    def _retryable(e: Exception) -> bool:
        if isinstance(e, openai.RateLimitError):
            # insufficient_quota is a billing problem, not a transient limit
            return getattr(e, "code", None) != "insufficient_quota"
        if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
            return True
        return isinstance(e, openai.APIStatusError) and e.status_code >= 500

    async def _create(self, kwargs: dict[str, Any], model: str, deadline: float) -> Any:
        """One logical request: retry 429/5xx/connection/timeouts with backoff until the
        total budget (``deadline``, monotonic) is spent."""
        attempt = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                raise ProviderError("openai", "timeout", retryable=True)
            try:
                return await self._client.with_options(timeout=remaining).chat.completions.create(
                    **kwargs
                )
            except openai.OpenAIError as e:
                if not self._retryable(e) or attempt >= self.max_retries:
                    raise self._error(e, model) from e
                delay = _BACKOFF_BASE_S * (2**attempt) * (0.5 + random.random())
                headers = getattr(getattr(e, "response", None), "headers", None) or {}
                with contextlib.suppress(TypeError, ValueError):
                    retry_after = float(headers.get("retry-after", 0))
                    delay = max(delay, min(retry_after, _MAX_RETRY_AFTER_S))
                if time.monotonic() + delay >= deadline - 0.5:  # no useful time left for a retry
                    raise self._error(e, model) from e
                attempt += 1
                log.info("openai retry %d after %s", attempt, type(e).__name__)
                await asyncio.sleep(delay)

    def _account(
        self, purpose: str, model: str, response: Any, elapsed_ms: float
    ) -> tuple[str, int, int]:
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        out_details = getattr(usage, "completion_tokens_details", None)
        reasoning = int(getattr(out_details, "reasoning_tokens", 0) or 0)
        served = getattr(response, "model", None) or model
        cost = estimate_cost_inr(
            served, in_tok, out_tok, cached, prices=self.prices, usd_to_inr=self.usd_to_inr
        )
        t = self.usage[purpose]
        t.calls += 1
        t.input_tokens += in_tok - cached
        t.output_tokens += out_tok
        t.cache_read_tokens += cached
        t.cost_inr += cost
        self.latency_ms[purpose].append(elapsed_ms)
        log.info(
            "llm purpose=%s model=%s in=%d cached=%d out=%d reasoning=%d latency_ms=%.0f "
            "cost_inr_est=%.4f",
            purpose, served, in_tok, cached, out_tok, reasoning, elapsed_ms, cost,
        )
        return served, in_tok, out_tok

    # ------------------------------------------------------------------ API
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
        notes = ""
        strict = True
        if json_schema and purpose == "call_turn" and self.relaxed_call_schema:
            json_schema, strict = relax_call_schema(json_schema), False
        if json_schema:
            notes = _NOTES_FORMAT + (_NOTES_CALL_TURN if purpose == "call_turn" else "")
            notes += _NOTES_INTERPRET if purpose == "interpret" else ""
        api_messages = self._messages(system, messages, attachments, notes)
        reasoning = self._effort_for(purpose, model, effort)
        cap = max_tokens + (_REASONING_HEADROOM.get(reasoning or "none", 0) if reasoning else 0)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_completion_tokens": cap,
            "prompt_cache_key": f"friday:{purpose}",
        }
        if reasoning:
            kwargs["reasoning_effort"] = reasoning
        if json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "friday_output", "strict": strict, "schema": json_schema},
            }
        deadline = time.monotonic() + self._budget_s(purpose)

        text, finish, served, in_tok, out_tok = await self._once(kwargs, model, purpose, deadline)
        if json_schema and (err := _validate_json(text, json_schema)):
            # one repair retry: show the model its own (capped) reply and the failure path
            self.repairs += 1
            log.warning("openai %s: structured output invalid (%s); repair retry", purpose, err)
            repair = [
                *api_messages,
                {"role": "assistant", "content": text[:2000]},
                {
                    "role": "user",
                    "content": f"That reply did not match the schema ({err}). Reply again with "
                    "ONLY the corrected JSON object.",
                },
            ]
            text, finish, served, in2, out2 = await self._once(
                {**kwargs, "messages": repair}, model, purpose, deadline
            )
            in_tok, out_tok = in_tok + in2, out_tok + out2
            if err2 := _validate_json(text, json_schema):
                raise ProviderError("openai", f"invalid structured output ({purpose}): {err2}")
        return LLMResponse(
            text=text, model=served, input_tokens=in_tok, output_tokens=out_tok, stop_reason=finish
        )

    async def _once(
        self, kwargs: dict[str, Any], model: str, purpose: str, deadline: float
    ) -> tuple[str, str | None, str, int, int]:
        t0 = time.monotonic()
        response = await self._create(kwargs, model, deadline)
        elapsed_ms = (time.monotonic() - t0) * 1000
        served, in_tok, out_tok = self._account(purpose, model, response, elapsed_ms)
        if not getattr(response, "choices", None):
            raise ProviderError("openai", f"empty response ({purpose})", retryable=True)
        choice = response.choices[0]
        finish = getattr(choice, "finish_reason", None)
        msg = choice.message
        if getattr(msg, "refusal", None) or finish == "content_filter":
            raise ProviderError("openai", f"model declined ({purpose})")
        text = getattr(msg, "content", None) or ""
        if finish == "length" and "response_format" in kwargs:
            raise ProviderError("openai", f"output truncated ({purpose})", retryable=True)
        return text, finish, served, in_tok, out_tok

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def build_openai_llm(c: Container) -> OpenAILLM:
    s: Settings = c.settings
    key = s.openai_api_key.get_secret_value() if s.openai_api_key else None
    return OpenAILLM(
        api_key=key,
        default_model=s.openai_default_purpose_model,
        fast_model=s.openai_models.get("call_turn", s.openai_default_purpose_model),
        timeout_s=s.openai_timeout_s,
        call_turn_timeout_s=s.openai_call_turn_timeout_s,
        max_retries=s.openai_max_retries,
        reasoning_effort=s.openai_reasoning_effort,
        default_reasoning_effort=s.openai_default_reasoning_effort,
        prices=s.openai_prices_usd_per_mtok,
        usd_to_inr=s.openai_usd_to_inr,
        relaxed_call_schema=s.openai_relaxed_call_schema,
    )
