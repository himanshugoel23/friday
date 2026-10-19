"""The bridge between W1 (before/after a call) and W2 (during a call).

The two packages each have a ``CallBrief``, a ``Callee`` and a ``CallOutcome`` with different
shapes. The disagreements are settled HERE, in one place:

* W1 brief -> W2 brief: ``to_live_brief`` (kinds, language, fact dicts, the user's name, limits).
* W2 result -> W1 outcome: ``to_outcome`` (status table in ``STATUS_MAP``, commitments, approvals).
* ``LiveEngineAdapter``: the ``friday.calls.interfaces.LiveCallEngine`` implementation that wraps
  the W2 engine. It needs a ``TelephonyFactory`` to get a line; the default one REFUSES, so
  nothing can dial until someone plugs a real (or simulated) line in on purpose.
* ``LiveOpeningLineProvider``: the exact first utterance of the call, obtained by running the W2
  engine against a silent probe line, so the text the user approves is the text that is spoken.

Only one W2 model changed for this bridge: ``CallOutcome`` gained ``answers`` and
``callback_time`` (structured copies of what its English summary says).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from friday.calls.interfaces import Callee as CallsCallee
from friday.calls.models import CallBrief as CallsBrief
from friday.calls.models import CalleeKind as CallsKind
from friday.calls.models import CallOutcome as CallsOutcome
from friday.calls.models import Commitment as CallsCommitment
from friday.calls.models import NextAction
from friday.calls.models import OutcomeStatus as CallsStatus
from friday.calls.numbers import mask
from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger
from friday.integration import copy
from friday.liveagent import lines as live_lines
from friday.liveagent.contracts import CallBrief as LiveBrief
from friday.liveagent.contracts import Callee as LiveCallee
from friday.liveagent.contracts import CalleeKind as LiveKind
from friday.liveagent.contracts import CallLanguage, LiveCallResult
from friday.liveagent.contracts import Limits as LiveLimits
from friday.liveagent.contracts import OutcomeStatus as LiveStatus
from friday.liveagent.engine import EngineConfig
from friday.liveagent.engine import LiveCallEngine as LiveEngine
from friday.liveagent.ports import (
    CallDropped,
    HeardUtterance,
    LineModel,
    TelephonyPort,
    UserChannel,
)

log = get_logger(__name__)

# ----------------------------------------------------------------------------- kinds and language
_ELDERS = frozenset(
    {"mother", "father", "mummy", "papa", "maa", "dadi", "dada", "nani", "nana", "grandmother",
     "grandfather", "grandparent", "elder", "parent"}
)  # fmt: skip


def live_kind(kind: CallsKind, relationship: str | None = None) -> LiveKind:
    """W1 has one FAMILY_FRIEND kind; W2 separates elders (slower, more respectful) from peers.
    A GROUP parent never dials; its children carry their own kinds."""
    if kind == CallsKind.FAMILY_FRIEND:
        rel = (relationship or "").lower().strip()
        return LiveKind.FAMILY_ELDER if rel in _ELDERS else LiveKind.FRIEND
    return {
        CallsKind.BUSINESS: LiveKind.BUSINESS,
        CallsKind.PROVIDER: LiveKind.PROVIDER,
        CallsKind.CUSTOMER_CARE: LiveKind.CUSTOMER_CARE,
        CallsKind.OFFICIAL: LiveKind.OFFICIAL,
        CallsKind.UNKNOWN: LiveKind.UNKNOWN,
        CallsKind.GROUP: LiveKind.UNKNOWN,
    }[kind]


def live_language(language: str | None) -> CallLanguage:
    try:
        return CallLanguage(language or "hinglish")
    except ValueError:
        return CallLanguage.HINGLISH


def live_tone(tone: str | None) -> str:
    t = (tone or "").lower()
    if "formal" in t or "firm" in t:
        return "formal"
    if "brief" in t:
        return "brief"
    if "warm" in t:
        return "warm"
    return "casual" if "friendly" in t else "warm"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


# ----------------------------------------------------------------------------- W1 brief -> W2 brief
def to_live_brief(
    brief: CallsBrief, *, callee: CallsCallee | None = None, max_call_seconds: int | None = None
) -> LiveBrief:
    """Everything the W2 engine needs, from what the user approved.

    * ``must_say`` items that repeat the goal are dropped (the purpose line already says them);
      a question purpose is replaced by a fixed lead-in so it is asked once, in the ask list.
    * ``limits``: only the money ceiling and the call length carry over. ``allowed_times`` and
      ``allowed_commitments`` stay empty on purpose: W1's brief has no such approval yet, so any
      promise the callee asks for becomes a ``needs_user_approval`` item (the safe default).
    * ``shareable_facts`` / ``private_facts`` become the dicts W2 wants; private facts never
      reach a model or a line (W2 guards check them).
    """
    lang = live_language(brief.language)
    goal = brief.goal.strip()
    must_say = [m for m in brief.must_say if m.strip() and _norm(m) not in _norm(goal)]
    ask_list = [q for q in brief.ask_list if q.strip()]
    goal_spoken: str | None = goal
    if any(_norm(q) in _norm(goal) or _norm(goal) in _norm(q) for q in ask_list):
        goal_spoken = copy.spoken("goal_spoken_ask", lang.value)
    seconds = max_call_seconds or (callee.max_duration_s if callee else None)
    limits = LiveLimits(
        max_amount_inr=brief.limits.max_price_inr,
        allowed_times=[],
        allowed_commitments=[],
        max_call_seconds=int(seconds) if seconds else 300,
    )
    return LiveBrief(
        goal=goal,
        must_say=must_say,
        must_not_say=list(brief.must_not_say),
        ask_list=ask_list,
        limits=limits,
        tone=live_tone(brief.tone),
        relationship=live_kind(brief.callee_kind, brief.relationship),
        shareable_facts={f"fact{i + 1}": f for i, f in enumerate(brief.shareable_facts) if f},
        private_facts={f"private{i + 1}": f for i, f in enumerate(brief.private_facts) if f},
        language=lang,
        user_name=(brief.user_display_name or "").strip()
        or copy.spoken("unnamed_user", lang.value),
        goal_spoken=goal_spoken,
        callee_name=None if brief.callee_kind == CallsKind.GROUP else brief.callee_name,
        voicemail_allowed=False,  # W1's brief has no voicemail consent yet: never leave a message
    )


def to_live_callee(brief: CallsBrief, callee: CallsCallee) -> LiveCallee:
    """The number is NOT passed on: the engine never needs it, so it cannot leak from there."""
    return LiveCallee(
        kind=live_kind(callee.kind, brief.relationship), name=callee.name or None, number=None
    )


# ------------------------------------------------------------------ W2 result -> W1 outcome
STATUS_MAP: dict[LiveStatus, CallsStatus] = {
    LiveStatus.COMPLETED: CallsStatus.COMPLETED,
    LiveStatus.PARTIAL: CallsStatus.PARTIAL,
    # W1 has no "needs approval" status: the approvals travel in ``needs_user_approval`` and the
    # call is PARTIAL (not retried), exactly as the report builder expects
    LiveStatus.NEEDS_USER_APPROVAL: CallsStatus.PARTIAL,
    LiveStatus.CALL_BACK_LATER: CallsStatus.CALLBACK_LATER,
    LiveStatus.DECLINED: CallsStatus.DECLINED,
    # a message was left: retrying would leave it again, so this is a finished (partial) call
    LiveStatus.VOICEMAIL_LEFT: CallsStatus.PARTIAL,
    LiveStatus.VOICEMAIL_NO_MESSAGE: CallsStatus.VOICEMAIL,
    LiveStatus.UNREACHABLE: CallsStatus.NO_ANSWER,
    LiveStatus.WRONG_NUMBER: CallsStatus.WRONG_PERSON,
    LiveStatus.DO_NOT_CALL: CallsStatus.OPTED_OUT,
    LiveStatus.DISTRESS: CallsStatus.SAFETY_STOP,
    LiveStatus.HOSTILE: CallsStatus.SAFETY_STOP,
    LiveStatus.UNRESOLVED: CallsStatus.FAILED,
    LiveStatus.CUT_OFF: CallsStatus.PARTIAL,
    LiveStatus.DROPPED: CallsStatus.FAILED,
}
_SUMMARY_KEY: dict[LiveStatus, str] = {
    LiveStatus.VOICEMAIL_LEFT: "summary_voicemail_left",
    LiveStatus.CUT_OFF: "summary_cut_off",
    LiveStatus.DISTRESS: "summary_distress",
    LiveStatus.HOSTILE: "summary_hostile",
    LiveStatus.UNRESOLVED: "summary_unresolved",
}
_UNANSWERED = "Still unanswered: "
_HEALTH = "The callee mentioned a health problem"


def to_outcome(
    request_id: str,
    result: LiveCallResult,
    *,
    language: str = "hinglish",
    started_at: datetime | None = None,
    attempt: int = 1,
    delivered: bool = False,
) -> CallsOutcome:
    o = result.outcome
    lang = language if language in ("hinglish", "en") else "hinglish"
    status = STATUS_MAP[o.status]
    parts: list[str] = []
    if delivered and o.status == LiveStatus.COMPLETED:
        parts.append(copy.line("summary_delivered", lang))
    if key := _SUMMARY_KEY.get(o.status):
        parts.append(copy.line(key, lang))
    unanswered = [a[len(_UNANSWERED) :] for a in o.next_actions if a.startswith(_UNANSWERED)]
    if unanswered:
        parts.append(copy.line("summary_unanswered", lang, items="; ".join(unanswered)))
    if any(a.startswith(_HEALTH) for a in o.next_actions):
        parts.append(copy.line("summary_health", lang))
    if o.callback_time:
        parts.append(copy.line("summary_callback", lang, when=o.callback_time))
    commitments = [
        CallsCommitment(text=c.text, needs_user_approval=not c.within_limits, approved=None)
        for c in o.commitments
    ]
    asks = [a.text for a in o.needs_user_approval]
    actions: list[NextAction] = []
    if o.status == LiveStatus.VOICEMAIL_LEFT:
        actions = [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE]
    return CallsOutcome(
        request_id=request_id,
        attempt=attempt,
        status=status,
        summary=" ".join(parts),
        answers=dict(o.answers),
        commitments=commitments,
        needs_user_approval=asks,
        next_actions=actions,
        do_not_call_again=o.status == LiveStatus.DO_NOT_CALL,
        started_at=started_at,
        duration_s=float(result.duration_s),
    )


def failed_outcome(request_id: str, started_at: datetime | None, attempt: int = 1) -> CallsOutcome:
    return CallsOutcome(
        request_id=request_id, attempt=attempt, status=CallsStatus.FAILED, started_at=started_at
    )


# ----------------------------------------------------------------------------- the line
class NoTelephony(RuntimeError):
    """No line is plugged in: nothing is dialled."""


@dataclass
class TelephonyLease:
    """One line for one call: the port, the engine clock (simulation) and the ask-the-user hook."""

    port: TelephonyPort
    clock: Callable[[], float] | None = None
    user_channel: UserChannel | None = None


class TelephonyFactory(Protocol):
    async def open(
        self, *, brief: LiveBrief, callee: LiveCallee, dial_number: str, from_number: str | None
    ) -> TelephonyLease:
        """Open a line to ``dial_number``. ``dial_number`` is already the redirect target when a
        test redirect is configured. Raise to refuse; the call then ends as FAILED, undialled."""
        ...


class RefusingTelephonyFactory:
    """The production default until a real line is wired: it never dials anything."""

    async def open(
        self, *, brief: LiveBrief, callee: LiveCallee, dial_number: str, from_number: str | None
    ) -> TelephonyLease:
        raise NoTelephony("no telephony line is configured for consumer calls")


def dial_target(core: Any, number: str) -> str:
    """The number actually dialled: the test redirect (Settings.vendor_call_redirect_to) wins, as
    it does for vendor calls. The pilot allow-list is checked against THAT number."""
    target = getattr(core, "vendor_call_redirect_to", None) or number
    if core is not None and core.pilot_dial_blocked(target):
        raise NoTelephony("dial target is not on the pilot allow-list")
    return target


class LiveEngineAdapter:
    """``friday.calls.interfaces.LiveCallEngine`` over the W2 engine (replaces FakeLiveCallEngine
    in production wiring; the fake stays for unit tests)."""

    def __init__(
        self,
        factory: TelephonyFactory | None = None,
        *,
        core_settings: Any = None,
        clock: Clock | None = None,
        config: EngineConfig | None = None,
        line_model: LineModel | None = None,
        policy: Any = None,
    ) -> None:
        self.factory: TelephonyFactory = factory or RefusingTelephonyFactory()
        self.core, self.clock = core_settings, clock or SystemClock()
        self.config, self.line_model, self.policy = config, line_model, policy
        self.results: list[LiveCallResult] = []  # last results, for tests and the demo
        self.max_kept = 20

    async def _match_approved_opening(
        self, brief: CallsBrief, live_brief: LiveBrief, live_callee: LiveCallee
    ) -> tuple[LiveBrief, LiveCallee]:
        """The user approved ``brief.opening_line``; the engine must say that. A group child
        inherits its parent's line, which was made without a name or a relationship, so when the
        child's own opening would differ the call runs in that neutral register (the fixed
        disclosure is the same either way). If neither matches (an edited line), the engine's
        own opening, which always carries the disclosure, is used and the mismatch is logged."""
        approved = brief.opening_line
        if not approved:
            return live_brief, live_callee
        try:
            if await first_utterance(live_brief) == approved:
                return live_brief, live_callee
            neutral = live_brief.model_copy(
                update={"callee_name": None, "relationship": LiveKind.UNKNOWN}
            )
            if await first_utterance(neutral) == approved:
                return neutral, live_callee.model_copy(
                    update={"kind": LiveKind.UNKNOWN, "name": None}
                )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "consumer call %s: opening check failed (%s)", brief.request_id, type(e).__name__
            )
        return live_brief, live_callee

    async def run(self, brief: CallsBrief, callee: CallsCallee) -> CallsOutcome:
        started = self.clock.now()
        live_brief = to_live_brief(brief, callee=callee)
        live_callee = to_live_callee(brief, callee)
        live_brief, live_callee = await self._match_approved_opening(brief, live_brief, live_callee)
        try:
            dial = dial_target(self.core, callee.number)
            lease = await self.factory.open(
                brief=live_brief,
                callee=live_callee,
                dial_number=dial,
                from_number=callee.from_number,
            )
        except Exception as e:  # noqa: BLE001 - no line means no call, and a clear FAILED
            log.warning(
                "consumer call %s not opened (%s) to=%s",
                brief.request_id,
                type(e).__name__,
                mask(callee.number),
            )
            return failed_outcome(brief.request_id, started)
        cfg = self.config or EngineConfig(max_call_seconds=float(callee.max_duration_s))
        engine = LiveEngine(
            self.policy,
            config=cfg,
            user_channel=lease.user_channel,
            line_model=self.line_model,
            clock=lease.clock,
        )
        result = await engine.run(live_brief, live_callee, lease.port)
        self.results = [*self.results, result][-self.max_kept :]
        if (
            result.friday_lines
            and brief.opening_line
            and not brief.opening_line.startswith(result.friday_lines[0])
        ):  # should not happen: the approved opening is matched above
            log.warning(
                "consumer call %s: spoken opening differs from the approved one", brief.request_id
            )
        return to_outcome(
            brief.request_id,
            result,
            language=brief.language,
            started_at=started,
            delivered=bool(brief.must_say),
        )


# ----------------------------------------------------------------------------- the approved opening
class _ProbeLine:
    """A silent line that only listens to what Friday says first, then hangs up."""

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self._first = True

    async def speak(self, text: str, language: CallLanguage) -> None:
        self.spoken.append(text)

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        if self.spoken:
            raise CallDropped("probe done")
        if self._first:
            self._first = False
            return HeardUtterance(text="Hello?", language="en", audio_class="human", duration_s=1)
        return None

    async def send_dtmf(self, digits: str) -> None:
        return None

    async def hangup(self) -> None:
        return None


async def first_utterance(live: LiveBrief) -> str:
    """What the W2 engine says first for this brief (greeting + disclosure), by running it against
    a silent probe line. Same lines, same guards as a real call."""
    probe = _ProbeLine()
    callee = LiveCallee(kind=live.relationship, name=live.callee_name, number=None)
    await LiveEngine(config=EngineConfig(max_call_seconds=20.0)).run(live, callee, probe)
    if not probe.spoken:
        raise RuntimeError("the live engine produced no opening line")
    return probe.spoken[0]


class LiveOpeningLineProvider:
    """``OpeningLineProvider``: the greeting + disclosure the W2 engine will speak for this brief,
    so the user approves exactly what is said first."""

    async def opening_line(self, brief: CallsBrief, callee_name: str | None) -> str:
        live = to_live_brief(brief)
        if callee_name and not live.callee_name and brief.callee_kind != CallsKind.GROUP:
            live = live.model_copy(update={"callee_name": callee_name})
        return await first_utterance(live)


def all_pending_line_ids() -> list[str]:
    """Ids of every W2 line (for the founder's review kit); re-exported so the demo can count."""
    return [pl.id for pl in live_lines.all_lines()]
