# ruff: noqa: E501
"""The closed contract of the reply writer (docs/REPLY_WRITER.md).

``ReplyInput`` says WHAT is true and WHAT to do (typed facts, language, mood, the one open question);
``ReplyOutput`` is the short messages to send. Both are closed (extra fields are an error) so a trained
model can only ever see and produce these fields. No phone number, user id or raw user text lives here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Intent = Literal[
    "greeting", "ack", "price_compare", "lookup_failed", "ask_one", "honest_limit", "confirm", "cancelled",
    "proof", "playbook", "passthrough",
]
Lang = Literal["en", "hinglish", "hi"]
Script = Literal["roman", "devanagari"]
Pending = Literal["place", "compare_more", "retry", "confirm", "answer"]
StyleFlag = Literal["emoji_ok", "short", "no_question"]
# intents whose facts are typed enough for a model to write them; the rest only travel through (draft in, draft out)
WRITABLE: frozenset[str] = frozenset(
    {"greeting", "ack", "price_compare", "lookup_failed", "ask_one", "honest_limit", "cancelled", "playbook"}
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Button(_Closed):
    id: str = Field(max_length=64)
    title: str = Field(max_length=24)


class ProductFact(_Closed):
    name: str
    store: str | None = None
    price_paise: int | None = None
    per_unit_paise: int | None = None
    unit: Literal["kg", "L"] | None = None
    pack: str | None = None
    delivery_minutes: int | None = None
    rating: float | None = None


class Facts(_Closed):
    """Everything a reply may state. Money is in paise; internal ``status_codes`` choose the words and are never printed."""

    name: str | None = None  # the user's first name
    store: str | None = None  # the one store the user named / that was checked
    stores: list[str] = Field(default_factory=list)  # stores that were read
    stores_unread: list[str] = Field(default_factory=list)
    stores_offered: list[str] = Field(default_factory=list)  # stores Friday can compare next
    product: str | None = None
    category: str | None = None
    products: list[ProductFact] = Field(default_factory=list, max_length=6)
    pick: str | None = None
    pick_reason: str | None = None
    status_codes: list[str] = Field(default_factory=list)
    proof_refs: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    as_of: str | None = None
    place: str | None = None
    topic: str | None = None
    when: str | None = None
    next_actions: list[str] = Field(default_factory=list)  # codes: retry | compare_others | open_site | paste_details


class ReplyInput(_Closed):
    intent: Intent
    facts: Facts = Field(default_factory=Facts)
    lang: Lang = "hinglish"
    script: Script = "roman"
    formality: Literal["casual", "polite"] = "casual"
    mood: Literal["normal", "stressed"] = "normal"
    pending: Pending | None = None  # the ONE open question (what the closing question is about)
    style: list[StyleFlag] = Field(default_factory=list)
    buttons: list[Button] = Field(default_factory=list)  # buttons the caller can show; a writer may only choose among them
    draft: list[str] = Field(default_factory=list)  # text the caller already has for this reply (trusted: built from the facts)


class ReplyOutput(_Closed):
    messages: list[str] = Field(min_length=1, max_length=5)
    question: str | None = None  # the single question, which is also the last line of the last message
    buttons: list[Button] = Field(default_factory=list)
    proofs: list[str] = Field(default_factory=list)  # refs of proof items to attach (subset of facts.proof_refs)
    writer: Literal["template", "llm", "legacy"] = "template"
    fact_check: str = "skipped"  # ok | skipped | rejected:<codes>

    @field_validator("messages")
    @classmethod
    def _short(cls, v: list[str]) -> list[str]:
        for m in v:
            n = len([ln for ln in m.splitlines() if ln.strip()])
            if n < 1 or n > 5:
                raise ValueError("each message is 1-5 lines")
        return v

    @model_validator(mode="after")
    def _question_last(self) -> ReplyOutput:
        if self.question and self.question.strip() not in self.messages[-1]:
            raise ValueError("the question must be inside the last message")
        return self
