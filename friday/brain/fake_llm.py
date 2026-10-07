"""Deterministic fake ``LLMClient`` - the whole product runs on it in simulator
mode with no API keys.

* Keyed on ``purpose``: the brain's purposes (interpret, call_turn, summarize,
  compare, judge_nudge, resolve_references, extract, translate, sim_business) are
  answered by the deterministic handlers in ``friday.brain.handlers``, reading the
  same ``<input>`` JSON the real model gets.
* Unknown purposes: if a ``json_schema`` is given, returns the minimal valid
  object for it; otherwise a short neutral text.
* ``script(purpose, text)`` queues canned responses (tests by other teams);
  ``calls`` records every request. Same input -> same output.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from friday.core.interfaces import Effort, LLMMessage, LLMResponse, ProviderError
from friday.core.logging import get_logger
from friday.core.models import MediaBlob

from .prompts import extract_input

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)


@dataclass
class FakeCall:
    purpose: str
    system: str
    messages: list[LLMMessage]
    model: str | None
    json_schema: dict | None
    attachments: list[MediaBlob] = field(default_factory=list)
    response: str = ""


def minimal_instance(schema: dict[str, Any], root: dict[str, Any] | None = None) -> Any:
    """Smallest value valid for a (strict) JSON schema."""
    root = root or schema
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return minimal_instance(root.get("$defs", {}).get(name, {}), root)
    if "anyOf" in schema:
        options = schema["anyOf"]
        if any(o.get("type") == "null" for o in options):
            return None
        return minimal_instance(options[0], root)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    t = schema.get("type")
    if isinstance(t, list):
        t = "null" if "null" in t else t[0]
    if t == "object":
        return {k: minimal_instance(v, root) for k, v in schema.get("properties", {}).items()
                if k in schema.get("required", [])}
    return {"string": "", "integer": 0, "number": 0, "boolean": False, "array": [],
            "null": None}.get(t)


def merge_payload(stable: dict[str, Any], volatile: dict[str, Any]) -> dict[str, Any]:
    """Cached ``<data>`` (system) + volatile ``<input>`` (message): one level deep."""
    out = dict(stable)
    for k, v in volatile.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


class FakeLLM:
    """Deterministic ``LLMClient``."""

    provider = "fake"

    def __init__(self, handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None
                 ) -> None:
        if handlers is None:
            from .handlers import HANDLERS

            handlers = dict(HANDLERS)
        self.handlers = handlers
        self.calls: list[FakeCall] = []
        self._scripts: dict[str, deque[str]] = defaultdict(deque)
        self.fail_purposes: set[str] = set()
        self._batches: dict[str, dict[str, str]] = {}

    def script(self, purpose: str, *responses: str | BaseModel | dict) -> None:
        """Queue canned responses for ``purpose`` (consumed in order, then handlers)."""
        for r in responses:
            if isinstance(r, BaseModel):
                r = r.model_dump_json()
            elif isinstance(r, dict):
                r = json.dumps(r)
            self._scripts[purpose].append(r)

    async def submit_batch(self, requests: Sequence[dict[str, Any]]) -> str:
        """Fake Batches API: answers immediately and deterministically."""
        results: dict[str, str] = {}
        for r in requests:
            resp = await self.complete(system=r.get("system", ""), messages=r["messages"],
                                       purpose=r.get("purpose", "batch"), model=r.get("model"),
                                       json_schema=r.get("json_schema"),
                                       attachments=r.get("attachments", ()))
            results[r["custom_id"]] = resp.text
        batch_id = f"fakebatch_{len(self._batches) + 1}"
        self._batches[batch_id] = results
        return batch_id

    async def batch_results(self, batch_id: str) -> dict[str, str] | None:
        return self._batches.get(batch_id)

    def calls_for(self, purpose: str) -> list[FakeCall]:
        return [c for c in self.calls if c.purpose == purpose]

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
        call = FakeCall(purpose=purpose, system=system, messages=list(messages), model=model,
                        json_schema=json_schema, attachments=list(attachments))
        self.calls.append(call)
        if purpose in self.fail_purposes:
            raise ProviderError("fake", f"scripted failure for {purpose}", retryable=True)
        if self._scripts.get(purpose):
            text = self._scripts[purpose].popleft()
        else:
            text = self._answer(purpose, system, messages, json_schema)
        call.response = text
        prompt_chars = len(system) + sum(len(m.content) for m in messages)
        return LLMResponse(text=text, model=f"fake-{model or 'default'}",
                           input_tokens=prompt_chars // 4, output_tokens=len(text) // 4,
                           stop_reason="end_turn")

    def _answer(self, purpose: str, system: str, messages: Sequence[LLMMessage],
                json_schema: dict | None) -> str:
        payload = None
        for m in reversed(messages):
            if m.role == "user":
                payload = extract_input(m.content)
                if payload is not None:
                    break
        stable = extract_input(system, tag="data")
        if stable is not None:
            payload = merge_payload(stable, payload or {})
        handler = self.handlers.get(purpose)
        if handler is not None and payload is not None:
            out = handler(payload)
            if isinstance(out, BaseModel):
                return out.model_dump_json()
            return out if isinstance(out, str) else json.dumps(out)
        if json_schema:
            return json.dumps(minimal_instance(json_schema))
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return "Okay." if last else ""


def build_fake_llm(c: Container) -> FakeLLM:
    return FakeLLM()
