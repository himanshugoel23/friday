# ruff: noqa: E501
"""Fakes for the reply-writer tests: a scripted LLM client, ready-made inputs. No network."""

from __future__ import annotations

import json
from typing import Any

from friday.core.interfaces import LLMResponse
from friday.replywriter.schema import Button, Facts, ProductFact, ReplyInput


class ScriptedLLM:
    """complete() returns the next scripted JSON (a dict is dumped, a str is returned as is) or raises."""

    def __init__(self, *replies: Any) -> None:
        self.replies, self.calls = list(replies), []

    async def complete(self, **kw: Any) -> LLMResponse:
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r if isinstance(r, str) else json.dumps(r), model="fake")


def out(*messages: str, question: str | None = None, buttons: list[str] | None = None, proofs: list[str] | None = None) -> dict[str, Any]:
    return {"messages": list(messages), "question": question, "buttons": buttons or [], "proofs": proofs or []}


def compare_input(**kw: Any) -> ReplyInput:
    facts = Facts(
        store="Blinkit", stores=["Blinkit"], stores_offered=["Zepto", "Instamart", "BigBasket"], category="atta",
        products=[
            ProductFact(name="Aashirvaad Shudh Chakki Atta 5 kg", store="Blinkit", price_paise=24400, per_unit_paise=4880, unit="kg", pack="5 kg", delivery_minutes=9),
            ProductFact(name="Rajdhani Chakki Atta 5 kg", store="Blinkit", price_paise=21900, per_unit_paise=4380, unit="kg", pack="5 kg", delivery_minutes=9),
        ],
        pick="Rajdhani Chakki Atta 5 kg", pick_reason="lowest price per kg (Rs 43.8/kg)", as_of="29 Oct 22:10", links=["https://blinkit.com/p/atta"],
    )
    base: dict[str, Any] = {"intent": "price_compare", "facts": facts, "lang": "en", "pending": "compare_more",
                            "buttons": [Button(id="shop:cmp:yes", title="Compare"), Button(id="shop:cmp:no", title="No thanks")]}
    base.update(kw)
    return ReplyInput(**base)


GOOD = out(
    "Checked Blinkit only. I would take Rajdhani Chakki Atta 5 kg: lowest price per kg.",
    "1. Aashirvaad Shudh Chakki Atta 5 kg: Rs 244 (Blinkit), 9 min\n2. Rajdhani Chakki Atta 5 kg: Rs 219 (Blinkit), 9 min\nPrices as of 29 Oct 22:10 IST.",
    "Want me to compare with Zepto, Instamart and BigBasket too?",
    question="Want me to compare with Zepto, Instamart and BigBasket too?",
)
