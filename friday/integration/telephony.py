"""The production telephony line for consumer calls: ``ConsumerTelephonyFactory``.

It is the one missing piece between the W2 live engine and a real phone call. The engine talks to a
``TelephonyPort``; this factory dials the allow-listed number through the existing Sarvam/Vobiz call
leg (``friday.voice.telephony.sarvam``) and hands the engine that leg as a port
(``friday.liveagent.sarvam_adapter.SarvamLegPort``). The leg already does the media work: streaming
speech to text, text to speech, barge-in, the latency switches (all read from the same settings as
every other call). Nothing in the voice stack is changed.

What the factory adds, and tests (tests/integration/test_consumer_telephony.py):

* ``authorize`` + ``open`` REFUSE to dial unless ALL of these hold: the mode is live (a simulated
  line is only possible when the factory was built ``simulated=True``), the profile is ``pilot``,
  ``FRIDAY_CONSUMER_CALLS_ENABLED`` is true, the kill switch is off (``FRIDAY_CALLS_ENABLED`` and
  ``friday pause``), the number ACTUALLY dialled (after ``vendor_call_redirect_to``) is on the
  pilot allow-list, the brief carries a recorded approval that still matches its content, and the
  W1 ``CallGate`` says allow right now (windows, per-number limits, do-not-call and the rest).
* The caller ID comes from the number pool (``tasks.number_pool``), falling back to the first
  configured Vobiz caller ID; a paced or blocked pool refuses.
* ``MeteredPort`` wraps the leg: it enforces the maximum duration with a backstop beyond the
  engine's own limit, stops the call when the kill switch goes on mid-call, and records the
  transcript, the languages heard and the reply gaps.
* Dial results that never reach a person (busy, no answer, voicemail detected before the first
  word, provider failure) end the call with the matching W1 outcome and nothing is said.
  A line that drops, a callee who hangs up and the maximum duration come out of the engine and the
  backstop (DROPPED -> failed, CUT_OFF -> partial).
* After the call: the transcript and a masked JSON call log are written under ``var/`` (gitignored),
  the recording reference (provider URL) is handed back so W1 stores it and the retention sweep
  deletes it. A recording is NEVER announced on the call (founder decision).

Numbers appear in logs and output only masked to the last two digits (``mask2``).
UNVERIFIED on a live call: this workstream placed no real call.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from friday.calls.models import CallBrief as CallsBrief
from friday.calls.models import OutcomeStatus as CallsStatus
from friday.calls.numbers import canonical
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import DialStatus, NumberOutcome, OutboundCallRequest, new_id
from friday.integration.bridge import (
    DialNotConnected,
    LineFacts,
    NoTelephony,
    TelephonyLease,
)
from friday.liveagent.contracts import CallBrief as LiveBrief
from friday.liveagent.contracts import Callee as LiveCallee
from friday.liveagent.contracts import CallLanguage, LiveCallResult
from friday.liveagent.contracts import OutcomeStatus as LiveStatus
from friday.liveagent.ports import CallDropped, HeardUtterance, TelephonyPort, UserChannel

log = get_logger(__name__)

BACKSTOP_GRACE_S = 15.0  # the port ends a call this long after the engine's own maximum
PERMIT_TTL_S = 120.0  # an authorisation is good for the one open() that follows it
RECORDING_WAIT_S = 8.0
DEFAULT_LOG_DIR = Path("var") / "consumer_calls"

_LONG_DIGITS = re.compile(r"(?<!\w)\+?\d(?:[\s\-().]?\d){5,}(?!\w)")


# ----------------------------------------------------------------------------- masking
def mask2(number: str | None) -> str:
    """'+919876543210' -> '+9*********10': only the last two digits are shown."""
    if not number:
        return "<none>"
    n = len(number)
    if n <= 4:
        return "*" * n
    return number[0] + "*" * (n - 3) + number[-2:]


def scrub_text(text: str) -> str:
    """Any run of six or more digits (a number the callee read out) is masked to its last two."""

    def repl(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group())
        return "*" * max(len(digits) - 2, 0) + digits[-2:]

    return _LONG_DIGITS.sub(repl, text)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


# ----------------------------------------------------------------------------- refusals
class DialRefused(NoTelephony):
    """A rule said no. ``code`` is a machine code, not user text; the call ends FAILED."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def line_permitted(settings: Settings) -> bool:
    """True when the production wiring may build the real line: live mode and the pilot profile.
    (The simulator profile keeps the refusing default; tests and the demo plug their own fake.)"""
    return bool(settings.is_live and settings.is_pilot and settings.consumer_calls_enabled)


# ----------------------------------------------------------------------------- the line opener
@dataclass
class OpenedLine:
    """A connected leg: the port plus what the factory needs to account for the call afterwards."""

    port: TelephonyPort
    clock: Callable[[], float] | None = None
    user_channel: UserChannel | None = None
    from_number: str | None = None
    recording: Callable[[], Awaitable[str | None]] | None = None
    reply_gaps: Callable[[], list[float]] | None = None  # ms, caller stopped -> first audio queued
    block_signal: Callable[[], str | None] | None = None


class LineOpener(Protocol):
    async def dial(
        self,
        *,
        brief: LiveBrief,
        callee: LiveCallee,
        to: str,
        from_number: str | None,
        max_seconds: int,
        ring_timeout_s: int,
        call_id: str,
        record: bool,
    ) -> OpenedLine:
        """Dial and wait for an answer. Raise ``DialNotConnected`` when nobody is reached."""
        ...


_DIAL_TO_STATUS: dict[DialStatus, CallsStatus] = {
    DialStatus.BUSY: CallsStatus.BUSY,
    DialStatus.NO_ANSWER: CallsStatus.NO_ANSWER,
    DialStatus.VOICEMAIL: CallsStatus.VOICEMAIL,
    DialStatus.FAILED: CallsStatus.FAILED,
}


class VobizLineOpener:
    """The real opener: ``place_call`` on the container's telephony provider (Sarvam/Vobiz), wait
    for the answer, wrap the leg with ``SarvamLegPort``. ``telephony`` may be the provider or a
    function returning it (resolved on the first call, so wiring never fails at start-up)."""

    def __init__(self, telephony: Any, settings: Settings) -> None:
        self._telephony = telephony
        self.settings = settings

    def _tel(self) -> Any:
        return self._telephony() if callable(self._telephony) else self._telephony

    async def dial(
        self,
        *,
        brief: LiveBrief,
        callee: LiveCallee,
        to: str,
        from_number: str | None,
        max_seconds: int,
        ring_timeout_s: int,
        call_id: str,
        record: bool,
    ) -> OpenedLine:
        from friday.core.models import Language
        from friday.liveagent.sarvam_adapter import SarvamLegPort

        req = OutboundCallRequest(
            to_phone=to,
            task_id=call_id,
            record=record,
            ring_timeout_s=ring_timeout_s,
            max_duration_s=max_seconds,
            language=Language(brief.language.value),
            metadata={"call_id": call_id},
            from_number=from_number,
        )
        try:
            leg = await self._tel().place_call(req)
        except Exception as e:  # noqa: BLE001 - provider error, kill-switch guard, anything
            log.warning("consumer call %s could not be placed (%s)", call_id, type(e).__name__)
            raise DialNotConnected(CallsStatus.FAILED, type(e).__name__) from e
        try:
            status = await leg.wait_for_answer(ring_timeout_s)
        except Exception as e:  # noqa: BLE001
            with contextlib.suppress(Exception):
                await leg.hangup()
            raise DialNotConnected(CallsStatus.FAILED, type(e).__name__) from e
        if status != DialStatus.ANSWERED:
            signal = getattr(leg, "block_signal", None)
            with contextlib.suppress(Exception):
                await leg.hangup()  # a machine that picked up must not stay on a paid line
            if signal in ("blocked", "rejected"):
                raise DialNotConnected(CallsStatus.FAILED, f"call {signal}")
            raise DialNotConnected(_DIAL_TO_STATUS.get(status, CallsStatus.FAILED), str(status))

        async def recording() -> str | None:
            wait = getattr(leg, "wait_recording", None)
            if wait is not None:
                await wait(RECORDING_WAIT_S)
            return await leg.recording_url()

        return OpenedLine(
            port=SarvamLegPort(leg),
            from_number=getattr(leg, "from_number", None) or from_number,
            recording=recording if record else None,
            reply_gaps=lambda: [float(x) for x in getattr(leg, "reply_gaps", [])],
            block_signal=lambda: getattr(leg, "block_signal", None),
        )


class PersonaLineOpener:
    """Offline opener over ``integration.sim.PersonaTelephony`` (the dry run and the tests): the
    callee is a scripted W2 persona. ``dial_status`` makes it behave like a busy or silent phone."""

    def __init__(self, sim: Any, *, dial_status: CallsStatus | None = None) -> None:
        self.sim, self.dial_status = sim, dial_status
        self.dialled: list[str] = []

    async def dial(
        self,
        *,
        brief: LiveBrief,
        callee: LiveCallee,
        to: str,
        from_number: str | None,
        max_seconds: int,
        ring_timeout_s: int,
        call_id: str,
        record: bool,
    ) -> OpenedLine:
        self.dialled.append(to)
        if self.dial_status is not None:
            raise DialNotConnected(self.dial_status)
        lease = await self.sim.open(
            brief=brief, callee=callee, dial_number=to, from_number=from_number
        )
        return OpenedLine(
            port=lease.port, clock=lease.clock, user_channel=lease.user_channel,
            from_number=from_number,
        )  # fmt: skip


# ----------------------------------------------------------------------------- metered port
class MeteredPort:
    """Wraps the engine's port: backstop on the maximum duration, kill switch, transcript."""

    def __init__(
        self,
        inner: TelephonyPort,
        *,
        clock: Callable[[], float],
        hard_limit_s: float,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.inner, self.clock, self.hard_limit_s = inner, clock, hard_limit_s
        self.should_stop = should_stop
        self.t0 = clock()
        self.turns: list[dict[str, Any]] = []
        self.languages: list[str] = []
        self.gaps_ms: list[float] = []
        self.ended_by: str | None = None  # max_duration | kill_switch | line_ended | friday
        self._heard_at: float | None = None
        self._hung = False

    def elapsed(self) -> float:
        return self.clock() - self.t0

    async def _guard(self) -> None:
        if self.should_stop is not None and self.should_stop():
            self.ended_by = "kill_switch"
            await self.hangup()
            raise CallDropped("stopped by the kill switch")
        if self.elapsed() > self.hard_limit_s:
            self.ended_by = "max_duration"
            await self.hangup()
            raise CallDropped("maximum call duration reached")

    def _add(self, speaker: str, text: str, lang: str | None) -> None:
        self.turns.append(
            {"t": round(self.elapsed(), 1), "who": speaker, "lang": lang, "text": scrub_text(text)}
        )

    async def speak(self, text: str, language: CallLanguage) -> None:
        await self._guard()
        if self._heard_at is not None:
            self.gaps_ms.append(max(0.0, (self.clock() - self._heard_at) * 1000.0))
            self._heard_at = None
        self._add("friday", text, language.value)
        try:
            await self.inner.speak(text, language)
        except CallDropped:
            self.ended_by = self.ended_by or "line_ended"
            raise

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        await self._guard()
        remaining = self.hard_limit_s - self.elapsed()
        try:
            heard = await self.inner.listen(max(0.5, min(timeout_s, remaining + 0.5)))
        except CallDropped:
            self.ended_by = self.ended_by or "line_ended"
            raise
        if heard is not None and heard.text.strip():
            self._add("callee", heard.text, heard.language)
            if heard.language and heard.language not in self.languages:
                self.languages.append(heard.language)
            self._heard_at = self.clock()
        return heard

    async def send_dtmf(self, digits: str) -> None:
        await self._guard()
        await self.inner.send_dtmf(digits)

    async def hangup(self) -> None:
        if self._hung:
            return
        self._hung = True
        with contextlib.suppress(Exception):
            await self.inner.hangup()


# ----------------------------------------------------------------------------- the call log
@dataclass
class CallLog:
    """One consumer call as written to ``var/consumer_calls/`` (numbers masked to two digits)."""

    call_id: str
    request_ref: str
    to: str
    from_: str
    dial_status: str
    started_at: str
    duration_s: float = 0.0
    turns: int = 0
    languages: list[str] = field(default_factory=list)
    reply_gaps_ms: list[float] = field(default_factory=list)
    gap_p50_ms: float | None = None
    gap_p95_ms: float | None = None
    ended_by: str | None = None
    engine_status: str | None = None
    safety_blocks: int = 0
    recording_ref_kept: bool = False
    transcript_path: str | None = None
    log_path: str | None = None


@dataclass
class _Permit:
    request_id: str
    approval_hash: str
    at: float


_PERMIT: ContextVar[_Permit | None] = ContextVar("consumer_dial_permit", default=None)
_SAFETY_EVENTS = frozenset({"guard", "hard_stop", "policy_rejected"})


class ConsumerTelephonyFactory:
    """``bridge.TelephonyFactory`` for real consumer calls. See the module docstring."""

    def __init__(
        self,
        *,
        settings: Settings,
        opener: LineOpener,
        gate: Any,
        store: Any,
        users: Any,
        hasher: Any,
        calls_settings: Any = None,
        pool: Any = None,
        clock: Any = None,
        log_dir: Path | None = None,
        simulated: bool = False,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        from friday.calls.settings import CallsSettings
        from friday.core.clock import SystemClock

        self.settings, self.opener = settings, opener
        self.gate, self.store, self.users, self.hasher = gate, store, users, hasher
        self.cs = calls_settings or CallsSettings()
        self.pool, self.clock = pool, clock or SystemClock()
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.simulated = simulated  # only the dry run and tests; never set by production wiring
        self._mono = monotonic or time.monotonic
        self.logs: list[CallLog] = []

    # ------------------------------------------------------------------ rules
    def _stopped(self) -> bool:
        from friday.pause import is_paused

        return (not self.cs.enabled) or is_paused(self.settings)

    def static_refusal(self) -> str | None:
        """The settings-level reasons, checked at authorise time and again at open time."""
        s = self.settings
        if not self.simulated and not s.is_live:
            return "not_live"
        if not s.is_pilot:
            return "profile_not_pilot"  # real consumer calls are pilot-only for now
        if not s.consumer_calls_enabled:
            return "switch_off"
        if self._stopped():
            return "kill_switch"
        if not s.pilot_allowed_numbers:
            return "no_allow_list"
        return None

    def _allow_listed(self, number: str) -> bool:
        s = self.settings
        return number in set(s.pilot_allowed_numbers) and not s.pilot_dial_blocked(number)

    async def authorize(self, brief: CallsBrief, callee: Any) -> None:
        """Called by the adapter with the W1 brief right before ``open``. Raises ``DialRefused``."""
        if (why := self.static_refusal()) is not None:
            raise DialRefused(why)
        number = canonical(getattr(callee, "number", "") or "")
        if number is None:
            raise DialRefused("invalid_number")
        if not brief.approved or not brief.approval_hash or not brief.is_approved_as_is():
            raise DialRefused("no_approved_brief")
        if self.hasher is None or brief.callee_number_hash != self.hasher.hash(number):
            raise DialRefused("approval_number_mismatch")
        if self.gate is None or self.store is None or self.users is None:
            raise DialRefused("no_gate")
        request = await self.store.get_request(brief.request_id)
        user = await self.users.get(brief.user_id)
        if request is None or user is None:
            raise DialRefused("unknown_request")
        decision = await self.gate.decide(request, brief, user, self.clock.now())
        if not decision.allowed:
            raise DialRefused(f"gate_{decision.verdict.value}:{','.join(decision.reasons)}")
        _PERMIT.set(_Permit(brief.request_id, brief.approval_hash, self._mono()))

    # ------------------------------------------------------------------ caller ID
    async def _caller_id(self, dial_number: str, given: str | None) -> tuple[str | None, bool]:
        """(number to present or None = let the provider pick, reserved a pool slot)."""
        if given:
            return given, False
        pool = self.pool
        if pool is not None and await pool.has_numbers():
            choice = await pool.choose_for(dial_number)
            if choice is None:
                raise DialRefused("caller_id_unavailable")
            if choice.not_before is not None:
                raise DialRefused("caller_id_paced")  # no slot was taken
            return choice.number.phone, True
        configured = list(self.settings.sarvam_caller_ids or self.settings.friday_numbers or [])
        return (configured[0] if configured else None), False

    # ------------------------------------------------------------------ open
    async def open(
        self, *, brief: LiveBrief, callee: LiveCallee, dial_number: str, from_number: str | None
    ) -> TelephonyLease:
        permit = _PERMIT.get()
        _PERMIT.set(None)  # one authorisation, one open
        if permit is None or self._mono() - permit.at > PERMIT_TTL_S:
            raise DialRefused("no_approved_brief")
        if (why := self.static_refusal()) is not None:
            raise DialRefused(why)
        if not self._allow_listed(dial_number):
            raise DialRefused("not_allow_listed")  # checked against the number really dialled
        max_s = int(min(brief.limits.max_call_seconds, self.cs.max_call_seconds))
        call_id = new_id()
        started = self.clock.now()
        presented, reserved = await self._caller_id(dial_number, from_number)
        log_ = CallLog(
            call_id=call_id, request_ref=permit.request_id[:8], to=mask2(dial_number),
            from_=mask2(presented), dial_status="dialling", started_at=started.isoformat(),
        )  # fmt: skip
        self.logs.append(log_)
        try:
            opened = await self.opener.dial(
                brief=brief, callee=callee, to=dial_number, from_number=presented,
                max_seconds=max_s, ring_timeout_s=self.settings.call_ring_timeout_s,
                call_id=call_id, record=bool(self.settings.call_record),
            )  # fmt: skip
        except DialNotConnected as e:
            log_.dial_status = e.status.value
            await self._release(presented if reserved else None, dial_number, e.status, 0.0)
            self._write(log_, [])
            log.info("consumer call %s to=%s not connected: %s", call_id, log_.to, e.status.value)
            raise
        except BaseException:
            log_.dial_status = "failed"
            await self._release(presented if reserved else None, dial_number, CallsStatus.FAILED, 0)
            raise
        log_.dial_status = "answered"
        if opened.from_number:
            log_.from_ = mask2(opened.from_number)
        clock = opened.clock or self._mono
        meter = MeteredPort(
            opened.port, clock=clock, hard_limit_s=max_s + BACKSTOP_GRACE_S,
            should_stop=self._stopped,
        )  # fmt: skip

        async def finish(result: LiveCallResult | None) -> LineFacts:
            return await self._finish(
                result, meter, opened, log_, dial_number, presented if reserved else None
            )

        return TelephonyLease(meter, opened.clock, opened.user_channel, finish)

    # ------------------------------------------------------------------ after the call
    async def _finish(
        self,
        result: LiveCallResult | None,
        meter: MeteredPort,
        opened: OpenedLine,
        log_: CallLog,
        dial_number: str,
        reserved_number: str | None,
    ) -> LineFacts:
        await meter.hangup()  # idempotent; the engine already hung up in the normal case
        facts = LineFacts()
        backstop = meter.ended_by in ("max_duration", "kill_switch")
        if (
            result is not None
            and backstop
            and result.outcome.status in (LiveStatus.DROPPED, LiveStatus.UNRESOLVED)
        ):
            facts.status_override = LiveStatus.CUT_OFF
        ref: str | None = None
        if opened.recording is not None:
            try:
                ref = await opened.recording()
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "consumer call %s: recording unavailable (%s)", log_.call_id, type(e).__name__
                )
        facts.recording_ref = ref
        gaps = [g for g in (opened.reply_gaps() if opened.reply_gaps else []) if g >= 0]
        gaps = gaps or meter.gaps_ms
        log_.duration_s = round(result.duration_s if result else meter.elapsed(), 1)
        log_.turns = len(meter.turns)
        log_.languages = list(meter.languages)
        log_.reply_gaps_ms = [round(g) for g in gaps]
        log_.gap_p50_ms, log_.gap_p95_ms = percentile(gaps, 50), percentile(gaps, 95)
        log_.ended_by = meter.ended_by
        log_.engine_status = result.outcome.status.value if result else None
        log_.safety_blocks = sum(
            1 for e in (result.events if result else []) if e.kind in _SAFETY_EVENTS
        )
        log_.recording_ref_kept = bool(ref)
        blocked = opened.block_signal() if opened.block_signal else None
        spoke = any(t["who"] == "callee" for t in meter.turns)
        outcome = (
            CallsStatus.FAILED
            if blocked
            else (CallsStatus.COMPLETED if spoke else CallsStatus.NO_ANSWER)
        )
        await self._release(reserved_number, dial_number, outcome, log_.duration_s)
        self._write(log_, meter.turns)
        log.info(
            "consumer call %s to=%s from=%s dur=%.0fs turns=%d langs=%s gap_p50=%s gap_p95=%s "
            "end=%s engine=%s",
            log_.call_id, log_.to, log_.from_, log_.duration_s, log_.turns,
            ",".join(log_.languages) or "-", log_.gap_p50_ms, log_.gap_p95_ms,
            log_.ended_by or "friday", log_.engine_status,
        )  # fmt: skip
        return facts

    async def _release(
        self, pool_number: str | None, dial_number: str, status: CallsStatus, duration_s: float
    ) -> None:
        if self.pool is None or pool_number is None:
            return
        mapped = {
            CallsStatus.BUSY: NumberOutcome.BUSY,
            CallsStatus.NO_ANSWER: NumberOutcome.NO_ANSWER,
            CallsStatus.VOICEMAIL: NumberOutcome.NO_ANSWER,
            CallsStatus.FAILED: NumberOutcome.FAILED,
        }.get(status, NumberOutcome.ANSWERED)
        with contextlib.suppress(Exception):
            await self.pool.record_outcome(
                pool_number, mapped, business_phone=dial_number, duration_s=duration_s
            )
        with contextlib.suppress(Exception):
            await self.pool.release(pool_number)

    def _write(self, log_: CallLog, turns: list[dict[str, Any]]) -> None:
        """Transcript (text) and call log (JSON) under ``var/``; numbers masked, never a key."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromisoformat(log_.started_at).strftime("%Y%m%d-%H%M%S")
            base = self.log_dir / f"consumer-call-{stamp}-{log_.call_id[:8]}"
            if turns:
                lines = [
                    f"Friday consumer call {log_.call_id[:8]} to {log_.to} at {log_.started_at}",
                    "",
                ]
                for t in turns:
                    lang = f" [{t['lang']}]" if t["lang"] else ""
                    lines.append(f"{t['t']:6.1f}s {t['who'].upper()}{lang}: {t['text']}")
                path = base.with_suffix(".txt")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                log_.transcript_path = str(path)
            jpath = base.with_suffix(".json")
            log_.log_path = str(jpath)
            jpath.write_text(json.dumps(asdict(log_), indent=2), encoding="utf-8")
        except OSError as e:
            log.warning(
                "consumer call %s: could not write the call log (%s)",
                log_.call_id,
                type(e).__name__,
            )
