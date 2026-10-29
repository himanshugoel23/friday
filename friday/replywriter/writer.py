# ruff: noqa: E501
"""write_reply(ReplyInput) -> ReplyOutput: the ONE interface (docs/REPLY_WRITER.md).

* ``TemplateWriter`` (templates.py): always available, deterministic. It is the fallback.
* ``LlmWriter`` (here): the existing LLM client + the friday/style prompt block, strict JSON out. Every output
  goes through the FACT CHECK (factcheck.py). One invented number, price, store, pack size or URL, or one
  style-rule violation => the LlmWriter output is thrown away and the TemplateWriter answer is used.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from friday.core.interfaces import LLMMessage
from friday.core.logging import get_logger
from friday.replywriter.factcheck import verify
from friday.replywriter.schema import WRITABLE, ReplyInput, ReplyOutput
from friday.replywriter.templates import TemplateWriter
from friday.style.prompt import STYLE_BLOCK

log = get_logger(__name__)

SYSTEM = (
    "You are the reply writer of Friday, an assistant on chat for people in India. You decide what to text and how to text it. "
    "You receive JSON: the intent, the FACTS (money is in paise: 24400 = Rs 244), the user's language, script and mood, the one "
    "open question, and a reference reply. Write the reply as JSON only:\n"
    '{"messages": ["..."], "question": "..." or null, "buttons": ["<button id>"], "proofs": ["<proof ref>"]}\n'
    "HARD RULES: use ONLY facts from the input. Never add or change a number, price, store name, pack size or link. "
    "Never print status codes. At most ONE question, as the last line of the last message. 1 to 5 messages of 1 to 5 short lines each. "
    "No markdown headers. Never refuse flatly: say what happened and what you can do next. Write in the user's language and script "
    "(Roman Hinglish stays Roman). Female voice for Hinglish (rahi hoon, sakti hoon). Buttons and proofs only from the lists given.\n"
    + STYLE_BLOCK
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
        "question": {"type": ["string", "null"]},
        "buttons": {"type": "array", "items": {"type": "string"}},
        "proofs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["messages", "question", "buttons", "proofs"],
    "additionalProperties": False,
}


class LlmWriterError(RuntimeError):
    pass


class LlmWriter:
    name = "llm"

    def __init__(self, llm: Any, *, timeout_s: float = 6.0, model: str | None = None) -> None:
        self.llm, self.timeout_s, self.model = llm, timeout_s, model

    async def write(self, inp: ReplyInput, reference: ReplyOutput) -> ReplyOutput:
        payload = {"input": inp.model_dump(mode="json", exclude_none=True), "reference_reply": reference.messages}
        try:
            resp = await asyncio.wait_for(
                self.llm.complete(
                    system=SYSTEM, messages=[LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False))],
                    purpose="reply_writer", model=self.model, max_tokens=500, json_schema=SCHEMA,
                ),
                self.timeout_s,
            )
            data = json.loads(resp.text)
            if not isinstance(data, dict) or set(data) - {"messages", "question", "buttons", "proofs"}:
                raise LlmWriterError("unexpected keys")
            offered = {b.id: b for b in inp.buttons}
            return ReplyOutput(
                messages=[str(m).strip() for m in data["messages"] if str(m).strip()],
                question=(str(data["question"]).strip() or None) if data.get("question") else None,
                buttons=[offered[b] for b in data.get("buttons") or [] if b in offered],
                proofs=[str(p) for p in data.get("proofs") or []],
                writer="llm",
            )
        except Exception as e:  # noqa: BLE001 - any failure means: use the template
            raise LlmWriterError(type(e).__name__) from e


async def write_reply(
    inp: ReplyInput, *, llm: Any = None, use_llm: bool = False, timeout_s: float = 6.0, model: str | None = None
) -> ReplyOutput:
    """The reply for ``inp``. With ``use_llm`` and a client the LlmWriter is tried first and fact-checked."""
    base = TemplateWriter().write(inp)
    if not use_llm or llm is None or inp.intent not in WRITABLE:
        return base
    try:
        out = await LlmWriter(llm, timeout_s=timeout_s, model=model).write(inp, base)
    except LlmWriterError as e:
        log.info("reply writer: llm unusable (%s); template used", e)
        return base.model_copy(update={"fact_check": "rejected:llm_error"})
    problems = verify(inp, out)
    if problems:
        log.info("reply writer: llm output rejected (%s); template used", ",".join(problems))  # codes only, never the text
        return base.model_copy(update={"fact_check": "rejected:" + ",".join(problems)})
    return out.model_copy(update={"writer": "llm", "fact_check": "ok"})
