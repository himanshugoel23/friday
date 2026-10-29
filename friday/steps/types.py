# ruff: noqa: E501
"""Typed contracts of the step runner (docs/BROWSER_AGENT_STEPS.md).

The step vocabulary is CLOSED: a plan can only contain the types below. There is no pay, checkout, sign or
account-creation step type, and ``validate.py`` rejects any plan that tries to smuggle one in through free text.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class StepType(StrEnum):
    OPEN_SITE = "open_site"  # open the site from its URL and look at the page (loop)
    NEED_AREA = "need_area"  # precondition: delivery area known (saved place / given), else ask Home or PG
    NEED_LOGIN = "need_login"  # only when the page showed a login wall: guarded OTP flow
    NEED_INFO = "need_info"  # ask the user ONE fact the playbook needs (e.g. which subscription)
    SEARCH = "search"  # search box (+ location if the site asks) (loop)
    READ_RESULTS = "read_results"  # read product lines off the result page (loop)
    MATCH_VARIANT = "match_variant"  # variant/pack given -> that one, else the main variants (code)
    COMPARE_AND_SUGGEST = "compare_and_suggest"  # popular alternatives + ONE recommendation (friday/shopping)
    NAVIGATE = "navigate"  # go to a section of the site, change nothing (loop)
    FILL_PREVIEW = "fill_preview"  # fill a form but NEVER submit it (loop)
    ACT_CONFIRMED = "act_confirmed"  # one irreversible action, only after the user's explicit yes (loop + policy permit)
    READ_STATUS = "read_status"  # read a status (order, booking) off a page (loop)
    REPORT = "report"  # tell the user the result with proof


LOOP_STEPS = frozenset({StepType.OPEN_SITE, StepType.SEARCH, StepType.READ_RESULTS, StepType.NAVIGATE, StepType.FILL_PREVIEW,
                        StepType.ACT_CONFIRMED, StepType.READ_STATUS})  # fmt: skip


class Step(BaseModel):
    type: StepType
    title: str = ""  # short plain label; the user-facing text comes from wording.py
    args: dict[str, str] = Field(default_factory=dict)


class StepPlan(BaseModel):
    playbook: str  # price_check | cancel_subscription | ... | "llm"
    goal: str
    domains: list[str]  # allowed hosts: from the USER's words / the shopping site table, never from a model
    start_url: str = ""
    slots: dict[str, str] = Field(default_factory=dict)  # item, store, category, variant ...
    steps: list[Step]
    source: str = "data"  # data | llm


class Status(StrEnum):
    RUNNING = "running"
    WAITING_USER = "waiting_user"  # one question is open (area, info, resend, fallback yes/no)
    WAITING_OTP = "waiting_otp"  # the site sent a code; the user's chat reply carries it (guarded)
    WAITING_AGENT = "waiting_agent"  # the browser loop inside a step asked something (confirmation, form field)
    WAITING_BUSY = "waiting_busy"  # no browser capacity: retried by the tick
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL = frozenset({Status.DONE, Status.BLOCKED, Status.CANCELLED, Status.FAILED, Status.EXPIRED})


class StepRecord(BaseModel):
    idx: int
    type: str
    state: str  # done | skipped | failed
    note: str = ""  # short, no typed values
    snippet: str = ""  # a short text proof of what the page showed (clipped, secrets redacted)
    proofs: list[dict[str, str]] = Field(default_factory=list)  # screenshot refs: {id, what, where, when}


class Awaiting(BaseModel):
    kind: str  # area | info | resend | fallback | agent | otp
    asked_at: str
    key: str = ""  # info: the fact key
    tries: int = 0


class PlanState(BaseModel):
    id: str
    user_id: str
    lang: str = "hinglish"
    plan: StepPlan
    status: Status = Status.RUNNING
    idx: int = 0
    records: list[StepRecord] = Field(default_factory=list)
    # context the steps share. NEVER holds a code, password or card number.
    area: str = ""
    login_wall: bool = False
    logged_in: bool = False
    info: dict[str, str] = Field(default_factory=dict)
    products: list[dict[str, str]] = Field(default_factory=list)  # read off the site: title, pack, price
    shown: list[dict[str, str]] = Field(default_factory=list)  # what match_variant picked
    variant_missing: bool = False
    suggestion: dict[str, object] = Field(default_factory=dict)
    awaiting: Awaiting | None = None
    sub_run_id: str = ""  # the browser-loop run that is waiting for the user
    tries: dict[str, int] = Field(default_factory=dict)  # per step idx retry counters
    replans: int = 0
    resends: int = 0
    code_tries: int = 0
    stop_reason: str = ""
    fallback: str = ""  # next-best option offered when a step is blocked: shopping_web | manual
    created_at: str = ""
    updated_at: str = ""


class StepRequest(BaseModel):
    """What one browser-loop step is asked to do. Small on purpose: one step, one prompt."""

    user_id: str
    plan_id: str
    step: Step
    goal: str
    domains: list[str]
    start_url: str = ""
    lang: str = "hinglish"
    facts: dict[str, str] = Field(default_factory=dict)  # non-secret overlay facts (delivery_area ...)
    otp_key: str = ""  # login step: the key the guarded OTP channel holds the code under
    login_site: str = ""
    max_steps: int = 10


class StepResult(BaseModel):
    status: str  # ok | waiting | blocked | payment_stop | failed | busy
    text: str = ""  # the loop's finish result (page-derived; clipped)
    message: str = ""  # a plain message to relay (a question of the loop, or why it stopped)
    run_id: str = ""
    reason: str = ""
    proofs: list[dict[str, str]] = Field(default_factory=list)
