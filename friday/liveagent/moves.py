"""The closed set of MOVES, per-callee-kind move sets, the transition table, and the policy
interface that picks the next move.

A move is a KIND of thing Friday may do next. What she actually SAYS is a fixed line from
``lines.py`` (pending founder approval) with slots filled from the brief or the callee's words and
verified by ``slotguard.py``. The default policy is deterministic rules (``rules.py``); an
LLM-backed policy (``LLMMovePolicy``) may only choose among the moves the state machine allows,
and its output is validated; anything invalid falls back to the rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from friday.liveagent.contracts import (
    ApprovalRequest,
    CallBrief,
    CalleeKind,
    CallLanguage,
    Commitment,
    OutcomeStatus,
)

if TYPE_CHECKING:
    from friday.liveagent.ports import MoveModel
    from friday.liveagent.understand_callee import Understanding


class Move(StrEnum):
    GREET = "greet"  # first word: hello (+ callee's name)
    DISCLOSE = "disclose"  # "I am Friday, <user>'s assistant"; also the truthful "are you AI?" line
    STATE_PURPOSE = "state_purpose"  # why the call; also delivers the brief's must_say items
    ASK = "ask"  # one question from the brief's ask_list (or a clarifying question)
    ANSWER_FROM_BRIEF = "answer_from_brief"  # a shareable fact, or the fixed deflection
    CONFIRM = "confirm"  # read back what was heard; accept/decline a commitment
    HANDLE_OBJECTION = "handle_objection"  # busy, refuses, asks money, off topic, silence, unclear
    HOLD_WAIT = "hold_wait"  # callee said wait / hold queue / IVR navigation / asking the user
    VOICEMAIL = "voicemail"  # the fixed short message (only if the brief allows it)
    CLOSE = "close"  # polite end after a result
    STOP = "stop"  # immediate polite end: stop calling, wrong number, distress, no bots, abuse


TERMINAL_MOVES = frozenset({Move.CLOSE, Move.STOP})

_ALL = frozenset(Move)

# Which moves a callee kind may use at all. Voicemail messages are only for personal callees (a
# business/official/customer-care line is not a mailbox we leave a callback request on); IVR
# navigation is a HOLD_WAIT sub-step that only makes sense for institutions.
KIND_MOVES: dict[CalleeKind, frozenset[Move]] = {
    CalleeKind.FAMILY_ELDER: _ALL,
    CalleeKind.FRIEND: _ALL,
    CalleeKind.PROVIDER: _ALL,
    CalleeKind.UNKNOWN: _ALL,
    CalleeKind.CUSTOMER_CARE: _ALL - {Move.VOICEMAIL},
    CalleeKind.OFFICIAL: _ALL - {Move.VOICEMAIL},
    CalleeKind.BUSINESS: _ALL - {Move.VOICEMAIL},
}
KINDS_WITH_IVR = frozenset(
    {CalleeKind.CUSTOMER_CARE, CalleeKind.OFFICIAL, CalleeKind.BUSINESS, CalleeKind.PROVIDER}
)

START_MOVES = frozenset({Move.GREET, Move.VOICEMAIL, Move.HOLD_WAIT, Move.STOP})

_ANYTIME = frozenset({Move.STOP, Move.HOLD_WAIT, Move.CLOSE, Move.HANDLE_OBJECTION})

# prev move -> moves that may follow it. Disclosure is ALWAYS the move right after the greet:
# nothing but the stop/hold/voicemail escapes may follow GREET. After that every content move may
# follow any non-terminal move; STOP, CLOSE, HOLD_WAIT and objections may follow anything.
_CONTENT = frozenset(
    {Move.STATE_PURPOSE, Move.ASK, Move.ANSWER_FROM_BRIEF, Move.CONFIRM, Move.DISCLOSE}
)
_OPEN = _ANYTIME | _CONTENT
TRANSITIONS: dict[Move | None, frozenset[Move]] = {
    None: START_MOVES,
    Move.GREET: frozenset({Move.DISCLOSE, Move.STOP, Move.VOICEMAIL, Move.HOLD_WAIT}),
    Move.DISCLOSE: _OPEN,
    Move.STATE_PURPOSE: _OPEN,
    Move.ASK: _OPEN,
    Move.ANSWER_FROM_BRIEF: _OPEN,
    Move.CONFIRM: _OPEN,
    Move.HANDLE_OBJECTION: _OPEN,
    Move.HOLD_WAIT: _OPEN | {Move.GREET, Move.VOICEMAIL},
    Move.VOICEMAIL: frozenset({Move.CLOSE, Move.STOP}),
    Move.CLOSE: frozenset(),
    Move.STOP: frozenset(),
}


def allowed_next(prev: Move | None, kind: CalleeKind) -> frozenset[Move]:
    """The moves that may legally follow ``prev`` for this callee kind."""
    return TRANSITIONS[prev] & KIND_MOVES[kind]


def transition_ok(prev: Move | None, nxt: Move, kind: CalleeKind) -> bool:
    return nxt in allowed_next(prev, kind)


# ------------------------------------------------------------------ decisions and context


class Effect(BaseModel):
    """A side effect the engine applies after the line is spoken (state is not mutated by the
    policy). kind: approval | commitment | next_action | do_not_call | answer | advance | status |
    resume | awaiting | callback_time | switch_language | flag"""

    kind: str
    data: dict[str, Any] = Field(default_factory=dict)


class MoveDecision(BaseModel):
    move: Move
    variant: str  # a line variant of the move (see lines.py)
    slots: dict[str, str] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = 1.0
    source: str = "rules"  # rules | llm
    continue_turn: bool = False  # speak the next decision in the same breath (no listen)
    terminal_status: OutcomeStatus | None = None  # set on CLOSE/STOP: the call ends with this
    effects: list[Effect] = Field(default_factory=list)
    silent: bool = False  # no spoken line (DTMF-only IVR step)
    authorizes_commitment: bool = False  # the commitment guard allowed this line's "yes"
    allow_repeat: bool = False  # the truthful AI answer may be repeated when asked again


@dataclass
class CallState:
    """Mutable per-call state. Only the engine writes it."""

    kind: CalleeKind
    language: CallLanguage
    last_move: Move | None = None
    last_variant: str | None = None
    disclosed: bool = False
    purpose_said: bool = False
    # agenda: ("purpose",) then ("message", i) for each must_say, then ("ask", j) for each ask
    agenda: list[tuple[str, int]] = field(default_factory=list)
    agenda_idx: int = 0  # next agenda item to deliver
    last_item: int | None = None  # the item last delivered (awaiting the callee's reaction)
    resume_mode: str = "next"  # after a chained answer: deliver the "next" item or ask "again"
    awaiting_before_hold: str = "none"
    awaiting: str = "none"  # none | go_ahead | answer | ack | readback | busy_time | callback_ok
    ask_attempts: int = 0
    clarifies: int = 0
    silences: int = 0
    off_topic: int = 0
    refusals: int = 0
    unknown_streak: int = 0
    turns: int = 0  # callee turns processed
    friday_lines: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    commitments: list[Commitment] = field(default_factory=list)
    approvals: list[ApprovalRequest] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    callback_time: str | None = None
    pending_value: str | None = None  # a heard value waiting for the callee's "yes, correct"
    resume_pending: bool = False
    ivr_steps: int = 0
    ivr_path: list[str] = field(default_factory=list)
    hold_s: float = 0.0
    user_questions: int = 0
    used_line_ids: list[str] = field(default_factory=list)
    do_not_call: bool = False
    health_note: str = ""
    flags: set[str] = field(default_factory=set)
    terminal: OutcomeStatus | None = None


class PolicyContext(BaseModel):
    """Everything a policy sees to pick the next move."""

    model_config = {"arbitrary_types_allowed": True}

    brief: CallBrief
    kind: CalleeKind
    state: Any  # CallState (pydantic cannot validate a dataclass with sets cleanly)
    understanding: Any | None  # Understanding of the callee's latest utterance, None at start
    allowed: frozenset[Move]


@runtime_checkable
class MovePolicy(Protocol):
    async def choose(self, ctx: PolicyContext) -> MoveDecision: ...


# ------------------------------------------------------------------ LLM-backed policy


def policy_payload(ctx: PolicyContext) -> dict[str, Any]:
    """What the model is shown: no private facts, ever. The model only sees public brief text,
    the intent code's reading of the callee's words and the list of legal moves."""
    from friday.liveagent.slotguard import public_brief_view

    u: Understanding | None = ctx.understanding
    st: CallState = ctx.state
    return {
        "brief": public_brief_view(ctx.brief),
        "kind": ctx.kind.value,
        "allowed_moves": sorted(m.value for m in ctx.allowed),
        "last_move": st.last_move.value if st.last_move else None,
        "awaiting": st.awaiting,
        "agenda_remaining": [list(a) for a in st.agenda[st.agenda_idx :]],
        "callee_heard": (u.text if u else ""),
        "callee_intent": (u.intent.value if u else None),
    }


class LLMMovePolicy:
    """Lets a model choose the next move among the legal ones. Hard rules and mandatory
    responses (stop, are-you-AI, secrets, money, commitments, IVR, voicemail) are decided by
    code BEFORE the model is asked; the model's output is validated (legal move, known variant,
    verified slots) and any invalid output falls back to the rule policy."""

    def __init__(self, model: MoveModel, fallback: MovePolicy | None = None) -> None:
        from friday.liveagent.rules import RuleBasedPolicy

        self.model = model
        self.fallback: MovePolicy = fallback or RuleBasedPolicy()
        self.rejected: list[str] = []  # reasons, for the audit trail and tests

    async def choose(self, ctx: PolicyContext) -> MoveDecision:
        from friday.liveagent import lines as L
        from friday.liveagent.rules import mandatory_decision
        from friday.liveagent.slotguard import verify_slots

        forced = mandatory_decision(ctx)
        if forced is not None:
            return forced
        try:
            raw = await self.model.propose(policy_payload(ctx))
            move = Move(str(raw.get("move", "")))
            variant = str(raw.get("variant", ""))
            slots = {str(k): str(v) for k, v in dict(raw.get("slots") or {}).items()}
        except Exception as exc:  # unparsable, unknown move, model error
            return await self._reject(ctx, f"unparsable model output: {exc!r}")
        if move not in ctx.allowed:
            return await self._reject(ctx, f"move {move.value} not legal here")
        if move in TERMINAL_MOVES:
            return await self._reject(ctx, "the model may not end the call")
        if not L.has_variant(move, variant):
            return await self._reject(ctx, f"unknown variant {move.value}.{variant}")
        u: Understanding | None = ctx.understanding
        heard = u.text if u else ""
        problems = verify_slots(slots, ctx.brief, heard)
        if problems:
            return await self._reject(ctx, "ungrounded slots: " + "; ".join(problems))
        need = L.required_slots(move, variant)
        if not need <= set(slots):
            return await self._reject(ctx, f"missing slots {sorted(need - set(slots))}")
        return MoveDecision(
            move=move,
            variant=variant,
            slots=slots,
            reason=str(raw.get("reason", ""))[:200],
            confidence=float(raw.get("confidence", 0.5) or 0.5),
            source="llm",
        )

    async def _reject(self, ctx: PolicyContext, why: str) -> MoveDecision:
        self.rejected.append(why)
        d = await self.fallback.choose(ctx)
        return d.model_copy(update={"reason": f"llm rejected ({why}); " + d.reason})
