"""AI-13: simulated-business persona helper for the Voice simulator's free-form
replies. A plain function taking an ``LLMClient``; deterministic with the fake LLM.

    from friday.brain.sim_business import simulate_business_reply
    reply = await simulate_business_reply(c.llm, sim_business, transcript)
    reply.text, reply.language, reply.hangup
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from friday.core.interfaces import LLMClient, LLMMessage, ProviderError
from friday.core.models import Speaker, Transcript

from .heuristics.business import reply as _det_reply
from .prompts import render_input, system_prompt
from .schemas import BusinessReplyOut, strict_schema


def _turns(transcript: Transcript | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(transcript, Transcript):
        return [{"speaker": t.speaker.value, "text": t.text} for t in transcript.turns
                if t.speaker in (Speaker.FRIDAY, Speaker.CALLEE)]
    return list(transcript)


async def simulate_business_reply(llm: LLMClient, business: BaseModel | dict[str, Any],
                                  transcript: Transcript | list[dict[str, Any]],
                                  *, model: str | None = None) -> BusinessReplyOut:
    biz = business.model_dump(mode="json") if isinstance(business, BaseModel) else dict(business)
    payload = {"business": biz, "transcript": _turns(transcript)}
    try:
        resp = await llm.complete(
            system=system_prompt("sim_business"),
            messages=[LLMMessage(role="user", content=render_input(payload,
                                                                   "Your next line:"))],
            purpose="sim_business", model=model, max_tokens=300,
            json_schema=strict_schema(BusinessReplyOut))
        return BusinessReplyOut.model_validate_json(resp.text)
    except (ProviderError, ValidationError, ValueError):
        return _det_reply(biz, payload["transcript"])
