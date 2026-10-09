"""CallSessionRunner (V-2, V-7, V-8, V-9 + inbound E31): one call end to end.

    runner = c.call_runner
    result = await runner.run(brief, ask_user, notify_user)               # outbound
    result = await runner.run_inbound(brief, leg, ask_user, notify_user)  # business called us

Loop (docs/ARCHITECTURE.md §3.2): dial -> fixed disclosure to the first human (and to
every new human after IVR/hold) -> policy.next_call_action() -> guard -> execute.

Guarantees enforced HERE, not only in prompts:
  * the disclosure is spoken by the runner, never by the policy
  * ``friday.core.safety`` on every utterance / hold line / DTMF; ``commits_booking``
    requires ``brief.can_commit(answers)`` (+ delegation price ceiling); "I'm human"
    claims, missing questions/user phone -> blocked: SYSTEM "BLOCKED: ..." turn, policy
    asked again; 3 blocks in a row -> polite safe exit
  * fillers stripped before TTS; language mirroring falls back to a TTS-supported
    language; at most 2 mid-call questions (US-5.6)
  * WAIT_ON_HOLD = hold-listening: ZERO policy calls until a human/IVR prompt, or
    ``max_hold_s`` -> HOLD_TIMEOUT; wait-time + progress updates via ``notify_user``
  * OTP/PIN digits heard from the callee/user are redacted from the transcript
  * never raises for call-level failures (returns FAILED + ``error``); cancellation via
    ``runner.cancel(task_id)`` ends the call politely with outcome CANCELLED

CallTurn text conventions for the policy (CallTurn has no audio_class field yet - see
docs/CORE_CHANGES.md): non-human CALLEE chunks are prefixed ``[ivr_prompt]``,
``[queue_announcement]``, ``[hold_music]``, ``[voicemail]``; SYSTEM turns use
``USER ANSWERED: ...``, ``USER DID NOT ANSWER WITHIN 90s``, ``BLOCKED: ...``,
``DTMF: ...``, ``ON HOLD``, ``HUMAN AGENT JOINED AFTER 7m 0s HOLD``,
``USER JOINED THE CALL``, ``USER DID NOT JOIN``, ``USER: ...`` (bridged user speech),
``CALLEE HUNG UP``, ``SILENCE``.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Protocol

from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.container import ComponentNotAvailable, Container
from friday.core.events import CallFinished, CallStarted, CallTurnRecorded, EventBus
from friday.core.interfaces import (
    AskUser,
    CallEnded,
    CallLeg,
    CallPolicy,
    NotifyUser,
    ProviderError,
    TelephonyProvider,
    Translator,
    telephony_capabilities,
)
from friday.core.logging import get_logger, mask_phone, truncate
from friday.core.models import (
    CORE_LANGUAGES,
    AudioClass,
    CallAction,
    CallActionType,
    CallBrief,
    CallDirection,
    CallMode,
    CallOutcome,
    CallResult,
    CareOutcome,
    DialStatus,
    Language,
    MidCallQuestion,
    OutboundCallRequest,
    Speaker,
    TaskType,
    Transcription,
    UserAnswer,
)
from friday.core.safety import KeyBuffer, check_speech
from friday.core.scale import Cache, LockTimeout, RateLimiter
from friday.voice.commit import (
    COMMIT_TYPES,
    commit_reasons,
    is_commit_action,
    slot_of,
)
from friday.voice.events import CallCostReport, CallLanguageSwitched, CallLatencyReport
from friday.voice.latency import LatencyRecorder
from friday.voice.text import mask_digits, redact_secrets, strip_fillers

log = get_logger(__name__)

MAX_MID_CALL_QUESTIONS = 2  # US-5.6
P95_BUDGET_MS = 1500  # founder guardrail: p95 turn latency < 1.5 s
MAX_BLOCKED_IN_A_ROW = 2
RECORDING_WAIT_S = 5.0  # provider recording callbacks usually land within seconds
MAX_SILENCES = 3
HOLD_LISTEN_S = 30.0
USER_JOIN_TIMEOUT_S = 25  # US-26.3
CARE_ACTIVE_MAX_S = 1200  # US-34.6: care calls get 20 min active (+ hold)

_HUMAN_CLAIM = re.compile(
    r"\b(i am|i'm) (a )?(real )?(human|person|real person)\b|main insaan hoon|"
    r"मैं इंसान हूँ|main (ek )?(aadmi|ladki|insaan) hoon",
    re.I,
)
_WAIT_MIN = re.compile(r"(\d+)\s*(?:minutes?|mins?|मिनट)", re.I)
_DROP_OFF = re.compile(r"friday.{0,20}(drop|leave|chale jao|disconnect|you can go)", re.I)
_SECRET_IN_USER = re.compile(r"\b(otp|pin|cvv|password|passcode)\b|ओटीपी|पिन", re.I)

_HOLD_LINES = {
    Language.EN: "Thank you for holding. I'm still waiting for {name}'s reply.",
    Language.HINGLISH: (
        "Hold karne ke liye dhanyavaad. Main abhi {name} ke jawab ka intezaar kar rahi hoon."
    ),
    Language.HI: "होल्ड करने के लिए धन्यवाद। मैं अभी {name} के जवाब का इंतज़ार कर रही हूँ।",
}
_INBOUND_GREETING = {
    Language.EN: "Hi, this is Friday, an AI assistant. We called you earlier on behalf of {name}.",
    Language.HINGLISH: (
        "Hi, main Friday hoon, ek AI assistant. Humne aapko pehle {name} ki taraf se call kiya tha."
    ),
    Language.HI: "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट। हमने आपको पहले {name} की ओर से कॉल किया था।",
}
_NEW_NUMBER = {
    Language.EN: "Friday here, calling from a new number.",
    Language.HINGLISH: "Friday bol rahi hoon, ab main is naye number se call karti hoon.",
    Language.HI: "मैं Friday बोल रही हूँ, अब मैं इस नए नंबर से कॉल करती हूँ।",
}
_SAFE_EXIT = {
    Language.EN: "I'll check with {name} and call you back. Thank you.",
    Language.HINGLISH: "Main {name} se confirm karke aapko call back karti hoon. Dhanyavaad.",
    Language.HI: "मैं {name} से पूछकर आपको वापस कॉल करती हूँ। धन्यवाद।",
}
_CANCEL_LINE = {
    Language.EN: "Sorry, I need to end this call now. Thank you for your time.",
    Language.HINGLISH: (
        "Sorry, mujhe abhi yeh call khatam karni hogi. Aapke time ke liye dhanyavaad."
    ),
    Language.HI: "माफ़ कीजिए, मुझे अभी यह कॉल खत्म करनी होगी। आपके समय के लिए धन्यवाद।",
}
_TRANSLATOR_INTRO = {
    Language.EN: "I'm Friday, an AI assistant translating for {name}.",
    Language.HINGLISH: "Main Friday hoon, ek AI assistant, {name} ke liye translate kar rahi hoon.",
    Language.HI: "मैं Friday हूँ, एक AI असिस्टेंट, {name} के लिए अनुवाद कर रही हूँ।",
}
_TRANSLATOR_SECRET_WARNING = {
    Language.EN: "I can't pass on OTPs, PINs or passwords. Please don't share them on this call.",
    Language.HINGLISH: (
        "Main OTP, PIN ya password aage nahi bata sakti. Please inhe call pe share mat kijiye."
    ),
}


def _line(table: dict[Language, str], language: Language, **kw: Any) -> tuple[str, Language]:
    lang = (
        language
        if language in table
        else (Language.HINGLISH if Language.HINGLISH in table else Language.EN)
    )
    return table[lang].format(**kw), lang


class VoiceCallResult(CallResult):
    """CallResult + the per-turn latency summary (not part of the core model)."""

    latency: dict[str, float] = {}


class RecordingStore(Protocol):
    """What the runner needs from Backend A's object store (``friday.db.objectstore``)."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> str: ...


_DIAL_OUTCOME = {
    DialStatus.BUSY: CallOutcome.BUSY,
    DialStatus.NO_ANSWER: CallOutcome.NO_ANSWER,
    DialStatus.VOICEMAIL: CallOutcome.VOICEMAIL,
    DialStatus.FAILED: CallOutcome.FAILED,
}

# Internal cost estimate (INR, never shown to users).
COST_TELEPHONY_PER_MIN = 0.8
COST_STT_PER_MIN = 0.5
COST_TTS_PER_1K_CHARS = 2.0
COST_POLICY_CALL = 0.12
COST_TRANSLATE_CALL = 0.06


class CallRunner:
    """``friday.core.interfaces.CallSessionRunner`` implementation."""

    def __init__(
        self,
        c: Container | None = None,
        *,
        telephony: TelephonyProvider | None = None,
        policy: CallPolicy | None = None,
        translator: Translator | None = None,
        settings: Settings | None = None,
        clock: Clock | None = None,
        bus: EventBus | None = None,
        tts_languages: frozenset[Language] | None = None,
        rate_limiter: RateLimiter | None = None,
        cache: Cache | None = None,
        recording_store: RecordingStore | None = None,
    ) -> None:
        self._c = c
        self._telephony = telephony
        self._policy = policy
        self._translator = translator
        self.settings = settings or (c.settings if c else Settings())
        self.clock = clock or (c.clock if c else None)
        if self.clock is None:
            from friday.core.clock import SystemClock

            self.clock = SystemClock()
        self.bus = bus or (c.bus if c else EventBus())
        self._tts_languages = tts_languages
        self._cancelled: set[str] = set()
        self.rate_limiter = rate_limiter
        self.cache = cache
        self.recording_store = recording_store
        self.draining = False
        self.slot_timeout_s = 10.0  # wait for a provider concurrency slot, then FAILED
        self.active: dict[str, asyncio.Task | None] = {}  # call_id -> task (live calls)
        self._sessions: dict[str, _Session] = {}
        self._idle = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------------ dependencies
    @property
    def telephony(self) -> TelephonyProvider:
        if self._telephony is None:
            assert self._c is not None, "CallRunner needs a container or telephony="
            self._telephony = self._c.telephony
        return self._telephony

    @property
    def policy(self) -> CallPolicy:
        if self._policy is None:
            if self._c is None:
                raise ComponentNotAvailable("no CallPolicy configured")
            self._policy = self._c.brain
        return self._policy

    @property
    def translator(self) -> Translator:
        if self._translator is None:
            if self._c is None:
                raise ComponentNotAvailable("no Translator configured")
            self._translator = self._c.brain
        return self._translator

    @property
    def tts_languages(self) -> frozenset[Language] | None:
        if self._tts_languages is None and self._c is not None:
            try:
                self._tts_languages = frozenset(self._c.tts.supported_languages)
            except Exception:  # noqa: BLE001 - TTS optional (simulator legs need none)
                self._tts_languages = frozenset(Language)
        return self._tts_languages

    # ------------------------------------------------------------------ API
    def cancel(self, task_id: str) -> None:
        """Ask the in-flight call for ``task_id`` to wrap up politely (FIRST_MATCH
        sibling found, user cancelled). ``run`` then returns outcome CANCELLED."""
        self._cancelled.add(task_id)

    @property
    def live_calls(self) -> int:
        return len(self.active)

    def _enter(self, call_id: str) -> None:
        self.active[call_id] = asyncio.current_task()
        self._idle.clear()

    def _leave(self, call_id: str) -> None:
        self.active.pop(call_id, None)
        if not self.active:
            self._idle.set()

    async def drain(self, timeout_s: float | None = None) -> bool:
        """Graceful shutdown (S-9): refuse new calls, let live calls finish. Returns True
        when idle; after ``timeout_s`` live calls are asked to wrap up (cancel) and the
        runner waits for them to end."""
        self.draining = True
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=timeout_s)
            return True
        except TimeoutError:
            for call_id, _task in list(self.active.items()):
                log.warning("drain timeout: ending live call %s", call_id)
            for sess in list(self._sessions.values()):
                self.cancel(sess.brief.task_id)
            await self._idle.wait()
            return False

    async def run(
        self,
        brief: CallBrief,
        ask_user: AskUser,
        notify_user: NotifyUser | None = None,
        *,
        from_number: str | None = None,
        inbound_leg: CallLeg | None = None,
        context: str | None = None,
    ) -> CallResult:
        if inbound_leg is not None:
            return await self.run_inbound(
                brief, inbound_leg, ask_user, notify_user, context=context
            )
        session = _Session(
            self,
            brief,
            ask_user,
            notify_user,
            from_number=from_number,
        )
        return await session.execute()

    async def run_inbound(
        self,
        leg_or_brief: CallLeg | CallBrief,
        brief_or_leg: CallBrief | CallLeg,
        ask_user: AskUser,
        notify_user: NotifyUser | None = None,
        *,
        context: str | None = None,
    ) -> CallResult:
        """A business called a Friday number (E31) and the leg is already answered.

        Accepts ``run_inbound(leg, brief, ...)`` (Backend B's call order) or
        ``run_inbound(brief, leg, ...)``. Friday speaks the inbound disclosure +
        ``context`` first, then the policy continues with the same brief (approval rule
        unchanged)."""
        if isinstance(leg_or_brief, CallBrief):
            brief, leg = leg_or_brief, brief_or_leg
        else:
            leg, brief = leg_or_brief, brief_or_leg
        assert isinstance(brief, CallBrief)
        session = _Session(
            self,
            brief,
            ask_user,
            notify_user,
            inbound_leg=leg,  # type: ignore[arg-type]
            context=context,
        )
        return await session.execute()


class _Session:
    def __init__(
        self,
        runner: CallRunner,
        brief: CallBrief,
        ask_user: AskUser,
        notify_user: NotifyUser | None,
        *,
        from_number: str | None = None,
        inbound_leg: CallLeg | None = None,
        context: str | None = None,
    ) -> None:
        self.r = runner
        self.brief = brief
        self.ask_user = ask_user
        self.notify_user = notify_user
        self.clock = runner.clock
        self.settings = runner.settings
        self.inbound = inbound_leg is not None
        self.leg: CallLeg | None = inbound_leg
        self.context = context
        self.from_number = from_number or brief.from_number
        self.keybuf = KeyBuffer(brief)  # SECURITY-24: keys since the last IVR prompt
        self.committed = False  # SECURITY-4: a gated commit was actually spoken
        self.human_reached = False
        self.pressed: list[str] = []  # menu keys (for learned IVR maps)
        self.block_signal: str | None = None
        self.bridge_refused = False
        self.result = VoiceCallResult(
            task_id=brief.task_id,
            provider=getattr(inbound_leg, "provider", None) or "unknown",
            to_phone=brief.target.phone,
            dial_status=DialStatus.FAILED,
            outcome=CallOutcome.FAILED,
            started_at=self.clock.now(),
            direction=CallDirection.INBOUND if self.inbound else CallDirection.OUTBOUND,
        )
        self.transcript = self.result.transcript
        self.answers: list[UserAnswer] = self.result.answers
        self.disclosed_current = False
        self.disclosures = 0
        self.after_machine = False  # last thing heard was IVR/hold -> next human is new
        self.last_callee_lang: Language | None = None
        self.silences = 0
        self.blocked_streak = 0
        self.hold_s = 0.0
        self.left = False
        self.hung_up = False
        self.last_action: CallAction | None = None
        self.latency = LatencyRecorder()
        self.tts_chars = 0
        self.translations = 0
        self.voicemail_detected = False
        self._stack: AsyncExitStack | None = None
        self._cached_ivr: list[str] = []
        self._prerender: asyncio.Future | None = None
        self._extra_legs: list[CallLeg] = []
        self.care: CareOutcome | None = None
        if brief.task_type == TaskType.CUSTOMER_CARE or brief.company:
            self.care = CareOutcome(company=brief.company, request_kind=brief.care_request)

    # ================================================================== lifecycle
    @property
    def name(self) -> str:
        return self.brief.on_behalf_of

    @property
    def cancelled(self) -> bool:
        return self.brief.task_id in self.r._cancelled

    async def execute(self) -> CallResult:
        r = self.r
        if r.draining:
            self.result.error = "voice worker is draining"
            self.result.outcome = CallOutcome.FAILED
            self.result.ended_at = self.clock.now()
            return self.result
        r._enter(self.result.call_id)
        r._sessions[self.result.call_id] = self
        try:
            async with AsyncExitStack() as stack:
                self._stack = stack
                return await self._execute_inner()
        finally:
            r._sessions.pop(self.result.call_id, None)
            r._leave(self.result.call_id)

    async def _execute_inner(self) -> CallResult:
        try:
            self.result.outcome = self._check_outcome(await self._run())
        except asyncio.CancelledError:
            self.result.outcome = CallOutcome.CANCELLED
            self.result.error = "task cancelled"
            await asyncio.shield(self._finish())
            raise
        except CallEnded:
            self.result.outcome = CallOutcome.HUNG_UP
        except Exception as e:  # noqa: BLE001 - runner never raises on call failure
            log.exception("call %s failed", self.result.call_id)
            self.result.outcome = CallOutcome.FAILED
            self.result.error = truncate(f"{type(e).__name__}: {e}", 300)
        await self._finish()
        return self.result

    def _check_outcome(self, outcome: CallOutcome) -> CallOutcome:
        """SECURITY-4: the outcome comes from what actually happened on the call. A
        SUCCESS on a task that commits money/slots needs a gated commit turn; the model's
        claim alone is never enough."""
        if (
            outcome == CallOutcome.SUCCESS
            and self.brief.task_type in COMMIT_TYPES
            and self.brief.mode != CallMode.TRANSLATOR  # translating commits nothing
            and not self.committed
        ):
            self.transcript.add(
                Speaker.SYSTEM, "OUTCOME DOWNGRADED: no gated commit", at=self.clock.now()
            )
            has_offer = bool(self.result.quotes or self.result.collected)
            return CallOutcome.PENDING_APPROVAL if has_offer else CallOutcome.PARTIAL
        return outcome

    async def _finish(self) -> None:
        r = self.result
        if self.leg is not None and not self.hung_up and not self.left:
            await self._safe_hangup()
        r.ended_at = self.clock.now()
        r.hold_seconds = int(round(self.hold_s))
        if self.care is not None:
            self.care.hold_seconds = r.hold_seconds
            r.care = self.care
        r.collected = dict(r.collected)
        if self.committed:
            r.collected["committed"] = "true"  # engine: COMPLETED needs this (SECURITY-4)
            slot = slot_of(self.last_action) if self.last_action is not None else None
            if slot is not None:  # BUG-1: lets the engine re-verify a delegation WINDOW
                r.collected["slot_at"] = slot.isoformat()
        else:
            r.collected.pop("committed", None)
        if self.block_signal:
            r.collected["provider_signal"] = self.block_signal
        if self.bridge_refused:
            r.collected["bridge_unavailable"] = "1"  # engine/brain: send the call-back pack
        if self.leg is not None:
            await self._store_recording()
        await self._learn_ivr_map()
        summary = self.latency.summary()
        r.latency = summary
        self._collect_costs()
        r.cost_inr_est = round(self._cost(), 2)
        if self._prerender is not None and not self._prerender.done():
            self._prerender.cancel()
        r.answers = self.answers
        if summary["p95_ms"] > P95_BUDGET_MS:
            log.warning(
                "call %s p95 turn latency %.0fms over the %dms budget",
                r.call_id,
                summary["p95_ms"],
                P95_BUDGET_MS,
            )
        if summary["turns"]:
            log.info(
                "call %s latency p50=%.0fms p95=%.0fms over %d turns",
                r.call_id,
                summary["p50_ms"],
                summary["p95_ms"],
                int(summary["turns"]),
            )
            await self.r.bus.publish(
                CallLatencyReport(
                    task_id=r.task_id,
                    call_id=r.call_id,
                    turns=int(summary["turns"]),
                    p50_ms=summary["p50_ms"],
                    p95_ms=summary["p95_ms"],
                    max_ms=summary["max_ms"],
                    policy_p95_ms=summary["policy_p95_ms"],
                    stt_p95_ms=summary["stt_p95_ms"],
                    tts_p95_ms=summary["tts_p95_ms"],
                )
            )
        self.r._cancelled.discard(self.brief.task_id)
        log.info("call %s to %s finished: %s", r.call_id, mask_phone(r.to_phone), r.outcome.value)
        await self.r.bus.publish(
            CallCostReport(
                task_id=r.task_id,
                call_id=r.call_id,
                provider=r.provider,
                telephony_seconds=r.telephony_seconds,
                hold_seconds=r.hold_seconds,
                stt_seconds=r.stt_seconds,
                tts_chars=r.tts_chars,
                tts_billed_chars=r.tts_billed_chars,
                policy_calls=r.policy_calls,
                translate_calls=r.translate_calls,
                cost_inr_est=r.cost_inr_est,
            )
        )
        await self.r.bus.publish(
            CallFinished(task_id=r.task_id, call_id=r.call_id, outcome=r.outcome)
        )

    async def _store_recording(self) -> None:
        """S-6: move the provider recording into the object store (India region, private,
        lifecycle = retention) and persist ONLY the store URL; never keep a local file in
        live. Without a store (simulator / dev) the leg's own URL is kept."""
        r = self.result
        assert self.leg is not None
        url: str | None = None
        try:
            wait = getattr(self.leg, "wait_recording", None)
            if wait is not None:
                await wait(RECORDING_WAIT_S)
            url = await self.leg.recording_url()
        except Exception:  # noqa: BLE001
            log.warning("recording unavailable for %s", r.call_id)
        store = self.r.recording_store
        if not url or store is None:
            r.recording_url = url
            return
        owns = getattr(store, "owns", None)
        if callable(owns) and owns(url):
            r.recording_url = url
            return
        fetch = getattr(self.leg, "fetch_recording", None)
        data: bytes | None = None
        try:
            if url.startswith("file://"):
                from pathlib import Path
                from urllib.parse import unquote, urlparse

                data = await asyncio.to_thread(Path(unquote(urlparse(url).path)).read_bytes)
            elif fetch is not None:
                data = await fetch(url)
        except Exception as e:  # noqa: BLE001
            log.warning("could not fetch recording for %s: %s", r.call_id, type(e).__name__)
        if not data:
            r.recording_url = None if url.startswith("file://") else url
            return
        ext = ".txt" if url.startswith("file://") else (".mp3" if url.endswith(".mp3") else ".wav")
        ctype = "text/plain" if ext == ".txt" else ("audio/mpeg" if ext == ".mp3" else "audio/wav")
        try:
            r.recording_url = await store.put(
                f"{r.task_id}/{r.call_id}{ext}", data, content_type=ctype
            )
        except Exception as e:  # noqa: BLE001 - keep the provider URL; retention still applies
            log.warning("recording upload failed for %s: %s", r.call_id, type(e).__name__)
            r.recording_url = None if url.startswith("file://") else url

    async def _learn_ivr_map(self) -> None:
        """S-10: remember the key path that reached a human, per company number, in the
        shared Cache (non-personal: menu keys only; identifiers become ``{label}``)."""
        cache = self.r.cache
        if cache is None or self.inbound or self.care is None:
            return
        if not (self.human_reached and self.pressed) or self.brief.ivr_map or self._cached_ivr:
            return
        steps: list[str] = []
        for keys in self.pressed:
            if "{" in keys or len(re.sub(r"\D", "", keys)) <= 2:
                steps.append(keys)
                continue
            label = next(
                (
                    f"{{{i.label}}}"
                    for i in self.brief.approved_identifiers
                    if re.sub(r"\D", "", i.value) and re.sub(r"\D", "", i.value) in keys
                ),
                None,
            )
            if label is None:
                return  # unknown long entry: never store raw digits
            steps.append(label + ("#" if keys.endswith("#") else ""))
        await cache.set(_ivr_key(self.brief.target.phone), steps, ttl_s=30 * 86400)

    def _collect_costs(self) -> None:
        r = self.result
        if r.answered_at:
            r.telephony_seconds = round(
                max(0.0, (self.clock.now() - r.answered_at).total_seconds()), 1
            )
        legs = [self.leg, *self._extra_legs] if self.leg is not None else list(self._extra_legs)
        r.stt_seconds = round(sum(float(getattr(x, "stt_seconds", 0.0) or 0.0) for x in legs), 1)
        billed = [getattr(x, "tts_billed_chars", None) for x in legs]
        r.tts_billed_chars = (
            sum(b for b in billed if b) if any(b is not None for b in billed) else 0
        )
        r.tts_chars = self.tts_chars
        r.translate_calls = self.translations

    def _cost(self) -> float:
        r = self.result
        if not r.answered_at:
            return 0.1 if r.provider != "simulator" else 0.0
        minutes = max(0.0, (self.clock.now() - r.answered_at).total_seconds()) / 60
        active_min = max(0.0, minutes - self.hold_s / 60)
        return (
            minutes * COST_TELEPHONY_PER_MIN
            + active_min * COST_STT_PER_MIN
            + (self.result.tts_billed_chars or 0) / 1000 * COST_TTS_PER_1K_CHARS
            + r.policy_calls * COST_POLICY_CALL
            + self.translations * COST_TRANSLATE_CALL
        )

    async def _safe_hangup(self) -> None:
        if self.leg is None or self.hung_up:
            return
        self.hung_up = True
        try:
            await self.leg.hangup()
        except Exception:  # noqa: BLE001
            log.debug("hangup failed (already ended?)")

    # ================================================================== main
    async def _run(self) -> CallOutcome:
        if self.inbound:
            return await self._run_inbound()
        b = self.brief
        meta = {"call_id": self.result.call_id}
        needs = self._needs()
        if needs:
            meta["needs"] = ",".join(sorted(needs))
        if self.from_number:
            meta["from_number"] = self.from_number
        missing = self._missing_capabilities()
        if missing:
            return self._decline_unsupported(missing)
        if not await self._reserve_capacity("telephony"):
            self.result.error = "telephony rate-limited; retry later"
            self.result.dial_status = DialStatus.FAILED
            return CallOutcome.FAILED
        req = OutboundCallRequest(
            to_phone=b.target.phone,
            task_id=b.task_id,
            record=self.settings.call_record,
            ring_timeout_s=self.settings.call_ring_timeout_s,
            max_duration_s=b.max_duration_s,
            language=b.opening_language,
            metadata=meta,
            from_number=self.from_number,
        )
        tel = self.r.telephony
        self.result.provider = getattr(tel, "name", "unknown")
        try:
            self.leg = await tel.place_call(req)
        except ProviderError as e:
            self.result.error = truncate(str(e), 300)
            self.result.dial_status = DialStatus.FAILED
            return CallOutcome.FAILED
        self.result.provider = getattr(self.leg, "provider", None) or self.result.provider
        self.result.provider_call_id = self.leg.provider_call_id
        self.result.from_number = getattr(self.leg, "from_number", None) or self.from_number
        if not await self._reserve_capacity(self.result.provider):
            self.result.error = f"{self.result.provider} concurrency limit; retry later"
            self.result.dial_status = DialStatus.FAILED
            await self._safe_hangup()
            return CallOutcome.FAILED
        await self.r.bus.publish(
            CallStarted(
                task_id=b.task_id,
                call_id=self.result.call_id,
                to_phone=b.target.phone,
                provider=self.result.provider,
            )
        )
        self._start_prerender()
        status = await self.leg.wait_for_answer(req.ring_timeout_s)
        self.result.dial_status = status
        if status != DialStatus.ANSWERED:
            self.hung_up = True  # nothing to hang up
            signal = getattr(self.leg, "block_signal", None)
            if signal in ("blocked", "rejected"):  # NP-4: feeds the number's health
                self.block_signal = signal
                self.result.dial_status = DialStatus.FAILED
                self.result.error = f"call {signal} by the carrier/provider"
                return CallOutcome.FAILED
            return _DIAL_OUTCOME.get(status, CallOutcome.FAILED)
        self.result.answered_at = self.clock.now()
        try:
            if b.mode == CallMode.TRANSLATOR:
                return await self._translator_loop()
            if not self.brief.ivr_map and self.r.cache is not None:
                cached = await self.r.cache.get(_ivr_key(b.target.phone))
                if isinstance(cached, list):
                    self._cached_ivr = [str(x) for x in cached]
            first = await self._hear()
            if first is not None and first.audio_class == AudioClass.IVR_PROMPT:
                outcome = await self._replay_ivr(first)
                if outcome is not None:
                    return outcome
            return await self._loop()
        except CallEnded:
            return await self._callee_hung_up()

    # ------------------------------------------------------------------ learned IVR maps
    def _ivr_steps(self) -> list[tuple[str, str | None]]:
        """Learned menu path for this company number (cost rule 4).

        Source: ``CallBrief.ivr_map``, else the shared Cache entry learned from earlier
        calls to this number (S-10), else an ``ivr_notes`` entry
        ``"replay: 2 | 3@broadband | {Registered mobile}# | 9"``.
        A step is DTMF keys, optionally ``@keyword`` the current prompt must contain;
        ``{label or id}`` is replaced by that APPROVED identifier's value."""
        raw: list[str] = list(self.brief.ivr_map or self._cached_ivr or [])
        if not raw:
            for note in self.brief.ivr_notes:
                if note.lower().startswith("replay:"):
                    raw = [x.strip() for x in note.split(":", 1)[1].split("|") if x.strip()]
                    break
        steps: list[tuple[str, str | None]] = []
        for item in raw:
            keys, _, expect = item.partition("@")
            steps.append((keys.strip(), expect.strip() or None))
        return steps

    def _resolve_keys(self, keys: str) -> str | None:
        def sub(m: re.Match) -> str:
            ref = m.group(1).strip().lower()
            for ident in self.brief.approved_identifiers:
                if ref in (ident.id.lower(), ident.label.lower()):
                    return re.sub(r"\D", "", ident.value)
            raise KeyError(ref)

        try:
            return re.sub(r"\{([^}]+)\}", sub, keys)
        except KeyError:
            return None

    async def _replay_ivr(self, prompt: Transcription) -> CallOutcome | None:
        """Navigate a known IVR without any policy call; hand back to the policy on surprise."""
        steps = self._ivr_steps()
        if not steps or self.leg is None:
            return None
        heard: Transcription | None = prompt
        for keys, expect in steps:
            if heard is None or heard.audio_class != AudioClass.IVR_PROMPT:
                break
            if expect and expect.lower() not in (heard.text or "").lower():
                await self._system(f"IVR REPLAY STOPPED: menu changed (expected '{expect}')")
                return None
            digits = self._resolve_keys(keys)
            if digits is None or not self.keybuf.check(digits).allowed:
                await self._system("IVR REPLAY STOPPED: step needs an unapproved identifier")
                return None
            await self.leg.send_dtmf(digits)
            self.pressed.append(keys)  # the template step, never the identifier digits
            masked = mask_digits(digits)
            await self._system(f"DTMF: {masked} (learned IVR map)")
            if self.care is not None:
                self.care.ivr_path.append(masked)
            self.result.ivr_keys_replayed += 1
            heard = await self._hear()
            if heard is not None and "invalid" in (heard.text or "").lower():
                await self._system("IVR REPLAY STOPPED: invalid option")
                return None
        if heard is not None and heard.audio_class in (
            AudioClass.HOLD_MUSIC,
            AudioClass.QUEUE_ANNOUNCEMENT,
        ):
            return await self._hold(CallAction(type=CallActionType.WAIT_ON_HOLD))
        return None

    def _fixed_lines(self) -> dict[Language, list[str]]:
        """Lines the runner itself may speak on this call (pre-rendered while ringing)."""
        b = self.brief
        lang = b.opening_language
        lines = {lang: [b.disclosure(lang)]}
        if b.number_changed:
            text, nl = _line(_NEW_NUMBER, lang)
            lines.setdefault(nl, []).append(text)
        for table in (_HOLD_LINES, _SAFE_EXIT, _CANCEL_LINE):
            text, tl = _line(table, lang, name=self.name)
            lines.setdefault(tl, []).append(text)
        if self.care is not None and lang != Language.EN:  # agents after IVR often speak English
            lines.setdefault(Language.EN, []).append(b.disclosure(Language.EN))
        extra = getattr(self.r._policy, "fixed_lines", None)  # a scripted policy's own fixed lines
        if extra is not None:
            try:
                for plang, texts in extra(b).items():
                    lines.setdefault(plang, []).extend(texts)
            except Exception:  # noqa: BLE001 - pre-rendering is best effort
                log.warning("policy fixed_lines failed on call %s", self.result.call_id)
        return lines

    def _start_prerender(self) -> None:
        tts = getattr(getattr(self.leg, "tel", None), "tts", None)
        prerender = getattr(tts, "prerender", None)
        if prerender is None:
            return

        async def warm() -> None:
            for lang, texts in self._fixed_lines().items():
                await prerender(texts, lang)

        self._prerender = asyncio.ensure_future(warm())

    def _caps(self) -> frozenset[str]:
        return telephony_capabilities(self.r.telephony)

    def _can_bridge(self) -> bool:
        return bool(self._caps() & {"bridge_transfer", "bridge_conference"})

    def _missing_capabilities(self) -> list[str]:
        """Hard requirements the active provider cannot meet (no fallback provider)."""
        b = self.brief
        caps = self._caps()
        missing: list[str] = []
        if (self.care is not None or b.ivr_notes or b.ivr_map) and "dtmf" not in caps:
            missing.append("dtmf")
        if b.mode == CallMode.TRANSLATOR and "media_stream" not in caps:
            missing.append("media_stream")
        if b.mode == CallMode.WARM_TRANSFER and not self._can_bridge():
            missing.append("bridge")
        return missing

    def _decline_unsupported(self, missing: list[str]) -> CallOutcome:
        """Honest decline BEFORE dialling: NEEDS_USER_VERIFICATION is final (not retried);
        the engine reports it and the user does it themselves with the context we have."""
        self.hung_up = True
        self.result.error = (
            "the telephony provider cannot do this on a call yet (" + ", ".join(missing) + ")"
        )
        self.result.collected["unsupported_capability"] = ",".join(missing)
        log.warning("declining call %s: provider lacks %s", self.result.call_id, missing)
        return CallOutcome.NEEDS_USER_VERIFICATION

    async def _reserve_capacity(self, key: str) -> bool:
        """Provider limiters (S-9): token for dialling + a concurrency slot held for the
        whole call. False = rate-limited / no slot -> FAILED (retryable), never raises."""
        lim = self.r.rate_limiter
        if lim is None or self._stack is None:
            return True
        try:
            if key == "telephony" and not await lim.acquire("telephony", timeout_s=5.0):
                return False
            await self._stack.enter_async_context(lim.slot(key, timeout_s=self.r.slot_timeout_s))
        except (LockTimeout, TimeoutError):
            return False
        return True

    def _needs(self) -> set[str]:
        """Capabilities this call needs (RoutedTelephony falls back per call)."""
        b = self.brief
        needs: set[str] = set()
        if self.care is not None or b.ivr_notes:
            needs.add("dtmf")
        if b.mode == CallMode.WARM_TRANSFER or (self.care is not None and b.user_phone):
            needs.add("bridge")
        if b.mode == CallMode.TRANSLATOR:
            needs.add("media_stream")
        return needs

    async def _run_inbound(self) -> CallOutcome:
        b = self.brief
        assert self.leg is not None
        self.result.provider = getattr(self.leg, "provider", "unknown")
        self.result.provider_call_id = self.leg.provider_call_id
        self.result.from_number = getattr(self.leg, "from_number", None)
        self.result.dial_status = DialStatus.ANSWERED
        self.result.answered_at = self.clock.now()
        await self.r.bus.publish(
            CallStarted(
                task_id=b.task_id,
                call_id=self.result.call_id,
                to_phone=b.target.phone,
                provider=self.result.provider,
            )
        )
        try:
            greeting, lang = _line(_INBOUND_GREETING, b.opening_language, name=self.name)
            if self.context:
                extra = strip_fillers(self.context)
                if check_speech(extra, b).allowed:
                    greeting = f"{greeting} {extra}"
                else:
                    await self._system("BLOCKED: inbound context contained an unapproved number")
            await self._say(greeting, lang, disclosure=True)
            self.disclosed_current = True
            await self._hear()
            return await self._loop()
        except CallEnded:
            return await self._callee_hung_up()

    async def _loop(self) -> CallOutcome:
        while True:
            if self.cancelled:
                return await self._end_with(_CANCEL_LINE, CallOutcome.CANCELLED)
            if self.voicemail_detected:
                await self._system("VOICEMAIL DETECTED - not leaving a message")
                await self._safe_hangup()
                return CallOutcome.VOICEMAIL
            if self.silences >= MAX_SILENCES:
                await self._system("LINE SILENT - ending call")
                await self._safe_hangup()
                return CallOutcome.HUNG_UP
            if self._active_s() > self._max_active_s():
                await self._system("MAX CALL DURATION REACHED")
                outcome = (
                    CallOutcome.PARTIAL
                    if (self.result.quotes or self.result.collected)
                    else CallOutcome.FAILED
                )
                if outcome == CallOutcome.FAILED:
                    self.result.error = "max call duration reached"
                return await self._end_with(_SAFE_EXIT, outcome)
            action = await self._decide()
            if action is None:
                self.result.error = self.result.error or "call policy failed"
                return await self._end_with(_SAFE_EXIT, CallOutcome.FAILED)
            outcome = await self._execute(action)
            if outcome is not None:
                return outcome

    def _active_s(self) -> float:
        if not self.result.answered_at:
            return 0.0
        return (self.clock.now() - self.result.answered_at).total_seconds() - self.hold_s

    def _max_active_s(self) -> float:
        if self.care is not None:
            return max(self.brief.max_duration_s, CARE_ACTIVE_MAX_S)
        return self.brief.max_duration_s

    async def _end_with(self, table: dict[Language, str], outcome: CallOutcome) -> CallOutcome:
        text, lang = _line(table, self._lang(), name=self.name)
        with contextlib.suppress(CallEnded):
            await self._say(text, lang)
        await self._safe_hangup()
        return outcome

    async def _callee_hung_up(self) -> CallOutcome:
        self.hung_up = True
        await self._system("CALLEE HUNG UP")
        if self.left:
            return CallOutcome.TRANSFERRED
        try:  # let the policy classify (e.g. "call after 5" then hung up)
            action = await self._decide(record_latency=False)
        except Exception:  # noqa: BLE001
            action = None
        if action is not None:
            self._absorb(action)
            if (
                action.type == CallActionType.HANGUP
                and action.outcome
                and action.outcome != CallOutcome.TRANSFERRED
            ):
                return action.outcome
        return CallOutcome.HUNG_UP

    # ================================================================== policy
    async def _decide(self, *, record_latency: bool = True) -> CallAction | None:
        for attempt in range(2):
            t0 = time.perf_counter()
            try:
                action = await self.r.policy.next_call_action(
                    self.brief, self.transcript, list(self.answers)
                )
            except ComponentNotAvailable as e:
                self.result.error = f"no call policy: {e}"
                return None
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "policy error on call %s (attempt %d): %r", self.result.call_id, attempt + 1, e
                )
                self.result.error = truncate(f"policy error: {type(e).__name__}: {e}", 300)
                continue
            finally:
                self.result.policy_calls += 1
            if record_latency:
                self.latency.policy((time.perf_counter() - t0) * 1000)
            self.result.error = None
            return action
        return None

    def _absorb(self, action: CallAction) -> None:
        if action.collected:
            self.result.collected.update(action.collected)
        if action.quote is not None:
            q = action.quote.model_copy(
                update={"call_id": self.result.call_id, "task_id": self.brief.task_id}
            )
            self.result.quotes = [
                x for x in self.result.quotes if x.business_name != q.business_name
            ] + [q]
        if action.care is not None:
            path = self.care.ivr_path if self.care else []
            self.care = action.care.model_copy(update={"ivr_path": action.care.ivr_path or path})

    def _guard(self, action: CallAction) -> list[str]:
        b = self.brief
        reasons: list[str] = []
        t = action.type
        if (
            t
            in (
                CallActionType.SAY,
                CallActionType.HANGUP,
                CallActionType.ASK_USER,
                CallActionType.BRIDGE_USER,
            )
            and action.text
        ):
            reasons += check_speech(action.text, b).reasons
            if _HUMAN_CLAIM.search(action.text):
                reasons.append("Friday must never claim to be human")
        if t == CallActionType.SAY and not (action.text or "").strip():
            reasons.append("SAY without text")
        if t == CallActionType.PRESS_KEYS:
            if not action.digits:
                reasons.append("PRESS_KEYS without digits")
            else:
                # SECURITY-24: the concatenation of keys since the last IVR prompt
                reasons += self.keybuf.check(action.digits).reasons
        # SECURITY-3/27: ANY utterance that sounds like a confirmation is a commitment,
        # flagged by the model or not, and must pass check_commit (approval / delegation
        # price + slot window + scope).
        gated = action.commits_booking or b.task_type in COMMIT_TYPES
        if t in (CallActionType.SAY, CallActionType.HANGUP) and is_commit_action(action) and gated:
            why = commit_reasons(b, list(self.answers), action)
            if why:
                reasons.append(
                    "commitment not allowed on this call ("
                    + "; ".join(why)
                    + ") - tell the business you'll call back after checking with the user"
                )
        if t == CallActionType.ASK_USER:
            if action.question is None:
                reasons.append("ASK_USER without a question")
            elif len(self.result.questions) >= MAX_MID_CALL_QUESTIONS:
                reasons.append(
                    "max 2 mid-call questions reached - wrap up and ask the user after the call"
                )
        if t == CallActionType.BRIDGE_USER and not b.user_phone:
            reasons.append("no user phone to bridge")
        if t == CallActionType.BRIDGE_USER and (not self._can_bridge() or self.bridge_refused):
            self.bridge_refused = True
            reasons.append(
                "this telephony provider cannot connect the user into the call - end with "
                "HANGUP outcome NEEDS_USER_VERIFICATION and say the user will call back "
                "with the context"
            )
        return reasons

    async def _execute(self, action: CallAction) -> CallOutcome | None:
        self._absorb(action)
        reasons = self._guard(action)
        if reasons:
            self.blocked_streak += 1
            await self._system("BLOCKED: " + "; ".join(dict.fromkeys(reasons)))
            log.warning(
                "blocked %s on call %s: %s", action.type.value, self.result.call_id, reasons
            )
            if self.blocked_streak >= MAX_BLOCKED_IN_A_ROW:
                outcome = (
                    CallOutcome.NEEDS_USER_VERIFICATION
                    if (self.care is not None or self.bridge_refused)
                    else CallOutcome.PARTIAL
                )
                return await self._end_with(_SAFE_EXIT, outcome)
            return None
        self.blocked_streak = 0
        self.last_action = action
        t = action.type
        if t == CallActionType.SAY:
            await self._say(action.text or "", action.language)
            if is_commit_action(action):
                self.committed = True
            await self._hear()
        elif t == CallActionType.WAIT:
            await self._hear()
        elif t == CallActionType.HANGUP:
            if action.text:
                with contextlib.suppress(CallEnded):
                    await self._say(action.text, action.language)
                    if is_commit_action(action):
                        self.committed = True
            await self._safe_hangup()
            return action.outcome or CallOutcome.PARTIAL
        elif t == CallActionType.PRESS_KEYS:
            assert self.leg is not None and action.digits
            await self.leg.send_dtmf(action.digits)
            self.pressed.append(action.digits)
            masked = mask_digits(action.digits)
            await self._system(f"DTMF: {masked}")
            if self.care is not None:
                self.care.ivr_path.append(masked)
            await self._hear()
        elif t == CallActionType.ASK_USER:
            await self._ask(action)
        elif t == CallActionType.WAIT_ON_HOLD:
            return await self._hold(action)
        elif t == CallActionType.BRIDGE_USER:
            return await self._bridge(action)
        return None

    # ================================================================== speech
    def _lang(self) -> Language:
        if self.brief.playbook:  # scripted calls never switch language (Hinglish only)
            return Language.HINGLISH
        return self.last_callee_lang or self.brief.opening_language

    def _speak_lang(self, wanted: Language) -> Language:
        supported = self.r.tts_languages
        if not supported or wanted in supported:
            return wanted
        for alt in (
            self.last_callee_lang,
            self.brief.opening_language,
            Language.HINGLISH,
            Language.EN,
        ):
            if alt and alt in supported:
                return alt
        return wanted

    async def _say(
        self,
        text: str,
        language: Language,
        *,
        disclosure: bool = False,
        leg: CallLeg | None = None,
        label: str = "",
    ) -> None:
        clean = strip_fillers(text)
        if not clean:
            return
        lang = self._speak_lang(language)
        target = leg or self.leg
        assert target is not None
        t0 = time.perf_counter()
        await target.speak(clean, lang)
        wall = (time.perf_counter() - t0) * 1000
        self.tts_chars += len(clean)
        if not disclosure:
            self.latency.tts(getattr(target, "last_tts_ms", None) or wall)
        await self._record(Speaker.FRIDAY, f"{label}{clean}", lang)

    async def _disclose(self, human_lang: Language | None) -> None:
        b = self.brief
        lang = b.opening_language
        if self.after_machine and human_lang in CORE_LANGUAGES:
            lang = human_lang  # agent after IVR/hold: their language if we have a template
        await self._say(b.disclosure(lang), lang, disclosure=True)
        self.disclosed_current = True
        self.disclosures += 1
        if b.number_changed and not self.inbound and self.disclosures == 1:
            line, nl = _line(_NEW_NUMBER, lang)  # pre-rendered, no digits
            await self._say(line, nl, disclosure=True)

    async def _hear(self, wait_s: float | None = None) -> Transcription | None:
        assert self.leg is not None
        t = await self.leg.listen(wait_s or self.settings.call_silence_timeout_s)
        self.latency.stt(getattr(self.leg, "last_stt_ms", None))
        if t is None:
            self.silences += 1
            await self._system("SILENCE")
            if not self.disclosed_current and self.disclosures == 0:
                await self._disclose(None)  # picked up and waiting for us to speak
            return None
        self.silences = 0
        if t.audio_class in (AudioClass.HOLD_MUSIC, AudioClass.QUEUE_ANNOUNCEMENT):
            self.hold_s += float(getattr(t, "duration_s", None) or 0.0)
        await self._record_callee(t)
        if t.audio_class == AudioClass.HUMAN and not self.disclosed_current:
            await self._disclose(t.language)
        return t

    async def _record_callee(self, t: Transcription, *, speaker_label: str = "") -> None:
        cls = t.audio_class
        if cls == AudioClass.VOICEMAIL:
            self.voicemail_detected = True
        if cls in (AudioClass.IVR_PROMPT, AudioClass.HOLD_MUSIC, AudioClass.QUEUE_ANNOUNCEMENT):
            self.after_machine = True
            self.disclosed_current = False
        if cls == AudioClass.IVR_PROMPT:
            self.keybuf.reset()  # SECURITY-24: a new prompt starts a new key buffer
        if cls == AudioClass.HUMAN and t.text:
            self.human_reached = True
        text = redact_secrets(t.text or "")
        if (
            cls == AudioClass.HUMAN
            and t.language is not None
            and (t.language != self.last_callee_lang)
        ):
            old = self.last_callee_lang
            self.last_callee_lang = t.language
            if t.language not in self.result.languages_heard:
                self.result.languages_heard.append(t.language)
            if old is not None:
                await self.r.bus.publish(
                    CallLanguageSwitched(
                        task_id=self.brief.task_id,
                        call_id=self.result.call_id,
                        old=old,
                        new=t.language,
                    )
                )
        await self._record(
            Speaker.CALLEE,
            f"{speaker_label}{text}",
            t.language,
            confidence=t.confidence,
            audio_class=cls,
        )

    async def _record(
        self,
        speaker: Speaker,
        text: str,
        language: Language | None,
        confidence: float | None = None,
        audio_class: AudioClass | None = None,
    ) -> None:
        turn = self.transcript.add(
            speaker,
            text,
            at=self.clock.now(),
            language=language,
            confidence=confidence,
            audio_class=audio_class,
        )
        await self.r.bus.publish(
            CallTurnRecorded(task_id=self.brief.task_id, call_id=self.result.call_id, turn=turn)
        )

    async def _system(self, text: str) -> None:
        turn = self.transcript.add(Speaker.SYSTEM, text, at=self.clock.now())
        await self.r.bus.publish(
            CallTurnRecorded(task_id=self.brief.task_id, call_id=self.result.call_id, turn=turn)
        )

    # ================================================================== ASK_USER
    async def _ask(self, action: CallAction) -> None:
        assert action.question is not None
        q: MidCallQuestion = action.question.model_copy(
            update={
                "task_id": self.brief.task_id,
                "call_id": self.result.call_id,
                "asked_at": self.clock.now(),
            }
        )
        if action.text:
            await self._say(action.text, action.language)
        self.result.questions.append(q)
        timeout = q.timeout_s or self.brief.approval.hold_timeout_s
        answer = await self._await_answer(q, timeout, action.language)
        if answer is not None:
            self.answers.append(answer)
            approved = " (APPROVED)" if answer.approves else ""
            await self._system(f"USER ANSWERED: {answer.text}{approved}")
        else:
            await self._system(f"USER DID NOT ANSWER WITHIN {timeout}s")

    async def _await_answer(
        self, q: MidCallQuestion, limit_s: int, lang: Language
    ) -> UserAnswer | None:
        ask_task: asyncio.Task = asyncio.ensure_future(self.ask_user(q))
        interval = max(5, self.settings.call_hold_reminder_interval_s)
        max_lines = max(0, int(limit_s // interval))
        try:
            for _ in range(max_lines):
                tick = asyncio.ensure_future(self.clock.sleep(interval))
                done, _p = await asyncio.wait({ask_task, tick}, return_when=asyncio.FIRST_COMPLETED)
                if ask_task in done:
                    tick.cancel()
                    break
                line, line_lang = _line(
                    _HOLD_LINES,
                    self._lang() if self._lang() in _HOLD_LINES else lang,
                    name=self.name,
                )
                if check_speech(line, self.brief).allowed:
                    await self._say(line, line_lang)
            # backstop in real seconds - ask_user itself resolves None after timeout_s
            return await asyncio.wait_for(asyncio.shield(ask_task), timeout=limit_s + 60)
        except TimeoutError:
            ask_task.cancel()
            return None
        except CallEnded:
            ask_task.cancel()
            raise
        except Exception as e:  # noqa: BLE001 - engine failure == no answer
            log.warning("ask_user failed on call %s: %r", self.result.call_id, e)
            return None

    # ================================================================== hold
    async def _hold(self, action: CallAction) -> CallOutcome | None:
        setter = getattr(self.leg, "set_hold_mode", None)
        if setter:
            setter(True)  # local classifier only; no STT on hold music
        try:
            return await self._hold_loop(action)
        finally:
            if setter:
                setter(False)

    async def _hold_loop(self, action: CallAction) -> CallOutcome | None:
        assert self.leg is not None
        max_hold = action.max_hold_s or self.brief.max_hold_s
        target = self.brief.target.name
        self.disclosed_current = False
        self.after_machine = True
        await self._system("ON HOLD (listening mode, no LLM)")
        if action.user_update:
            await self._notify(action.user_update)
        waited = 0.0
        next_update = float(self.settings.hold_user_update_interval_s)
        announced = bool(action.user_update)
        last_queue_text = ""
        while True:
            if self.cancelled:
                self.hold_s += waited
                return await self._end_with(_CANCEL_LINE, CallOutcome.CANCELLED)
            t0 = self.clock.now()
            try:
                chunk = await self.leg.listen(HOLD_LISTEN_S)
            except CallEnded:
                self.hold_s += waited
                raise
            dt = (self.clock.now() - t0).total_seconds()
            nominal = getattr(chunk, "duration_s", None) if chunk is not None else HOLD_LISTEN_S
            waited += max(dt, nominal or 0.0)
            if chunk is not None and chunk.audio_class in (AudioClass.HUMAN, AudioClass.IVR_PROMPT):
                self.hold_s += waited
                who = (
                    "HUMAN AGENT JOINED" if chunk.audio_class == AudioClass.HUMAN else "IVR PROMPT"
                )
                await self._system(f"{who} AFTER {_fmt(waited)} HOLD")
                await self._record_callee(chunk)
                if chunk.audio_class == AudioClass.HUMAN:
                    await self._disclose(chunk.language)
                return None
            if (
                chunk is not None
                and chunk.audio_class == AudioClass.QUEUE_ANNOUNCEMENT
                and chunk.text
                and chunk.text != last_queue_text
            ):
                last_queue_text = chunk.text
                if not announced and (m := _WAIT_MIN.search(chunk.text)):
                    announced = True
                    await self._notify(
                        f"On hold with {target}. Expected wait is about {m.group(1)} min."
                    )
            if waited >= next_update:
                next_update += self.settings.hold_user_update_interval_s
                await self._notify(f"Still on hold with {target}, {_fmt(waited)} so far.")
            if waited >= max_hold:
                self.hold_s += waited
                await self._system(f"HOLD TIMEOUT after {_fmt(waited)}")
                await self._safe_hangup()
                await self._notify(
                    f"{target} kept me on hold for {_fmt(waited)}. I'll try again later."
                )
                return CallOutcome.HOLD_TIMEOUT

    async def _notify(self, text: str) -> None:
        if self.notify_user is None:
            return
        try:
            await self.notify_user(text)
        except Exception as e:  # noqa: BLE001
            log.warning("notify_user failed: %r", e)

    # ================================================================== bridge (V-7)
    def _whisper(self) -> str:
        b = self.brief
        parts = [f"Friday here. Connecting you to {b.target.name}."]
        if b.goal:
            parts.append(truncate(b.goal, 90))
        for k, v in list(self.result.collected.items())[:2]:
            parts.append(f"{k}: {truncate(v, 30)}.")
        return truncate(" ".join(parts), 220)  # ~15 s spoken (US-26.2)

    async def _bridge(self, action: CallAction) -> CallOutcome | None:
        assert self.leg is not None and self.brief.user_phone
        if action.text:
            await self._say(action.text, action.language)
        try:
            user_leg = await self.leg.add_participant(
                self.brief.user_phone, announce=self._whisper()
            )
        except ProviderError as e:  # transfer request rejected: stay on the call
            await self._system(
                f"BRIDGE FAILED ({type(e).__name__}): the provider refused the transfer"
            )
            self.bridge_refused = True
            return None
        self._extra_legs.append(user_leg)
        status = await user_leg.wait_for_answer(USER_JOIN_TIMEOUT_S)
        if status != DialStatus.ANSWERED:
            await self._system(f"USER DID NOT JOIN ({status.value})")
            with contextlib.suppress(Exception):  # noqa: BLE001
                await user_leg.hangup()
            return None
        await self._system("USER JOINED THE CALL")
        if action.leave_after_bridge:
            await self.leg.leave()
            self.left = True
            await self._system("FRIDAY LEFT; USER AND CALLEE BRIDGED")
            return CallOutcome.TRANSFERRED
        await self._monitor(user_leg)
        return CallOutcome.TRANSFERRED

    async def _monitor(self, user_leg: CallLeg) -> None:
        """Stay on silently, transcribing both sides (US-26.4)."""
        assert self.leg is not None
        legs: dict[str, CallLeg] = {"callee": self.leg, "user": user_leg}

        async def on_chunk(who: str, t: Transcription) -> bool:
            if who == "callee":
                await self._record_callee(t)
                return False
            text = redact_secrets(t.text or "")
            await self._system(f"USER: {text}")
            if _DROP_OFF.search(t.text or ""):
                await self.leg.leave()  # type: ignore[union-attr]
                self.left = True
                await self._system("FRIDAY LEFT ON USER REQUEST")
                return True
            return False

        await self._duplex(legs, on_chunk)
        if not self.left:
            await self._safe_hangup()

    async def _duplex(
        self,
        legs: dict[str, CallLeg],
        on_chunk: Callable[[str, Transcription], Awaitable[bool]],
    ) -> set[str]:
        """Listen on several legs at once until one hangs up or ``on_chunk`` says stop."""
        timeout = self.settings.call_silence_timeout_s
        pending: dict[str, asyncio.Task] = {
            who: asyncio.ensure_future(leg.listen(timeout)) for who, leg in legs.items()
        }
        ended: set[str] = set()
        idle_rounds = 0
        try:
            while pending and not ended:
                if self._active_s() > self._max_active_s() or self.cancelled:
                    break
                done, _ = await asyncio.wait(pending.values(), return_when=asyncio.FIRST_COMPLETED)
                got_any = False
                for who, task in list(pending.items()):
                    if task not in done:
                        continue
                    del pending[who]
                    try:
                        t = task.result()
                    except CallEnded:
                        ended.add(who)
                        continue
                    if t is not None and (t.text or "").strip():
                        got_any = True
                        try:
                            stop = await on_chunk(who, t)
                        except CallEnded:  # the party we were speaking to hung up
                            ended.add("peer")
                            return ended
                        if stop:
                            return ended
                    pending[who] = asyncio.ensure_future(legs[who].listen(timeout))
                idle_rounds = 0 if got_any else idle_rounds + 1
                if idle_rounds >= 20:
                    break
        finally:
            for task in pending.values():
                task.cancel()
            for task in pending.values():
                with contextlib.suppress(asyncio.CancelledError, CallEnded, Exception):  # noqa: BLE001
                    await task
        return ended

    # ================================================================== translator (V-8)
    async def _translator_loop(self) -> CallOutcome:
        b = self.brief
        assert self.leg is not None
        if not b.user_phone:
            self.result.error = "translator mode needs brief.user_phone"
            await self._safe_hangup()
            return CallOutcome.FAILED
        first = await self.leg.listen(self.settings.call_silence_timeout_s)
        if first is not None:
            await self._record_callee(first)
        await self._disclose(first.language if first else None)
        intro, lang = _line(_TRANSLATOR_INTRO, self._lang(), name=self.name)
        await self._say(intro, lang)
        user_leg = await self.r.telephony.place_call(
            OutboundCallRequest(
                to_phone=b.user_phone,
                task_id=b.task_id,
                record=False,
                ring_timeout_s=USER_JOIN_TIMEOUT_S,
                language=b.user_language,
                metadata={"role": "user", "call_id": self.result.call_id},
            )
        )
        self._extra_legs.append(user_leg)
        status = await user_leg.wait_for_answer(USER_JOIN_TIMEOUT_S)
        if status != DialStatus.ANSWERED:
            await self._system(f"USER DID NOT JOIN ({status.value})")
            self.result.error = "user did not join the translator call"
            return await self._end_with(_SAFE_EXIT, CallOutcome.FAILED)
        await self._system("USER JOINED THE CALL (translator)")
        hello, hlang = _line(_TRANSLATOR_INTRO, b.user_language, name=self.name)
        await self._say(f"{hello}", hlang, leg=user_leg, label="(to user) ")
        directions = {"to_user": 0, "to_callee": 0}

        async def on_chunk(who: str, t: Transcription) -> bool:
            if who == "callee":
                await self._record_callee(t)
                if t.audio_class != AudioClass.HUMAN:
                    return False
                out = await self._translate(t.text, b.user_language, t.language)
                await self._say(out, b.user_language, leg=user_leg, label="(to user) ")
                directions["to_user"] += 1
                return False
            await self._system(f"USER: {redact_secrets(t.text)}")
            if _SECRET_IN_USER.search(t.text) or not check_speech(t.text, b).allowed:
                warn, wl = _line(_TRANSLATOR_SECRET_WARNING, b.user_language)
                await self._system("BLOCKED: user utterance contained a secret - not translated")
                await self._say(warn, wl, leg=user_leg, label="(to user) ")
                return False
            target = self.last_callee_lang or b.opening_language
            out = await self._translate(t.text, target, t.language)
            if not check_speech(out, b).allowed:
                await self._system("BLOCKED: translation contained an unapproved number")
                return False
            await self._say(out, target)
            directions["to_callee"] += 1
            return False

        try:
            await self._duplex({"callee": self.leg, "user": user_leg}, on_chunk)
        finally:
            with contextlib.suppress(Exception):  # noqa: BLE001
                await user_leg.hangup()
            await self._safe_hangup()
        self.result.collected["translated_to_user"] = str(directions["to_user"])
        self.result.collected["translated_to_callee"] = str(directions["to_callee"])
        if directions["to_user"] and directions["to_callee"]:
            return CallOutcome.SUCCESS
        return CallOutcome.PARTIAL

    async def _translate(self, text: str, target: Language, source: Language | None) -> str:
        if source == target:
            return text
        self.translations += 1
        t0 = time.perf_counter()
        out = await self.r.translator.translate(
            text, target=target, source=source, context=self.brief.goal
        )
        self.latency.policy((time.perf_counter() - t0) * 1000)
        return out


def _ivr_key(phone: str) -> str:
    return f"ivr_map:{phone}"


def _fmt(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _optional(c: Container, name: str) -> Any:
    try:
        return c.get(name)
    except Exception:  # noqa: BLE001 - component not wired in this process role
        return None


def build_scripted_policy(c: Container) -> CallPolicy:
    """The runner's policy: scripted briefs (``brief.playbook``) walk their playbook, every
    other brief goes to the LLM-driven brain exactly as before (friday/playbooks)."""
    from friday.playbooks.engine import PlaybookPolicy, RoutingCallPolicy
    from friday.playbooks.understand import LazyBrainUnderstander

    return RoutingCallPolicy(
        lambda: c.brain,
        PlaybookPolicy(
            understander=LazyBrainUnderstander(lambda: c.brain),
            llm_mode=c.settings.playbooks_llm_mode,
            recording=bool(c.settings.call_record),
            clock=c.clock,
        ),
    )


def build_call_runner(c: Container) -> CallRunner:
    """Wires the shared limiter / cache / object store when the container has them."""
    return CallRunner(
        c,
        policy=build_scripted_policy(c) if c.settings.playbooks_enabled else None,
        rate_limiter=_optional(c, "rate_limiter"),
        cache=_optional(c, "cache"),
        recording_store=_optional(c, "object_store"),
    )


__all__ = ["CallRunner", "VoiceCallResult", "build_call_runner"]
