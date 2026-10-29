# ruff: noqa: E501
"""Typed contracts of the general browser agent (docs/BROWSER_AGENT_DESIGN.md).

Everything the model can say is the flat ``Action`` schema below; everything the page can say is a ``PageSnapshot``
that is rendered as UNTRUSTED data. The model never sees a stored value of the user: it sees fact KEYS and picks a
``value_source`` such as ``fact:email``; the code resolves the value inside the worker.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

TOOLS = (
    "goto", "click", "fill", "select", "upload", "press", "wait", "extract", "screenshot_proof",
    "ask_user", "request_confirmation", "finish", "give_up",
)  # fmt: skip
ASK_KINDS = ("info", "choice", "yes_no", "attestation", "allow_domain", "allow_account", "login", "otp")


class Status(StrEnum):
    RUNNING = "running"
    WAITING_USER = "waiting_user"  # a grouped question is open
    WAITING_CONFIRM = "waiting_confirm"  # an irreversible action waits for an explicit yes
    DONE = "done"
    BLOCKED = "blocked"  # captcha / challenge / 401-403-429 / robots: we stop and say so
    PAYMENT_STOP = "payment_stop"  # a payment step was reached: Friday never pays
    BUDGET = "budget"
    GAVE_UP = "gave_up"
    BUSY = "busy"  # no browser capacity right now (RAM / sessions): resumable
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # the user did not answer in time; nothing irreversible happened
    ERROR = "error"


TERMINAL = frozenset({Status.DONE, Status.BLOCKED, Status.PAYMENT_STOP, Status.BUDGET, Status.GAVE_UP,
                      Status.CANCELLED, Status.EXPIRED, Status.ERROR})  # fmt: skip


class Element(BaseModel):
    id: str  # "e12": assigned per snapshot, the ONLY way the model points at something
    role: str  # button link textbox checkbox radio select file textarea
    name: str = ""  # visible label / accessible name (UNTRUSTED text)
    type: str = ""  # input type
    autocomplete: str = ""
    placeholder: str = ""
    value: str = ""  # current value; never filled for password / card style fields
    required: bool = False
    checked: bool | None = None
    disabled: bool = False
    options: list[str] = Field(default_factory=list)
    group: str = ""  # fieldset legend / form heading
    href_host: str = ""
    submit: bool = False  # a submit button of a form


class PageSnapshot(BaseModel):
    url: str
    title: str = ""
    http_status: int | None = None
    text: str = ""  # visible text, already clipped (UNTRUSTED)
    elements: list[Element] = Field(default_factory=list)
    captcha: bool = False


class AskField(BaseModel):
    key: str  # fact key the answer is stored under, e.g. "notice_period"
    label: str
    default: str | None = None  # a sensible suggestion the user can accept
    options: list[str] | None = None


class Action(BaseModel):
    """One step chosen by the model. Strict JSON, every field present (null when unused)."""

    tool: Literal[
        "goto", "click", "fill", "select", "upload", "press", "wait", "extract", "screenshot_proof",
        "ask_user", "request_confirmation", "finish", "give_up",
    ]  # fmt: skip
    note: str  # one short sentence: why (clipped and logged; never put user data here)
    url: str | None
    target: str | None  # element id from the snapshot, e.g. "e7"
    value_source: str | None  # fact:<key> | attest:<key> | vault:username | vault:password | otp | text:<search words only>
    option: str | None  # select: the option text; may also be "fact:<key>"
    file_ref: str | None  # upload: a reference such as "resume"; never a path
    key: str | None  # press: Enter, Tab, Escape ...
    ms: int | None  # wait
    question: str | None  # ask_user / extract
    kind: Literal["info", "choice", "yes_no", "attestation", "allow_domain", "allow_account", "login", "otp"] | None
    fields: list[AskField] | None
    suggest: str | None  # fill: a suggested value to OFFER when the fact is missing (never used silently)
    summary: str | None  # request_confirmation: exact text / consequence shown to the user
    result: str | None  # finish
    reason: str | None  # give_up


class Permit(BaseModel):
    """The user said yes to ONE irreversible action. Consumed by the next matching click."""

    id: str
    summary: str
    host: str
    expires_at: str
    action_class: str = "irreversible"
    label: str = ""  # the button the user was shown; the permit works for THAT control only


class Pending(BaseModel):
    kind: Literal["ask", "confirm"]
    id: str
    question: str
    ask_kind: str = "info"
    fields: list[AskField] = Field(default_factory=list)
    summary: str = ""
    target: str = ""  # confirm: the element label the yes is for
    host: str = ""
    created_at: str
    expires_at: str
    link: str = ""  # login / otp: the secure page (never a secret)
    domain: str = ""  # allow_domain / allow_account: the host asked about


class HistoryItem(BaseModel):
    step: int
    tool: str
    target: str = ""  # element LABEL (untrusted, clipped), never a typed value
    result: str = ""


class ProofRef(BaseModel):
    id: str
    what: str
    where: str  # host + path, no query string
    when: str
    path: str = ""


class RunSpec(BaseModel):
    """Input of a run. The caller (code, not the model and not a page) fixes all of this."""

    goal: str
    allowed_domains: list[str]
    max_steps: int = 40
    max_seconds: float = 300.0  # ACTIVE seconds (waiting for the user does not count)
    max_cost_inr: float = 12.0
    start_url: str | None = None
    account_ok_hosts: list[str] = Field(default_factory=list)  # explicit user ok to create an account, per site
    standing_ok: list[str] = Field(default_factory=list)  # pre-authorised action classes (job auto-apply only)
    handover_payment_link: bool = False  # the user asked for the payment link / QR and the site provides it
    playbook: str = ""  # e.g. "job_apply"
    login_site: str = ""  # vault key for this site
    lang: str = "hinglish"


class RunState(BaseModel):
    id: str
    user_id: str
    spec: RunSpec
    status: Status = Status.RUNNING
    step: int = 0
    spent_inr: float = 0.0
    active_s: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    last_url: str = ""
    history: list[HistoryItem] = Field(default_factory=list)
    pending: Pending | None = None
    deferred: list[AskField] = Field(default_factory=list)  # missing fields noticed so far (flushed as ONE question)
    attest: dict[str, bool] = Field(default_factory=dict)  # legal yes/no answers: this run only, never remembered
    permits: list[Permit] = Field(default_factory=list)
    proofs: list[ProofRef] = Field(default_factory=list)
    refusals: int = 0  # consecutive refused actions
    asks: int = 0
    result: str = ""
    reason: str = ""  # why it stopped (blocked reason, payment, ...)
    handover_url: str = ""
    left_for_user: list[str] = Field(default_factory=list)  # labels of fields the agent will not fill (ID numbers ...)
    extra_domains: list[str] = Field(default_factory=list)  # hosts the USER allowed during the run (never added by a page or the model)
    recent_sigs: list[str] = Field(default_factory=list)  # loop detection
    notes: list[str] = Field(default_factory=list)  # extracted answers (clipped), shown back to the model
    uploads: dict[str, int] = Field(default_factory=dict)


class RunOutcome(BaseModel):
    run_id: str
    status: Status
    message: str  # plain text for the user (wording module)
    question: str = ""
    proofs: list[ProofRef] = Field(default_factory=list)
    handover_url: str = ""
