"""The front door: a person calls Friday's public number and talks to Friday.

    classify  -> USER (blind-index lookup) | BUSINESS (call memory; existing path, unchanged)
                 | UNKNOWN
    guard     -> pilot allow-list, per-caller / global rate limits, one live call at a time,
                 max duration, spend cap, abuse hang-up (all before any LLM or TTS spend)
    session   -> fixed AI-disclosure greeting, then either a known-user chat or a short voice
                 onboarding (name, language, spoken consent; NO PIN), then personal-assistant
                 turns: understand (``brain.interpret``), read it back, create the real task
                 through the task engine with the caller as requester.

Hard rules kept here (not only in prompts):
* the first thing a caller hears is the fixed AI disclosure (pre-rendered in the shared TTS cache);
* a PIN / OTP / CVV is never asked for, spoken or passed to the LLM. Vobiz sends no keypad events
  in a media stream, so sensitive actions stay behind WhatsApp + PIN (docs/FRONT_DOOR.md);
* caller ID is not authentication: no memory reads, no identifiers, no approvals, and "delete
  everything" is only honoured by voice for an account with no PIN yet (created minutes ago);
* nothing is created without a spoken yes to the read-back, and Friday never claims something
  happened that did not (pilot: "I cannot phone real businesses yet" is said as it is);
* data minimisation: the transcript goes to a local file (pilot) with secrets redacted; only the
  consented name / language / requests reach the database.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from friday.brain import frontdoor as fd_copy
from friday.core.clock import Clock, to_ist
from friday.core.config import Settings
from friday.core.container import ComponentNotAvailable, Container
from friday.core.events import Event, TaskStatusChanged
from friday.core.interfaces import CallEnded, CallLeg, ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    AudioClass,
    CallBrief,
    CallDirection,
    CallerKind,
    CallMode,
    CallOutcome,
    CallResult,
    Channel,
    Consent,
    ConsentKind,
    ContactTarget,
    DialStatus,
    InboundMessage,
    Intent,
    Language,
    MessageKind,
    OnboardingStep,
    OutboundCallRequest,
    Profile,
    Speaker,
    TargetKind,
    Task,
    TaskStatus,
    TaskType,
    Transcription,
    User,
    UserStatus,
)
from friday.core.safety import check_speech
from friday.db.repositories._base import phone_index
from friday.voice.latency import LatencyRecorder
from friday.voice.text import redact_secrets, strip_fillers

log = get_logger(__name__)

# Internal cost estimate (INR, never shown to callers): the same constants the runner uses.
COST_TELEPHONY_PER_MIN = 0.8
COST_STT_PER_MIN = 0.5
COST_TTS_PER_1K_CHARS = 2.0
COST_LLM_TURN = 0.12

HOLD_AFTER_S = 1.2  # an LLM turn slower than this gets a short "one moment" (a fixed clip)
MAX_NAME_TRIES = 3
MAX_UNCLEAR = 2
MAX_FAILURES = 2
WORDS_TO_SWITCH_LANGUAGE = 3
WINDOW_START_HOUR, WINDOW_END_HOUR = 8, 21  # IST: result call-backs only inside this window

# intents whose handling needs the PIN (or is simply not built for voice): never done on a call
_PIN_INTENTS = {
    Intent.SAVE_IDENTIFIER,
    Intent.QUERY_MEMORY,
    Intent.FORGET,
    Intent.ADD_PERSON,
    Intent.ADD_PLACE,
    Intent.SETTINGS,
    Intent.INVITE,
    Intent.REMEMBER,
}
# audio classes that mean nobody is talking to us (the classifier may call odd speech UNKNOWN or
# IVR_PROMPT; with words in it we still treat it as the caller rather than hang up on a person)
_NOT_A_PERSON = {
    AudioClass.HOLD_MUSIC,
    AudioClass.QUEUE_ANNOUNCEMENT,
    AudioClass.VOICEMAIL,
    AudioClass.SILENCE,
}
_APPROVAL_INTENTS = {Intent.APPROVE, Intent.REJECT, Intent.CHOOSE, Intent.TASK_UPDATE}


# ================================================================================ data types


class Decision(BaseModel):
    route: Literal["serve", "reject", "legacy"]
    kind: CallerKind
    reason: str = ""
    reject_key: str | None = None  # fd_copy.LINES key spoken before hanging up
    silent: bool = False  # abuse: hang up without speaking at all
    user_id: str | None = None


class FrontDoorSummary(BaseModel):
    call_id: str
    caller: str  # masked
    kind: CallerKind
    route: str
    outcome: str
    end_reason: str = ""
    duration_s: float = 0.0
    languages: list[str] = Field(default_factory=list)
    cost_inr_est: float = 0.0
    turns: int = 0
    llm_turns: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    onboarded: bool = False
    tasks: list[str] = Field(default_factory=list)
    transcript_path: str | None = None


class FrontDoorCallFinished(Event):
    summary: FrontDoorSummary
    result: CallResult | None = None


def estimate_call_cost_inr(seconds: float, tts_billed_chars: int, llm_turns: int) -> float:
    minutes = max(0.0, seconds) / 60.0
    return round(
        minutes * (COST_TELEPHONY_PER_MIN + COST_STT_PER_MIN)
        + tts_billed_chars / 1000 * COST_TTS_PER_1K_CHARS
        + llm_turns * COST_LLM_TURN,
        2,
    )


# ================================================================================ guard


class FrontDoorGuard:
    """Per-caller and global rate limits, one live call at a time, spend cap, abuse blocklist.

    In-memory per process (the front door lives in the api process that receives the Vobiz
    webhook; a second replica would need the shared Cache, see docs/FRONT_DOOR.md). Callers are
    keyed by the phone blind index, never the raw number."""

    def __init__(self, settings: Settings, clock: Clock) -> None:
        self.s = settings
        self.clock = clock
        self._admits: dict[str, deque[float]] = {}
        self._rejects: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self.active: dict[str, str] = {}  # call id -> caller key
        self.spend_inr = 0.0

    @property
    def max_concurrent(self) -> int:
        return 1 if self.s.is_pilot else max(1, self.s.frontdoor_max_concurrent)

    @property
    def spend_cap_inr(self) -> float | None:
        if self.s.frontdoor_spend_cap_inr is not None:
            return self.s.frontdoor_spend_cap_inr
        return self.s.pilot_max_spend_inr if self.s.is_pilot else None

    def _now(self) -> float:
        return self.clock.now().timestamp()

    @staticmethod
    def _trim(q: deque[float], now: float, window: float) -> None:
        while q and now - q[0] > window:
            q.popleft()

    def note_reject(self, key: str) -> bool:
        """Record a refused call; True when this caller has now been refused so often that the
        next calls are dropped silently (a prank / scan costs us nothing)."""
        now = self._now()
        q = self._rejects.setdefault(key, deque())
        self._trim(q, now, 3600)
        q.append(now)
        return len(q) > 3

    def rejected_too_often(self, key: str) -> bool:
        now = self._now()
        q = self._rejects.get(key)
        if not q:
            return False
        self._trim(q, now, 3600)
        return len(q) > 3

    def check(self, key: str) -> str | None:
        """None = admit. Otherwise the LINES key to speak before hanging up."""
        now = self._now()
        if self.spend_cap_inr is not None and self.spend_inr >= self.spend_cap_inr:
            return "reject_unavailable"
        if len(self.active) >= self.max_concurrent:
            return "reject_busy"
        self._trim(self._global, now, 3600)
        if len(self._global) >= self.s.frontdoor_global_per_hour:
            return "reject_busy"
        q = self._admits.setdefault(key, deque())
        self._trim(q, now, 86400)
        hour = sum(1 for t in q if now - t <= 3600)
        if hour >= self.s.frontdoor_per_caller_per_hour or len(q) >= (
            self.s.frontdoor_per_caller_per_day
        ):
            return "reject_limit"
        return None

    def admit(self, call_id: str, key: str) -> None:
        now = self._now()
        self._admits.setdefault(key, deque()).append(now)
        self._global.append(now)
        self.active[call_id] = key

    def release(self, call_id: str, cost_inr: float) -> None:
        self.active.pop(call_id, None)
        self.spend_inr = round(self.spend_inr + max(0.0, cost_inr), 2)

    def max_call_s(self) -> int:
        return (
            self.s.frontdoor_pilot_max_call_s if self.s.is_pilot else self.s.frontdoor_max_call_s
        )


# ================================================================================ service


class FrontDoor:
    def __init__(self, c: Container, pipeline: Any, *, clock: Clock | None = None) -> None:
        self.c = c
        self.pipeline = pipeline
        self.settings = c.settings
        self.clock = clock or c.clock
        self.repos = c.repos
        self.bus = c.bus
        self.guard = FrontDoorGuard(self.settings, self.clock)
        self.history: list[FrontDoorSummary] = []
        self.results: ResultCallbacks = ResultCallbacks(self)
        self._tts_languages: frozenset[Language] | None = None
        self._subscribed = False
        self._prerendered = False

    # ------------------------------------------------------------------ wiring
    @property
    def enabled(self) -> bool:
        return bool(self.settings.frontdoor_enabled)

    def subscribe(self) -> None:
        if not self._subscribed:
            self.bus.subscribe(TaskStatusChanged, self.results.on_task_status)
            self._subscribed = True

    def unsubscribe(self) -> None:
        if self._subscribed:
            self.bus.unsubscribe(TaskStatusChanged, self.results.on_task_status)
            self._subscribed = False
        self.results.cancel_all()

    @property
    def default_language(self) -> Language:
        return Language(self.settings.default_language)

    def telephony(self) -> Any:
        try:
            return self.c.telephony
        except Exception:  # noqa: BLE001
            return None

    def brain(self) -> Any:
        try:
            return self.c.get("brain")
        except ComponentNotAvailable:
            return None

    def tts_languages(self) -> frozenset[Language] | None:
        if self._tts_languages is None:
            try:
                self._tts_languages = frozenset(self.c.tts.supported_languages)
            except Exception:  # noqa: BLE001 - simulator legs need no TTS
                return None
        return self._tts_languages

    def _tts_for_prerender(self) -> Any:
        tel = self.telephony()
        for p in getattr(tel, "providers", None) or [tel]:
            tts = getattr(p, "tts", None)
            if tts is not None and hasattr(tts, "prerender"):
                return tts
        return None

    async def prerender(self) -> int:
        """Warm the shared TTS cache with every fixed line (greeting, rejection, hold, goodbye...).
        Returns how many lines needed a vendor call (0 on later runs: the cache persists)."""
        tts = self._tts_for_prerender()
        if tts is None:
            return 0
        misses = 0
        for lang, texts in fd_copy.prerender_plan(self.default_language).items():
            misses += int(await tts.prerender(texts, lang) or 0)
        self._prerendered = True
        return misses

    def callbacks_possible(self, phone: str) -> bool:
        s = self.settings
        if not s.frontdoor_result_callbacks:
            return False
        if s.is_pilot and phone not in set(s.pilot_allowed_numbers):
            return False
        return self.telephony() is not None

    def followup_mode(self, phone: str) -> Literal["callback", "message", "none"]:
        if self.callbacks_possible(phone):
            return "callback"
        if self.settings.resolve_whatsapp() != "simulator":
            return "message"
        return "none"

    def can_dial(self, phone: str | None) -> bool:
        return not self.settings.pilot_dial_blocked(phone)

    # ------------------------------------------------------------------ classification
    async def classify(self, from_phone: str, match: Any = None) -> Decision:
        s = self.settings
        key = phone_index(from_phone)
        if not self.enabled:
            return Decision(route="legacy", kind=CallerKind.UNKNOWN, reason="front door off")
        if s.is_pilot and from_phone not in set(s.pilot_allowed_numbers):
            silent = self.guard.note_reject(key)
            return Decision(
                route="reject",
                kind=CallerKind.UNKNOWN,
                reason="pilot: caller not in the allow-list",
                reject_key=None if silent else "reject_private",
                silent=silent,
            )
        user = await self.repos.users.get_by_phone(from_phone)
        if user is not None:
            if user.status in (UserStatus.SUSPENDED, UserStatus.DELETED, UserStatus.WAITLISTED):
                silent = self.guard.note_reject(key)
                return Decision(
                    route="reject",
                    kind=CallerKind.USER,
                    reason=f"user is {user.status.value}",
                    reject_key=None if silent else "reject_unavailable",
                    silent=silent,
                    user_id=user.id,
                )
            return self._admit_or_reject(key, CallerKind.USER, user.id)
        matched = getattr(match, "status", None)
        if matched is not None and getattr(matched, "value", matched) != "unmatched":
            return Decision(route="legacy", kind=CallerKind.BUSINESS, reason="call-memory match")
        if s.is_pilot or s.frontdoor_open_signup:
            return self._admit_or_reject(key, CallerKind.UNKNOWN, None)
        return Decision(route="legacy", kind=CallerKind.UNKNOWN, reason="signup closed")

    def _admit_or_reject(self, key: str, kind: CallerKind, user_id: str | None) -> Decision:
        if self.guard.rejected_too_often(key):
            return Decision(
                route="reject", kind=kind, reason="repeat caller refused", silent=True
            )
        refuse = self.guard.check(key)
        if refuse is None:
            return Decision(route="serve", kind=kind, user_id=user_id)
        # only a caller over their OWN limit counts towards the silent-drop list; "busy" and the
        # spend cap are not the caller's fault
        silent = self.guard.note_reject(key) if refuse == "reject_limit" else False
        return Decision(
            route="reject",
            kind=kind,
            reason=refuse,
            reject_key=None if silent else refuse,
            silent=silent,
            user_id=user_id,
        )

    # ------------------------------------------------------------------ serving
    def _take_leg(self, ref: str | None) -> CallLeg | None:
        tel = self.telephony()
        take = getattr(tel, "take_inbound", None)
        if not callable(take) or not ref:
            return None
        return take(ref)

    async def reject_unparsable(self, ref: str | None) -> None:
        """Anonymous / hidden caller ID: nothing to classify, so refuse politely and cheaply."""
        leg = self._take_leg(ref)
        if leg is not None:
            key = "reject_private" if self.settings.is_pilot else "reject_unavailable"
            await self._play_reject(leg, key)

    async def serve(
        self, decision: Decision, ref: str | None, from_phone: str, to_number: str | None
    ) -> FrontDoorSummary | None:
        leg = self._take_leg(ref)
        if leg is None:
            log.warning("front door: no parked leg for call %s", ref)
            return None
        if decision.route == "reject":
            await self._play_reject(leg, decision.reject_key if not decision.silent else None)
            summary = FrontDoorSummary(
                call_id=ref or "?",
                caller=mask_phone(from_phone),
                kind=decision.kind,
                route="reject",
                outcome=CallOutcome.DECLINED.value,
                end_reason=decision.reason,
            )
            await self._finish(summary, None)
            return summary
        session = FrontDoorSession(self, leg, from_phone, decision, ref or "?", to_number)
        return await session.run()

    async def _play_reject(self, leg: CallLeg, key: str | None) -> None:
        with contextlib.suppress(CallEnded, ProviderError, Exception):
            if key:
                lang = self.default_language
                await leg.speak(fd_copy.line(key, lang), fd_copy.pick_language(lang))
        with contextlib.suppress(Exception):
            await leg.hangup()

    async def _finish(self, summary: FrontDoorSummary, result: CallResult | None) -> None:
        self.history.append(summary)
        del self.history[:-200]
        with contextlib.suppress(Exception):
            await self.repos.audit.log(
                "frontdoor.call",
                user_id=None,
                actor="system",
                kind=summary.kind.value,
                route=summary.route,
                outcome=summary.outcome,
                reason=summary.end_reason or None,
                seconds=round(summary.duration_s),
                cost_inr=summary.cost_inr_est,
            )
        await self.bus.publish(FrontDoorCallFinished(summary=summary, result=result))


# ================================================================================ session


class FrontDoorSession:
    def __init__(
        self,
        fd: FrontDoor,
        leg: CallLeg,
        phone: str,
        decision: Decision,
        call_id: str,
        to_number: str | None,
    ) -> None:
        self.fd = fd
        self.leg = leg
        self.phone = phone
        self.decision = decision
        self.call_id = call_id
        self.to_number = to_number
        self.s = fd.settings
        self.clock = fd.clock
        self.user: User | None = None
        self.profile: Profile | None = None
        self.consented = False
        self.created_here = False  # onboarded during THIS call
        self.name: str | None = None
        self.state = "chat"
        self.lang: Language = fd.default_language
        self._cand_lang: Language | None = None
        self.languages: list[Language] = []
        self.silences = 0
        self.unclear = 0
        self.failures = 0
        self.name_tries = 0
        self.pending: dict[str, Any] = {}
        self.expect_more = False
        self.ended = False
        self.end_reason = ""
        self.hung_up = False
        self.tasks: list[str] = []
        self.llm_turns = 0
        self.tts_chars = 0
        self.tts_dynamic_chars = 0
        self.latency = LatencyRecorder()
        self.started = self.clock.now()
        self.result = CallResult(
            task_id=f"frontdoor-{call_id}"[:60],
            provider=getattr(leg, "provider", "unknown"),
            provider_call_id=getattr(leg, "provider_call_id", None),
            direction=CallDirection.INBOUND,
            to_phone=phone,
            dial_status=DialStatus.ANSWERED,
            outcome=CallOutcome.SUCCESS,  # set explicitly when anything else happens
            from_number=to_number,
            started_at=self.started,
            answered_at=self.started,
        )
        self._brief = CallBrief(
            task_id=self.result.task_id,
            requester_user_id=decision.user_id or "",
            task_type=TaskType.ENQUIRY,
            goal="front door conversation",
            target=ContactTarget(kind=TargetKind.PERSON, name="Caller", phone=phone),
            on_behalf_of="Friday",
            mode=CallMode.FRONT_DOOR,
        )

    # ------------------------------------------------------------------ plumbing
    def _over_time(self) -> bool:
        return (self.clock.now() - self.started).total_seconds() >= self.fd.guard.max_call_s()

    def _speak_lang(self, lang: Language) -> Language:
        shown = fd_copy.pick_language(lang)
        supported = self.fd.tts_languages()
        if supported and shown not in supported:
            for alt in (Language.HINGLISH, Language.EN):
                if alt in supported:
                    return alt
        return shown

    async def _record(self, speaker: Speaker, text: str, lang: Language | None) -> None:
        self.result.transcript.add(speaker, text, at=self.clock.now(), language=lang)

    async def say(self, text: str, *, fixed: bool = True, lang: Language | None = None) -> None:
        """Speak one utterance. ``fixed`` = a pre-rendered table line; dynamic text is checked
        against the safety rules (never a PIN/OTP/long unknown number) before it is spoken."""
        clean = strip_fillers(text)
        if not clean or self.hung_up:
            return
        if not fixed and not check_speech(clean, self._brief).allowed:
            log.warning("front door: blocked an unsafe utterance")
            clean = fd_copy.line("didnt_catch", self.lang)
            fixed = True
        language = self._speak_lang(lang or self.lang)
        t0 = time.perf_counter()
        await self.leg.speak(clean, language)
        wall = (time.perf_counter() - t0) * 1000
        self.latency.tts(getattr(self.leg, "last_tts_ms", None) or wall)
        self.tts_chars += len(clean)
        if not fixed:
            self.tts_dynamic_chars += len(clean)
        await self._record(Speaker.FRIDAY, clean, language)

    async def hear(self, timeout_s: float | None = None) -> Transcription | None:
        t = await self.leg.listen(timeout_s or self.s.call_silence_timeout_s)
        self.latency.stt(getattr(self.leg, "last_stt_ms", None))
        if t is None:
            return None
        if t.audio_class in _NOT_A_PERSON or not (t.text or "").strip():
            return None  # music / voicemail / silence / empty: treated as silence
        text = redact_secrets(t.text or "")
        await self._record(Speaker.CALLEE, text, t.language)
        if t.language and t.language not in self.languages:
            self.languages.append(t.language)
        return t

    def _observe_language(self, detected: Language | None, text: str) -> None:
        """Mirror the caller turn by turn, with hysteresis (a one-word 'haan' flips nothing)."""
        if detected is None or detected == self.lang:
            self._cand_lang = None
            return
        if len(text.split()) >= WORDS_TO_SWITCH_LANGUAGE or detected == self._cand_lang:
            self.lang, self._cand_lang = detected, None
        else:
            self._cand_lang = detected

    # ------------------------------------------------------------------ run
    async def run(self) -> FrontDoorSummary:
        self.fd.guard.admit(self.call_id, phone_index(self.phone))
        try:
            await asyncio.wait_for(
                self._conversation(), timeout=self.fd.guard.max_call_s() + 20
            )
        except TimeoutError:
            self.end_reason = self.end_reason or "hard time limit"
            self.result.outcome = CallOutcome.PARTIAL
        except CallEnded:
            self.end_reason = self.end_reason or "caller hung up"
            self.hung_up = True
            self.result.outcome = CallOutcome.HUNG_UP
        except asyncio.CancelledError:
            self.end_reason = "cancelled"
            self.result.outcome = CallOutcome.CANCELLED
            await asyncio.shield(self._hangup())
            raise
        except Exception as e:  # noqa: BLE001 - the front door never raises into the webhook
            log.exception("front door call %s failed", self.call_id)
            self.end_reason = f"error: {type(e).__name__}"
            self.result.error = self.end_reason
            self.result.outcome = CallOutcome.FAILED
            with contextlib.suppress(Exception):
                await self.say(fd_copy.line("trouble", self.lang))
        finally:
            await self._hangup()
        return await self._finalise()

    async def _hangup(self) -> None:
        if self.hung_up:
            return
        self.hung_up = True
        with contextlib.suppress(Exception):
            await self.leg.hangup()

    async def _finalise(self) -> FrontDoorSummary:
        r = self.result
        end = self.clock.now()
        r.ended_at = end
        seconds = (end - self.started).total_seconds()
        billed = getattr(self.leg, "tts_billed_chars", None)
        r.tts_chars = self.tts_chars
        r.tts_billed_chars = int(billed) if isinstance(billed, int) else self.tts_dynamic_chars
        r.policy_calls = self.llm_turns
        r.telephony_seconds = round(seconds, 1)
        r.cost_inr_est = estimate_call_cost_inr(seconds, r.tts_billed_chars, self.llm_turns)
        r.languages_heard = list(self.languages)
        r.collected = {
            "caller_kind": self.decision.kind.value,
            "end_reason": self.end_reason,
            "tasks": ",".join(self.tasks),
            "onboarded": str(self.created_here).lower(),
        }
        lat = self.latency.summary()
        self.fd.guard.release(self.call_id, r.cost_inr_est)
        summary = FrontDoorSummary(
            call_id=self.call_id,
            caller=mask_phone(self.phone),
            kind=self.decision.kind,
            route="serve",
            outcome=r.outcome.value,
            end_reason=self.end_reason,
            duration_s=round(seconds, 1),
            languages=[x.value for x in self.languages],
            cost_inr_est=r.cost_inr_est,
            turns=len(r.transcript.turns),
            llm_turns=self.llm_turns,
            p50_ms=round(lat["p50_ms"], 1),
            p95_ms=round(lat["p95_ms"], 1),
            onboarded=self.created_here,
            tasks=list(self.tasks),
        )
        await self.fd._finish(summary, r)
        return summary

    async def _end(self, key: str, reason: str, outcome: CallOutcome = CallOutcome.SUCCESS) -> None:
        self.ended = True
        self.end_reason = reason
        self.result.outcome = outcome
        if outcome == CallOutcome.FAILED:
            self.result.error = reason
        with contextlib.suppress(CallEnded):
            await self.say(fd_copy.line(key, self.lang))
        await self._hangup()

    # ------------------------------------------------------------------ conversation
    async def _conversation(self) -> None:
        await self._load_user()
        await self._greet()
        while not self.ended and not self.hung_up:
            if self._over_time():
                await self._end("time_limit", "max duration", CallOutcome.PARTIAL)
                return
            t = await self.hear()
            if t is None:
                await self._on_silence()
                continue
            self.silences = 0
            text = t.text.strip()
            self._observe_language(t.language, text)
            await self._on_utterance(text, t)

    async def _load_user(self) -> None:
        if self.decision.user_id:
            self.user = await self.fd.repos.users.get(self.decision.user_id)
        if self.user is not None:
            self.profile = await self.fd.repos.profiles.get(self.user.id)
            self.consented = await self.fd.repos.consents.has(
                self.user.id, ConsentKind.TERMS_PRIVACY
            )
            self.name = (self.profile.name if self.profile else None) or None
            if self.profile and self.profile.language:
                self.lang = self.profile.language

    async def _greet(self) -> None:
        if self.user is None:
            self.state = "name"
            await self.say(fd_copy.line("greeting_new", self.lang))
            return
        # the disclosure clip is cached; warm the personal line while it plays
        personal = (
            fd_copy.line("hello_known", self.lang, name=self.name)
            if self.name
            else fd_copy.line("hello_known_noname", self.lang)
        )
        if self.consented:
            tts = self.fd._tts_for_prerender()
            warm = (
                asyncio.ensure_future(tts.prerender([personal], self._speak_lang(self.lang)))
                if tts is not None
                else None
            )
            await self.say(fd_copy.line("disclosure", self.lang))
            if warm is not None:
                with contextlib.suppress(Exception):
                    await warm
            await self.say(personal, fixed=tts is not None)
            self.state = "chat"
        else:  # known number but no consent yet (e.g. mid-onboarding on WhatsApp)
            await self.say(fd_copy.line("disclosure", self.lang))
            self.state = "consent"
            await self.say(fd_copy.line("ask_consent", self.lang))

    async def _on_silence(self) -> None:
        self.silences += 1
        if self.silences >= self.s.frontdoor_max_silences:
            await self._end("silence_bye", "silence", CallOutcome.HUNG_UP)
            return
        if self.silences == 1:
            await self.say(fd_copy.line("silence_prompt", self.lang))

    async def _on_utterance(self, text: str, t: Transcription) -> None:
        # ---- rules that hold in EVERY state, decided without an LLM
        if fd_copy.mentions_secret(text):
            await self.say(fd_copy.line("secret_refusal", self.lang))
            return
        if fd_copy.wants_delete(text):
            await self._delete_requested()
            return
        if fd_copy.asks_if_bot(text):
            await self.say(fd_copy.line("bot_answer", self.lang))
            await self._reprompt()
            return
        handler = getattr(self, f"_state_{self.state}")
        await handler(text, t)

    async def _reprompt(self) -> None:
        """After answering a side question, go back to what we were asking."""
        key = {
            "name": "ask_name_again",
            "language": None,
            "consent": "consent_again",
        }.get(self.state)
        if self.state == "language":
            await self.say(fd_copy.line("ask_language", self.lang, name=self.name or ""))
        elif key:
            await self.say(fd_copy.line(key, self.lang))

    # ------------------------------------------------------------------ onboarding states
    async def _state_name(self, text: str, t: Transcription) -> None:
        if fd_copy.asks_who(text):
            await self.say(fd_copy.line("capabilities", self.lang))
            await self._reprompt()
            return
        name = fd_copy.extract_name(text)
        if name is None:
            self.name_tries += 1
            if self.name_tries >= MAX_NAME_TRIES:
                await self._end("goodbye", "no name given", CallOutcome.PARTIAL)
                return
            await self.say(fd_copy.line("ask_name_again", self.lang))
            return
        self.name = name  # held in memory only until the caller consents
        self.state = "language"
        await self.say(fd_copy.line("ask_language", self.lang, name=name))

    async def _state_language(self, text: str, t: Transcription) -> None:
        choice = fd_copy.parse_language_choice(text)
        if choice is None and t.language in (Language.EN, Language.HI, Language.HINGLISH):
            choice = t.language  # they just answered in a language: take them at their word
        if choice is None:
            choice = self.lang
        self.lang = choice
        self.state = "consent"
        await self.say(fd_copy.line("ask_consent", self.lang))

    async def _state_consent(self, text: str, t: Transcription) -> None:
        if fd_copy.asks_who(text):
            await self.say(fd_copy.line("capabilities", self.lang))
            await self._reprompt()
            return
        if fd_copy.consents_yes(text):
            await self._record_consent(text, t)
            await self.say(fd_copy.line("consent_ok", self.lang, name=self.name or ""))
            self.state = "chat"
            return
        if fd_copy.yes_no(text) is False:
            self.name = None  # nothing was ever written
            await self._end("consent_declined", "consent declined", CallOutcome.SUCCESS)
            return
        self.unclear += 1
        if self.unclear > MAX_UNCLEAR:
            await self._end("consent_declined", "consent unclear", CallOutcome.PARTIAL)
            return
        await self.say(fd_copy.line("consent_again", self.lang))

    async def _record_consent(self, text: str, t: Transcription) -> None:
        """Spoken consent (DPDP): only now do a user row, profile and consent record exist."""
        repos = self.fd.repos
        now = self.clock.now()
        if self.user is None:
            user = User(
                phone=self.phone,
                status=UserStatus.ONBOARDING,
                # name, language and consent are done; the PIN is set later on WhatsApp
                onboarding_step=OnboardingStep.PIN,
                invites_remaining=0,
                created_at=now,
                updated_at=now,
            )
            await repos.users.add(user)
            self.user = user
            self.created_here = True
            await self.fd.pipeline.audit("user.created", user, via="voice")
        user = self.user
        profile = await repos.profiles.get_or_default(user.id)
        if self.name:
            profile = profile.model_copy(update={"name": self.name})
        pref = fd_copy.pick_language(self.lang)
        profile = profile.model_copy(update={"language": pref})
        await repos.profiles.save(profile)
        self.profile = profile
        await repos.consents.add(
            Consent(
                user_id=user.id,
                kind=ConsentKind.TERMS_PRIVACY,
                granted=True,
                evidence_text=f"(spoken on a call) {text[:200]}",
                recorded_at=now,
            )
        )
        await self.fd.pipeline.audit("consent.granted", user, kind="terms_privacy", via="voice")
        self.consented = True

    async def _delete_requested(self) -> None:
        """'Delete everything' by voice. Caller ID is not authentication, so a real account (one
        with a PIN) is only deleted from WhatsApp behind the PIN; an account created minutes ago
        by voice (no PIN yet) and a caller who has not consented yet can be erased on the spot."""
        user = self.user
        if user is None:  # nothing was stored yet
            self.name = None
            await self._end("deleted_nothing", "delete requested before consent")
            return
        if user.pin_hash:
            await self.say(fd_copy.line("delete_needs_pin", self.lang))
            if self.state != "chat":
                await self._reprompt()
            return
        try:
            await self.fd.pipeline.delete_everything(user)
        except Exception:  # noqa: BLE001
            log.exception("voice delete failed")
            await self._end("trouble", "delete failed", CallOutcome.FAILED)
            return
        self.user = None
        self.created_here = False
        await self._end("deleted_fresh", "user deleted their data by voice")

    # ------------------------------------------------------------------ chat state
    async def _state_chat(self, text: str, t: Transcription) -> None:
        assert self.user is not None
        words = text.split()
        if self.expect_more and (fd_copy.yes_no(text) is False or fd_copy.wants_to_end(text)):
            await self._end("goodbye", "caller finished")
            return
        if fd_copy.wants_to_end(text) and len(words) <= 6:
            await self._end("goodbye", "caller finished")
            return
        self.expect_more = False
        if fd_copy.asks_who(text) and len(words) <= 8:
            key = "capabilities_pilot" if self.s.pilot_blocks_business_calls else "capabilities"
            await self.say(fd_copy.line(key, self.lang))
            return
        await self._understand(text)

    async def _state_confirm(self, text: str, t: Transcription) -> None:
        answer = fd_copy.yes_no(text)
        kind = self.pending.get("kind")
        if answer is True and kind == "task":
            self.state = "chat"
            await self._start_task()
            return
        if answer is True and kind == "cancel":
            self.state = "chat"
            await self._cancel_task()
            return
        if answer is False:
            self.pending, self.state = {}, "chat"
            await self.say(fd_copy.line("confirm_no", self.lang))
            return
        if len(text.split()) >= 4:  # a new request instead of yes/no
            self.pending, self.state = {}, "chat"
            await self._understand(text)
            return
        self.unclear += 1
        if self.unclear > MAX_UNCLEAR:
            self.pending, self.state = {}, "chat"
            await self.say(fd_copy.line("confirm_no", self.lang))
            return
        await self.say(fd_copy.line("confirm_again", self.lang))

    # ------------------------------------------------------------------ understanding
    async def _understand(self, text: str) -> None:
        assert self.user is not None
        brain = self.fd.brain()
        if brain is None:
            await self._end("trouble", "no brain", CallOutcome.FAILED)
            return
        msg = InboundMessage(
            channel=Channel.VOICE,
            from_phone=self.phone,
            user_id=self.user.id,
            kind=MessageKind.TEXT,
            text=text,
        )
        try:
            interp = await self._interpret(brain, msg)
        except Exception:  # noqa: BLE001
            log.exception("front door: interpret failed")
            self.failures += 1
            if self.failures > MAX_FAILURES:
                await self._end("trouble", "brain failing", CallOutcome.FAILED)
                return
            await self.say(fd_copy.line("didnt_catch", self.lang))
            return
        self.failures = 0
        await self._act(interp, msg)

    async def _interpret(self, brain: Any, msg: InboundMessage) -> Any:
        ctx = await self.fd.pipeline.context(self.user)
        t0 = time.perf_counter()
        job = asyncio.ensure_future(brain.interpret(ctx, msg))
        done, _ = await asyncio.wait({job}, timeout=HOLD_AFTER_S)
        if not done:  # slow turn: a fixed "one moment" clip instead of dead air
            await self.say(fd_copy.line("hold", self.lang))
        interp = await job
        self.latency.policy((time.perf_counter() - t0) * 1000)
        self.llm_turns += 1
        return interp

    async def _act(self, interp: Any, msg: InboundMessage) -> None:
        intent = interp.intent
        if intent == Intent.DELETE_DATA:
            await self._delete_requested()
            return
        if intent == Intent.NEW_TASK and interp.task_spec is not None:
            await self._propose_task(interp, msg)
            return
        if intent == Intent.CANCEL_TASK:
            await self._propose_cancel(interp)
            return
        if intent in _PIN_INTENTS or interp.requires_pin:
            await self.say(fd_copy.line("need_pin_elsewhere", self.lang))
            self.expect_more = True
            return
        if intent in _APPROVAL_INTENTS:
            await self.say(fd_copy.line("approvals_not_by_voice", self.lang))
            self.expect_more = True
            return
        if intent == Intent.STATUS:
            await self._status()
            return
        reply = fd_copy.speakable(interp.reply)
        if reply and intent in (Intent.HELP, Intent.SMALL_TALK, Intent.UNKNOWN):
            await self.say(reply, fixed=False)
            return
        if intent in (Intent.HELP, Intent.SMALL_TALK):
            await self.say(fd_copy.line("capabilities", self.lang))
            return
        self.unclear += 1
        await self.say(fd_copy.line("didnt_catch", self.lang))

    async def _status(self) -> None:
        assert self.user is not None
        tasks = await self.fd.repos.tasks.list_for_user(self.user.id, open_only=True)
        if not tasks:
            await self.say(fd_copy.line("no_open_tasks", self.lang))
            return
        newest = sorted(tasks, key=lambda x: x.created_at)[-1]
        goal = fd_copy.spoken_goal(newest.spec.goal)
        state = _status_words(newest.status, fd_copy.pick_language(self.lang))
        await self.say(f"{goal[:1].upper() + goal[1:]}: {state}", fixed=False)
        self.expect_more = True
        await self.say(fd_copy.line("anything_else", self.lang))

    # ------------------------------------------------------------------ tasks
    async def _propose_task(self, interp: Any, msg: InboundMessage) -> None:
        spec = interp.task_spec
        if spec.missing:
            # the brain asks the one question it still needs; keep the short reply only
            question = fd_copy.speakable(interp.reply)
            await self.say(question or fd_copy.line("didnt_catch", self.lang), fixed=False)
            return
        if not self.fd.can_dial(spec.business_phone):
            # pilot: the engine would refuse; say so honestly BEFORE promising anything
            self.expect_more = True
            await self.say(fd_copy.line("pilot_no_business_calls", self.lang))
            return
        goal = fd_copy.spoken_goal(spec.goal)
        self.pending = {"kind": "task", "interp": interp, "msg": msg}
        self.state = "confirm"
        self.unclear = 0
        await self.say(fd_copy.line("confirm_task", self.lang, goal=goal), fixed=False)

    async def _start_task(self) -> None:
        assert self.user is not None
        interp, msg = self.pending["interp"], self.pending["msg"]
        self.pending = {}
        try:
            await self.fd.repos.messages.log_inbound(
                msg.model_copy(update={"text": redact_secrets(msg.text or "")})
            )
            task, queued_until = await self.fd.pipeline.create_task(
                self.user, interp.task_spec, msg, interp=interp
            )
        except Exception:  # noqa: BLE001
            log.exception("front door: could not create the task")
            self.expect_more = True
            await self.say(fd_copy.line("task_not_started", self.lang))
            return
        self.tasks.append(task.id)
        fresh = await self.fd.repos.tasks.get(task.id) or task
        if fresh.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.expect_more = True
            why = fd_copy.speakable(fresh.result.summary if fresh.result else "")
            await self.say(why or fd_copy.line("task_not_started", self.lang), fixed=not why)
            return
        mode = self.fd.followup_mode(self.phone)
        if queued_until is not None:
            key = "task_queued"
        else:
            key = {
                "callback": "task_started_callback",
                "message": "task_started_message",
                "none": "task_started_plain",
            }[mode]
        if mode == "callback" and queued_until is None:
            self.fd.results.watch(task.id, self.user.id, self.phone)
        self.expect_more = True
        await self.say(fd_copy.line(key, self.lang))

    async def _propose_cancel(self, interp: Any) -> None:
        assert self.user is not None
        task = await self.fd.repos.tasks.get(interp.task_id) if interp.task_id else None
        if task is None or task.requester_user_id != self.user.id or task.status.is_terminal:
            await self.say(fd_copy.line("no_open_tasks", self.lang))
            return
        self.pending = {"kind": "cancel", "task": task}
        self.state = "confirm"
        self.unclear = 0
        goal = fd_copy.spoken_goal(task.spec.goal)
        await self.say(fd_copy.line("cancel_confirm", self.lang, goal=goal), fixed=False)

    async def _cancel_task(self) -> None:
        task: Task = self.pending.pop("task")
        engine = self.fd.pipeline.engine()
        cancel = getattr(engine, "cancel", None)
        if cancel is not None:
            await cancel(task.id)
        await self.fd.pipeline.audit(
            "task.cancelled", self.user, actor="user", subject_id=task.id, via="voice"
        )
        self.expect_more = True
        await self.say(fd_copy.line("cancel_done", self.lang))


def _status_words(status: TaskStatus, lang: Language) -> str:
    table = {
        TaskStatus.AWAITING_APPROVAL: (
            "it is waiting for your approval, which I cannot take on a call",
            "yeh aapke approval ka intezaar kar raha hai, jo main call par nahi le sakti",
        ),
        TaskStatus.CALLING: ("I am on the call now", "main abhi call par hoon"),
        TaskStatus.SCHEDULED: ("it is scheduled", "yeh schedule ho chuka hai"),
    }
    en, hi = table.get(status, ("it is in progress", "yeh chal raha hai"))
    return en if lang == Language.EN else hi


# ================================================================================ result call-backs


class ResultCallbacks:
    """Call the caller back about a task they asked for on a call.

    Honest limits: at most one call-back per task and stage (an offer waiting for approval; the
    final result), only 08:00-21:00 IST, only to a number the pilot allow-list permits, and held
    in process memory (a restart forgets pending call-backs; the WhatsApp/outbox message still
    goes out). An offer call-back never claims a booking: approvals are not taken on a call."""

    def __init__(self, fd: FrontDoor) -> None:
        self.fd = fd
        self.watched: dict[str, tuple[str, str]] = {}  # task id -> (user id, phone)
        self.done: set[tuple[str, str]] = set()
        self.calls: list[dict[str, Any]] = []  # what happened (tests / summary)
        self._bg: set[asyncio.Future[Any]] = set()

    async def wait_idle(self) -> None:
        while self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)

    def cancel_all(self) -> None:
        for task in list(self._bg):
            task.cancel()

    def watch(self, task_id: str, user_id: str, phone: str) -> None:
        self.watched[task_id] = (user_id, phone)

    async def on_task_status(self, event: TaskStatusChanged) -> None:
        if event.task_id not in self.watched:
            return
        if event.new.is_terminal:
            stage = "final"
        elif event.new == TaskStatus.AWAITING_APPROVAL:
            stage = "offer"
        else:
            return
        if (event.task_id, stage) in self.done:
            return
        self.done.add((event.task_id, stage))
        user_id, phone = self.watched[event.task_id]
        if stage == "final":
            self.watched.pop(event.task_id, None)
        # The call-back rings a phone for seconds: never hold up the engine's status change.
        job = asyncio.ensure_future(self._deliver_safely(event.task_id, user_id, phone, stage))
        self._bg.add(job)
        job.add_done_callback(self._bg.discard)

    async def _deliver_safely(self, task_id: str, user_id: str, phone: str, stage: str) -> None:
        try:
            await self.deliver(task_id, user_id, phone, stage)
        except Exception:  # noqa: BLE001 - a failed call-back never breaks the task
            log.exception("front door result call-back failed")

    def _in_window(self) -> bool:
        h = to_ist(self.fd.clock.now()).hour
        return WINDOW_START_HOUR <= h < WINDOW_END_HOUR

    async def deliver(self, task_id: str, user_id: str, phone: str, stage: str = "final") -> bool:
        fd = self.fd
        task = await fd.repos.tasks.get(task_id)
        if task is None or not fd.callbacks_possible(phone):
            return False
        record: dict[str, Any] = {"task_id": task_id, "stage": stage, "placed": False}
        self.calls.append(record)
        if not self._in_window():
            record["skipped"] = "outside 08:00-21:00 IST"
            return False
        if fd.guard.spend_cap_inr is not None and fd.guard.spend_inr >= fd.guard.spend_cap_inr:
            record["skipped"] = "spend cap"
            return False
        profile = await fd.repos.profiles.get(user_id)
        lang = fd_copy.pick_language(profile.language if profile else fd.default_language)
        name = (profile.name if profile else None) or ""
        summary = fd_copy.speakable(task.result.summary if task.result else "")
        parts = [fd_copy.line("disclosure", lang), fd_copy.line("cb_update", lang, name=name)]
        if stage == "offer":
            if summary:
                parts.append(summary)
            parts.append(
                fd_copy.line(
                    "cb_offer_whatsapp"
                    if fd.settings.resolve_whatsapp() != "simulator"
                    else "cb_offer_novoice",
                    lang,
                )
            )
        else:
            parts.append(summary or fd_copy.line("cb_unfinished", lang))
        parts.append(fd_copy.line("goodbye", lang))
        tel = fd.telephony()
        s = fd.settings
        from_number = (s.sarvam_caller_ids or s.friday_numbers or [None])[0]
        req = OutboundCallRequest(
            to_phone=phone,
            task_id=f"cb-{task_id}"[:60],
            record=False,
            ring_timeout_s=25,
            max_duration_s=60,
            metadata={"role": "user", "purpose": "result_callback"},
            from_number=from_number,
        )
        started = fd.clock.now()
        leg = await tel.place_call(req)
        status = await leg.wait_for_answer(req.ring_timeout_s)
        record["status"] = status.value
        if status != DialStatus.ANSWERED:
            fd.guard.spend_inr = round(fd.guard.spend_inr + 0.1, 2)
            return False
        brief = CallBrief(
            task_id=req.task_id,
            requester_user_id=user_id,
            task_type=TaskType.ENQUIRY,
            goal="result call-back",
            target=ContactTarget(kind=TargetKind.PERSON, name=name or "User", phone=phone),
            on_behalf_of="Friday",
            mode=CallMode.FRONT_DOOR,
        )
        spoken = 0
        try:
            for part in parts:
                clean = strip_fillers(part)
                if not clean or not check_speech(clean, brief).allowed:
                    continue
                spoken += len(clean)
                await leg.speak(clean, lang)
            record["placed"] = True
        except CallEnded:
            record["placed"] = True
        finally:
            with contextlib.suppress(Exception):
                await leg.hangup()
            secs = (fd.clock.now() - started).total_seconds()
            fd.guard.spend_inr = round(
                fd.guard.spend_inr + estimate_call_cost_inr(secs, spoken, 0), 2
            )
        return True


__all__ = [
    "Decision",
    "FrontDoor",
    "FrontDoorCallFinished",
    "FrontDoorGuard",
    "FrontDoorSession",
    "FrontDoorSummary",
    "ResultCallbacks",
    "estimate_call_cost_inr",
]
