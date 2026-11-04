# ruff: noqa: E501, SIM905
"""The care protocol: state machine, follow-up check-ins and the central gate (docs/CARE_PROTOCOL.md).

NOT a clinical tool. Always on: no feature switch turns it off (only the test-only kill switch
``FRIDAY_CARE_KILL_SWITCH``, ignored in prod).

What it keeps per user (shared Cache, TTL 4 days, DELETED by "delete everything"): the tier, a few
timestamps and flags. It never keeps the user's words, a name or a draft.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from friday.care import copy
from friday.care.detect import (
    Tier,
    assess,
    detect_language,
    names_person,
    says_call_me,
    says_no,
    says_okay,
    says_stop,
    says_yes,
)
from friday.core.clock import at_ist, ensure_utc, is_quiet_hours, to_ist
from friday.core.logging import get_logger

log = get_logger(__name__)

STATE_TTL_S = 4 * 24 * 3600
HIGH_HOLD = timedelta(hours=36)  # features stay paused at most this long after the last HIGH message
MAX_HOLDS = 2  # neutral messages answered with a "paused" line before the user is let through
SAME_DAY_GAP = timedelta(hours=4)
MIN_GAP = timedelta(minutes=45)
SAME_DAY_LATEST_IST = (23, 30)
MORNING_HOUR_IST = 9
MORNING_GRACE = timedelta(hours=12)
INDEX_KEY = "care:index"

Sender = Callable[[str, str], Awaitable[Any]]  # (user_id, text)


def user_ref(user_id: str) -> str:
    """The only identifier that ever reaches a log line."""
    return hashlib.sha256(f"care:{user_id}".encode()).hexdigest()[:8]


@dataclass
class CareState:
    tier: str = "none"  # none | elevated | high
    lang: str = "hinglish"
    since: str = ""  # ISO UTC: first message of this episode
    last_distress_at: str = ""
    last_user_at: str = ""
    asked_safety: bool = False
    safety_answer: str | None = None  # yes | no
    helpline_given: bool = False
    awaiting: str | None = None  # person | family | None
    offered_call: bool = False
    holds: int = 0
    paused: bool = False
    same_day_done: bool = False
    morning_done: bool = False
    cancelled: bool = False  # the user said okay / stop: no more check-ins
    released: bool = False  # the gate is open again
    elder: bool = False  # a 60+ speaker: the plain, slow wording
    family_consent: str | None = None  # yes | no | None (not asked / not answered)
    emergency: bool = False  # explicit danger words: the family line may go without consent
    family_notified: bool = False  # the single family line was already handed out

    def dump(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, raw: dict[str, Any]) -> CareState:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _ln(st: CareState | None, key: str, lang: str, **fmt: str) -> str:
    return copy.line(key, lang, elder=bool(st and st.elder), **fmt)


_EMERGENCY_WORDS = re.compile(
    r"\b(?:112|ambulance|emergency|overdose|bachao|took\s+all|swallowed|right\s+now)\b|बचाओ|एम्बुलेंस|एंबुलेंस",
    re.IGNORECASE,
)
_METHOD_RULES = frozenset({"en.method", "hg.method", "hi.method"})


def _dt(value: str) -> datetime | None:
    return ensure_utc(datetime.fromisoformat(value)) if value else None


@dataclass
class CareTurn:
    """What the pipeline must do with this inbound message."""

    tier: Tier
    replies: list[str] = field(default_factory=list)  # sent in order as separate messages
    redact: bool = True  # the stored copy of the user's message is replaced by a placeholder
    release: bool = False  # the protocol ended on this message (okay / stop)


class CareStore:
    def __init__(self, cache: Any) -> None:
        self.cache = cache
        self._lock = asyncio.Lock()

    @staticmethod
    def key(user_id: str) -> str:
        return f"care:{user_id}"

    async def get(self, user_id: str) -> CareState | None:
        raw = await self.cache.get(self.key(user_id))
        return CareState.load(raw) if raw else None

    async def put(self, user_id: str, st: CareState) -> None:
        await self.cache.set(self.key(user_id), st.dump(), ttl_s=STATE_TTL_S)
        async with self._lock:
            idx = list(await self.cache.get(INDEX_KEY) or [])
            if user_id not in idx:
                idx.append(user_id)
                await self.cache.set(INDEX_KEY, idx)

    async def delete(self, user_id: str) -> None:
        await self.cache.delete(self.key(user_id))
        async with self._lock:
            idx = [u for u in (await self.cache.get(INDEX_KEY) or []) if u != user_id]
            await self.cache.set(INDEX_KEY, idx)

    async def active_ids(self) -> list[str]:
        return list(await self.cache.get(INDEX_KEY) or [])


class CareService:
    def __init__(
        self,
        cache: Any,
        clock: Any,
        *,
        settings: Any = None,
        sender: Sender | None = None,
        call_allowed: Callable[[str], Awaitable[bool]] | None = None,
        place_call: Callable[[str], Awaitable[bool]] | None = None,
        pause_work: Callable[[str], Awaitable[bool]] | None = None,
        elder_check: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.store = CareStore(cache)
        self.clock = clock
        self.settings = settings
        self.sender = sender  # follow-up check-ins
        self.call_allowed = call_allowed  # the user's OWN allow-listed number, existing call rules
        self.place_call = place_call
        self.elder_check = elder_check  # True when the speaker is 60+ (ROBIN sets this)
        self.pause_work = pause_work  # pauses an open payment/booking; True when something was paused

    # ------------------------------------------------------------------ switches
    @property
    def enabled(self) -> bool:
        s = self.settings
        killed = s is not None and getattr(s, "care_kill_switch", False) and getattr(s, "env", "prod") in ("dev", "test")
        return not killed  # the kill switch is for tests only; never honoured in prod

    # ------------------------------------------------------------------ the gate
    async def blocked(self, user_id: str) -> bool:
        """True while a HIGH episode is active for this user: no planner, shopping, jobs, steps,
        browser agent, proactive intent or promotional nudge may start. One place, many callers."""
        if not self.enabled:
            return False
        st = await self.store.get(user_id)
        return self._active_high(st, self.clock.now())

    async def is_active(self, user_id: str) -> bool:
        """STABLE API for other packages (friday/robin): True while a care episode (HIGH) is active
        for this user. Call it before every outbound check-in call, nudge or digest line; when True,
        do not start anything. Same answer as :meth:`blocked`."""
        return await self.blocked(user_id)

    async def family_line(self, user_id: str, name: str, lang: str | None = None) -> str | None:
        """The ONLY text that may go to the other family member about a care episode:
        "<name> may need you, please call." Returned once per episode, and only when the speaker
        agreed (or explicit danger words were used). Never includes anything the speaker wrote.
        None: send nothing."""
        if not self.enabled:
            return None
        st = await self.store.get(user_id)
        if st is None or st.tier == "none" or st.family_notified:
            return None
        if st.family_consent != "yes" and not st.emergency:
            return None
        words = [w for w in re.findall(r"[^\W\d_]+", name or "", flags=re.UNICODE) if w.lower() not in ("http", "https", "www", "com")]
        clean = " ".join(words[:3])[:30] or "Your family member"
        st.family_notified = True
        await self.store.put(user_id, st)
        return copy.line("family_line", lang or st.lang, name=clean)

    @staticmethod
    def _active_high(st: CareState | None, now: datetime) -> bool:
        if st is None or st.tier != "high" or st.released:
            return False
        last = _dt(st.last_distress_at)
        return last is not None and now - last < HIGH_HOLD

    async def forget(self, user_id: str) -> None:
        """"delete everything": the care state goes with the rest."""
        await self.store.delete(user_id)

    # ------------------------------------------------------------------ one inbound message
    async def screen(self, user_id: str, text: str | None, *, is_text: bool = True, elder: bool = False) -> CareTurn | None:
        """Look at one inbound message. None: not for the care protocol, carry on as usual."""
        if not self.enabled:
            return None
        now = self.clock.now()
        st = await self.store.get(user_id)
        active = self._active_high(st, now)
        a = assess(text) if (text and is_text) else None
        tier = a.tier if a else Tier.NONE
        if st is not None and not st.elder and (elder or (self.elder_check is not None and tier != Tier.NONE)):
            st.elder = elder or await self._is_elder(user_id)
        elif st is None and tier != Tier.NONE:
            self._pending_elder = elder or await self._is_elder(user_id)

        if tier == Tier.HIGH:
            return await self._high(user_id, st, a, text or "", now, active)
        if tier == Tier.ELEVATED:
            if active:
                return await self._while_high(user_id, st, text, now, a.lang, elevated=True)
            return await self._elevated(user_id, st, a, now)
        if active:
            return await self._while_high(user_id, st, text, now, detect_language(text or "") if text else (st.lang if st else "hinglish"))
        return None

    # ------------------------------------------------------------------ HIGH
    async def _high(self, user_id: str, st: CareState | None, a: Any, text: str, now: datetime, active: bool) -> CareTurn:
        lang = self._lang(st, a.lang, text)
        replies: list[str] = []
        if st is None or not active:
            st = CareState(tier="high", lang=lang, since=now.isoformat(), elder=self._take_elder() or bool(st and st.elder))
        st.tier, st.lang = "high", lang
        st.last_distress_at = st.last_user_at = now.isoformat()
        st.released = st.cancelled = False
        st.same_day_done = st.morning_done = False
        st.holds = 0
        if any(r in _METHOD_RULES for r in a.reasons) or _EMERGENCY_WORDS.search(text):
            st.emergency = True  # explicit danger: overrides the consent default for the one family line
        if not st.asked_safety:
            st.asked_safety, st.helpline_given, st.awaiting = True, True, None
            replies.append(_ln(st, "high_first", lang))
        elif st.safety_answer is None:
            # still no answer to the question: treat a distressed message as a yes, a plain "no" as a no
            st.safety_answer = "no" if says_no(text) else "yes"
            replies.append(_ln(st, "answer_yes" if st.safety_answer == "yes" else "answer_no", lang))
            await self._maybe_offer_call(user_id, st, replies, lang)
            self._ask_family(st, replies, lang)
        else:
            replies.append(_ln(st, "stay", lang))
        if self.pause_work is not None and not st.paused:
            try:
                if await self.pause_work(user_id):
                    replies.append(_ln(st, "paused_task", lang))
                st.paused = True
            except Exception:  # noqa: BLE001 - never block the care reply
                log.warning("care: pausing open work failed")
        await self.store.put(user_id, st)
        log.info("care_tier=high user=%s", user_ref(user_id))
        return CareTurn(Tier.HIGH, replies)

    # ------------------------------------------------------------------ ELEVATED
    async def _elevated(self, user_id: str, st: CareState | None, a: Any, now: datetime) -> CareTurn:
        lang = self._lang(st, a.lang, "")
        fresh = st is None or st.tier == "none"
        st = st or CareState(since=now.isoformat(), elder=self._take_elder())
        if a.third_party:
            reply = _ln(st, "third_party", lang)
        elif st.helpline_given:
            reply = _ln(st, "elevated_again", lang)
        else:
            reply = _ln(st, "elevated_first", lang)
            st.helpline_given = True
        if st.tier != "high":
            st.tier = "elevated"
        st.lang = lang
        st.last_user_at = now.isoformat()
        if fresh or not st.last_distress_at:
            st.last_distress_at = now.isoformat()
        await self.store.put(user_id, st)
        log.info("care_tier=elevated user=%s", user_ref(user_id))
        return CareTurn(Tier.ELEVATED, [reply])

    # ------------------------------------------------------------------ a message while HIGH is active
    async def _while_high(self, user_id: str, st: CareState, text: str | None, now: datetime, lang_guess: str, *, elevated: bool = False) -> CareTurn | None:
        lang = st.lang if (not text or len(text.split()) < 3) else lang_guess
        st.lang = lang
        st.last_user_at = now.isoformat()
        replies: list[str] = []
        if text and says_stop(text):
            st.cancelled = st.released = True
            st.tier = "elevated"
            await self.store.put(user_id, st)
            log.info("care_tier=high_released user=%s", user_ref(user_id))
            return CareTurn(Tier.HIGH, [_ln(st, "stopped", lang)], release=True)
        if text and says_okay(text) and not elevated:
            st.cancelled = st.released = True
            st.tier = "elevated"
            await self.store.put(user_id, st)
            log.info("care_tier=high_released user=%s", user_ref(user_id))
            return CareTurn(Tier.HIGH, [_ln(st, "steady", lang)], release=True)
        if st.awaiting == "family" and text and (says_yes(text) or says_no(text)):
            st.family_consent = "yes" if says_yes(text) else "no"
            st.awaiting = None
            replies.append(_ln(st, "family_yes" if st.family_consent == "yes" else "family_no", lang))
        elif st.asked_safety and st.safety_answer is None and text and (says_yes(text) or says_no(text)):
            st.safety_answer = "yes" if says_yes(text) else "no"
            replies.append(_ln(st, "answer_yes" if st.safety_answer == "yes" else "answer_no", lang))
            await self._maybe_offer_call(user_id, st, replies, lang)
            self._ask_family(st, replies, lang)
        elif text and says_call_me(text):
            await self._call(user_id, st, replies, lang)
        elif text and (named := self._person_in(text, st)):
            replies.append(self._draft(named, lang))
            st.awaiting = None
        elif text and st.awaiting is None and says_yes(text) and st.safety_answer is not None:
            st.awaiting = "person"
            replies.append(_ln(st, "person_ask", lang))
        elif elevated:
            replies.append(_ln(st, "stay", lang))
        else:
            st.holds += 1
            if st.holds > MAX_HOLDS or (st.morning_done and st.holds > 1):
                st.released = True  # the user is moving on: let the message through, say nothing more
                await self.store.put(user_id, st)
                log.info("care_tier=high_released user=%s", user_ref(user_id))
                return None
            replies.append(_ln(st, "hold_a" if st.holds % 2 else "hold_b", lang))
        await self.store.put(user_id, st)
        log.info("care_tier=high user=%s", user_ref(user_id))
        return CareTurn(Tier.HIGH, replies)

    # ------------------------------------------------------------------ pieces
    _pending_elder = False

    def _take_elder(self) -> bool:
        v, self._pending_elder = self._pending_elder, False
        return v

    async def _is_elder(self, user_id: str) -> bool:
        if self.elder_check is None:
            return False
        try:
            return bool(await self.elder_check(user_id))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _ask_family(st: CareState, replies: list[str], lang: str) -> None:
        """Ask ONCE whether the family may be told to call. Default: nothing is shared."""
        if st.family_consent is None:
            replies.append(_ln(st, "family_ask", lang))
            st.awaiting = "family"

    @staticmethod
    def _lang(st: CareState | None, detected: str, text: str) -> str:
        if st is not None and st.tier != "none" and len(text.split()) < 3:
            return st.lang
        return detected

    @staticmethod
    def _person_in(text: str, st: CareState) -> str | None:
        who = names_person(text)
        if who is None:
            return None
        relation = who.lower() in _RELATIONS
        if relation or st.awaiting == "person":
            return who
        return None

    @staticmethod
    def _draft(who: str, lang: str) -> str:
        relation = who.lower() in _RELATIONS
        name = "" if relation else f" {who}"
        body = copy.line("draft_body", lang, name=name)
        return copy.line("draft", lang, who=who, body=body)

    async def _maybe_offer_call(self, user_id: str, st: CareState, replies: list[str], lang: str) -> None:
        if st.offered_call or self.call_allowed is None:
            return
        try:
            if await self.call_allowed(user_id):
                replies.append(_ln(st, "offer_call", lang))
                st.offered_call = True
        except Exception:  # noqa: BLE001
            log.warning("care: call check failed")

    async def _call(self, user_id: str, st: CareState, replies: list[str], lang: str) -> None:
        ok = False
        if self.call_allowed is not None and self.place_call is not None:
            try:
                ok = bool(await self.call_allowed(user_id)) and bool(await self.place_call(user_id))
            except Exception:  # noqa: BLE001
                log.warning("care: own-number call failed")
        replies.append(_ln(st, "call_placed" if ok else "call_unavailable", lang))

    # ------------------------------------------------------------------ follow-up check-ins
    @staticmethod
    def checkin_times(st: CareState) -> tuple[datetime, datetime]:
        """(same-day check-in, next-morning check-in), both UTC."""
        last = _dt(st.last_user_at) or _dt(st.last_distress_at)
        assert last is not None
        local = to_ist(last)
        latest = at_ist(local.date(), *SAME_DAY_LATEST_IST)
        same_day = max(last + MIN_GAP, min(last + SAME_DAY_GAP, latest))
        morning = at_ist(local.date() + timedelta(days=1), MORNING_HOUR_IST)
        return same_day, morning

    async def tick(self, now: datetime | None = None, *, owns: Callable[[str], bool] | None = None) -> list[tuple[str, str]]:
        """One deterministic pass (called from the proactive tick): send every check-in that is due.
        Returns [(user_ref, which)] for tests and logs. Same-day check-in: any hour (HIGH only).
        Morning check-in: not in quiet hours. Then stop."""
        if not self.enabled:
            return []
        now = ensure_utc(now or self.clock.now())
        sent: list[tuple[str, str]] = []
        for uid in await self.store.active_ids():
            if owns is not None and not owns(uid):
                continue  # another proactive shard owns this user
            st = await self.store.get(uid)
            if st is None:
                await self.store.delete(uid)
                continue
            if st.tier != "high" or st.cancelled or st.released or not st.last_user_at:
                continue
            same_day, morning = self.checkin_times(st)
            if not st.same_day_done and now >= same_day:
                if now >= morning:  # missed the window: skip to the morning one
                    st.same_day_done = True
                elif await self._send(uid, "checkin_same_day", st):
                    st.same_day_done = True
                    sent.append((user_ref(uid), "same_day"))
                await self.store.put(uid, st)
            elif st.same_day_done and not st.morning_done and now >= morning:
                if now >= morning + MORNING_GRACE:
                    st.morning_done = True
                elif not is_quiet_hours(now) and await self._send(uid, "checkin_morning", st):
                    st.morning_done = True
                    sent.append((user_ref(uid), "morning"))
                await self.store.put(uid, st)
        return sent

    async def _send(self, uid: str, key: str, st: CareState) -> bool:
        if self.sender is None:
            return False
        try:
            await self.sender(uid, _ln(st, key, st.lang))
            return True
        except Exception:  # noqa: BLE001 - a failed check-in is retried on the next tick
            log.warning("care: check-in not delivered user=%s", user_ref(uid))
            return False


_RELATIONS = frozenset(
    "mom mother mum mummy maa papa father dad sister brother didi bhai bhaiya behen bahan friend dost "
    "partner wife husband cousin uncle aunt teacher boyfriend girlfriend bf gf colleague "
    "माँ मां मम्मी पापा भाई बहन दीदी दोस्त पति पत्नी सहेली".split()
)
