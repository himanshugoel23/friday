"""The business-type knowledge file (``business_types.yaml``): loader and schema.

Read only offline, while a playbook is being drafted. It never reaches a live call.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from friday.playbooks.intents import PLACEHOLDERS

KNOWLEDGE_PATH = Path(__file__).with_name("business_types.yaml")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# the lines a surprise may answer (the offline template keeps the salon line ids)
ANSWERABLE_LINES = frozenset({"s1_ask", "s2_ask", "s2_ask_time", "s2b_ask", "s3_ask", "s5_ask",
                              "s6_ask"})
OVERRIDABLE_LINES = frozenset({
    "s1_ask", "s2_ask", "s2b_ask", "s3_ask", "s3_readback_price", "s3_readback_range_price",
    "s4_ask", "s5_ask", "s6_ask",
})
TASK_TYPES = frozenset({"booking", "enquiry", "order", "healthcare", "status_chase",
                        "hotel_booking", "service_coordination"})
EXPECTED_OUTCOMES = frozenset({"SLOT_OFFERED", "CALL_BACK_LATER", "NO_SLOT", "WRONG_NUMBER",
                               "REFUSED", "UNCLEAR", "BOOKED"})


class KnowledgeError(ValueError):
    pass


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quotes(_S):
    price_units: str
    typical_range: str
    not_on_phone: str


class Surprise(_S):
    id: str
    title: str
    at: str
    say: str
    then: list[str] = Field(default_factory=list)
    hold_s: int | None = None
    expect: str

    @field_validator("at")
    @classmethod
    def _at(cls, v: str) -> str:
        if v not in ANSWERABLE_LINES:
            raise ValueError(f"'at' must be one of {sorted(ANSWERABLE_LINES)}")
        return v

    @field_validator("expect")
    @classmethod
    def _expect(cls, v: str) -> str:
        if v not in EXPECTED_OUTCOMES:
            raise ValueError(f"'expect' must be one of {sorted(EXPECTED_OUTCOMES)}")
        return v


class SelectHints(_S):
    task_types: list[str]
    categories: list[str]
    keywords: list[str]

    @field_validator("task_types")
    @classmethod
    def _tt(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in TASK_TYPES]
        if bad or not v:
            raise ValueError(f"task_types must be a non-empty subset of {sorted(TASK_TYPES)}")
        return v


class TemplateHints(_S):
    noun: str
    wrong_kind: str
    service_default: str
    business_default: str
    person_label: str
    price_word: str
    price_unit: str = "rupaye"
    price_inr: int = Field(gt=0)
    duration_min: int | None = None
    slot_reply: str
    alt_reply: str
    full_reply: str
    select: SelectHints
    lines: dict[str, str] = Field(default_factory=dict)

    @field_validator("lines")
    @classmethod
    def _lines(cls, v: dict[str, str]) -> dict[str, str]:
        bad = set(v) - OVERRIDABLE_LINES
        if bad:
            raise ValueError(
                f"cannot override line(s) {sorted(bad)}; allowed {sorted(OVERRIDABLE_LINES)}"
            )
        for lid, text in v.items():
            if _DEVANAGARI.search(text):
                raise ValueError(f"line {lid}: Roman script only")
            unknown = set(re.findall(r"\{([a-z_]+)\}", text)) - PLACEHOLDERS
            if unknown:
                raise ValueError(f"line {lid}: unknown placeholder(s) {sorted(unknown)}")
        return v


class BusinessType(_S):
    id: str = ""
    title: str
    task_type: str
    who_answers: str
    typical_opening: list[str] = Field(min_length=1)
    caller_questions: list[str] = Field(min_length=3)
    quotes: Quotes
    wont_say_on_phone: list[str] = Field(min_length=1)
    surprises: list[Surprise] = Field(min_length=5)
    hangup_behaviour: str
    language_mix: str
    template: TemplateHints

    @model_validator(mode="after")
    def _check(self) -> BusinessType:
        if self.task_type not in TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(TASK_TYPES)}")
        ids = [s.id for s in self.surprises]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate surprise ids")
        return self


class Knowledge(_S):
    version: int
    business_types: dict[str, BusinessType]

    @model_validator(mode="after")
    def _ids(self) -> Knowledge:
        for k, bt in self.business_types.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", k):
                raise ValueError(f"business type id '{k}': use lowercase letters, digits, _")
            bt.id = k
        return self


def parse_knowledge(text: str) -> Knowledge:
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise KnowledgeError(f"cannot parse business types: {e}") from None
    try:
        return Knowledge.model_validate(data)
    except ValueError as e:
        raise KnowledgeError(str(e)) from None


@lru_cache(maxsize=1)
def load_knowledge() -> Knowledge:
    return parse_knowledge(KNOWLEDGE_PATH.read_text(encoding="utf-8"))


def business_type_ids() -> list[str]:
    return sorted(load_knowledge().business_types)


def get_business_type(business_type: str) -> BusinessType:
    kn = load_knowledge()
    if business_type not in kn.business_types:
        raise KnowledgeError(
            f"unknown business type '{business_type}'. "
            f"Known: {', '.join(sorted(kn.business_types))}"
        )
    return kn.business_types[business_type]
