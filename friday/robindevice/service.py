"""DeviceService: everything the device API and the family side do, with no HTTP in it.

Per-parent isolation: every method works on one ParentState, found by the device token (never by an id the
client sends). Consent is enforced here: a signal type without its consent item is dropped and counted.
No message/notification/SMS text is ever accepted or stored; the only free text that reaches this layer is
what the parent explicitly shares for a scam check, and that is not stored (only verdict and categories).
"""

from __future__ import annotations

import asyncio
import functools
import secrets
import time
from collections.abc import Callable
from typing import Any

from friday.core.interfaces import LLMClient
from friday.core.logging import get_logger
from friday.robindevice import copy as C
from friday.robindevice import scamcheck
from friday.robindevice.callpattern import CallPatternAnalyzer
from friday.robindevice.engine import MIN, ScenarioEngine, known_predicates
from friday.robindevice.ports import (
    CONSENT_ITEMS,
    AlertPort,
    ConsentPort,
    ParentInfo,
    ParentLookup,
    Sensitivity,
    VoiceIntake,
    VoiceResult,
)
from friday.robindevice.replyaudio import ReplyAudioStore
from friday.robindevice.rules import Rules, load
from friday.robindevice.schemas import (
    SIGNAL_CONSENT,
    AckIn,
    HeartbeatIn,
    PairIn,
    validate_event,
)
from friday.robindevice.store import (
    PAIR_CODE_TTL_S,
    Device,
    DeviceStore,
    DeviceStorePort,
    Event,
    ParentState,
    code_is_strong,
    new_device_token,
    new_pair_code,
    sha256_hex,
)

log = get_logger(__name__)

STALE_FUTURE_MS = 5 * MIN
MAX_BATCH = 100
_INTERNAL_PREFIXES = ("_",)
FOREVER_MS = 4_102_444_800_000
DAY_MS = 86_400_000
EVENT_RETAIN_DAYS = 7  # device events (signals) are kept at most this long (founder-proposed default, a constant for now)


def _persisted(fn: Callable[..., Any]) -> Callable[..., Any]:
    """After the operation, write the touched parent back to the store (a no-op for the in-memory store).
    The first argument after ``self`` is the ``ParentState`` or the parent id."""

    @functools.wraps(fn)
    async def wrapper(self: DeviceService, who: Any, *a: Any, **k: Any) -> Any:
        try:
            return await fn(self, who, *a, **k)
        finally:
            await self.store.save(who if isinstance(who, str) else who.parent_id)

    return wrapper

# What the "what my son sees" screen lists as collected (static, shown next to the live counters).
COLLECTED = [
    "unknown call started/ended: number class, duration, a one-way hash of the number (made on your phone)",
    "camera in use: on/off times only (no picture, no app name)",
    "remote-control app opened/installed: which one from a fixed list",
    "bank/UPI app brought to the front: which one from a fixed list",
    "payment notification: app, debit/credit, amount, payee kind (new/known/merchant). Never the message text",
    "phone seen: time of last contact and whether the battery was low",
]
NEVER = ["messages or SMS", "call recordings or audio", "contacts or names", "your screen", "the call log"]


class DeviceService:
    def __init__(
        self,
        *,
        alerts: AlertPort,
        consent: ConsentPort,
        parents: ParentLookup,
        rules: Rules | None = None,
        store: DeviceStorePort | None = None,
        now_ms: Callable[[], int] | None = None,
        llm: LLMClient | None = None,
        brand: str = "Friday",
        call_text_retain_days: int = 0,
        voice: VoiceIntake | None = None,
        reply_audio: ReplyAudioStore | None = None,
        public_base_url: str = "",
    ) -> None:
        self.voice = voice
        self.reply_audio = reply_audio  # None = replies are text only
        self.public_base_url = public_base_url.rstrip("/")
        self.alerts, self.consent, self.parents = alerts, consent, parents
        self.rules = rules or load(known_predicates=known_predicates())
        self.store: DeviceStorePort = store or DeviceStore()
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.llm = llm
        self.brand = brand
        self.call_text_retain_days = call_text_retain_days
        self.engine = ScenarioEngine(self.rules, alerts, consent, parents, brand=brand)
        self._locks: dict[str, asyncio.Lock] = {}
        self._analyzers: dict[tuple[str, str], CallPatternAnalyzer] = {}
        self._analyzer_ms: dict[tuple[str, str], int] = {}  # when each analyzer was created (retention)

    def _lock(self, parent_id: str) -> asyncio.Lock:
        return self._locks.setdefault(parent_id, asyncio.Lock())

    # ------------------------------------------------------------------ pairing / auth
    async def create_pairing_code(self, parent_id: str) -> str:
        """Called by the family side (the child sets the parent up). 8 chars, 15 minutes, single use."""
        if await self.parents.get(parent_id) is None:
            raise KeyError("unknown parent")
        await self.store.ensure_loaded()
        code = new_pair_code()
        if not code_is_strong(code):  # cannot happen with new_pair_code; guards a future change
            raise ValueError("weak pairing code")
        await self.store.put_code(parent_id, code, self.now_ms() + PAIR_CODE_TTL_S * 1000)
        return code

    async def pair(self, body: PairIn) -> dict[str, Any] | None:
        now = self.now_ms()
        await self.store.ensure_loaded()
        if not code_is_strong(body.code):  # no real code looks like this: a bad guess, never looked up
            return None
        parent_id = await self.store.take_code(body.code, now)
        if parent_id is None:
            return None
        info = await self.parents.get(parent_id)
        if info is None:
            return None
        st = self.store.state(parent_id)
        if st.device is not None:  # one device per parent: a new phone replaces the old one
            self.store.unbind_token(st.device.token_hash)
        token = new_device_token()
        th = sha256_hex(token)
        st.device = Device(token_hash=th, paired_ms=now, last_seen_ms=now, app_version=body.app_version, os_sdk=body.os_sdk)
        if st.shadow_start_ms is None:
            st.shadow_start_ms = now
        st.paused_until_ms = 0
        self.store.bind_token(parent_id, th)
        await self.store.save(parent_id)
        return {
            "device_token": token,
            "parent_id": parent_id,
            "language": info.language,
            "brand": self.brand,
            "consent_items": list(CONSENT_ITEMS),
            "server_time_ms": now,
            "limits": {"max_batch": MAX_BATCH, "max_body_bytes": 65_536},
        }

    async def authenticate(self, token: str) -> ParentState | None:
        st = await self.store.parent_for_token(token)
        return st if st is not None and st.device is not None else None

    async def revoke(self, parent_id: str) -> bool:
        await self.store.ensure_loaded()
        st = self.store.peek(parent_id)
        if st is None or st.device is None:
            return False
        self.store.unbind_token(st.device.token_hash)
        st.device = None
        await self.store.save(parent_id)
        return True

    # ------------------------------------------------------------------ preferences (family side)
    def set_policy(
        self,
        parent_id: str,
        *,
        sensitivity: Sensitivity | None = None,
        payment_threshold_paise: int | None = None,
        shadow_days: int | None = None,
        support_window_minutes: int | None = None,
    ) -> None:
        st = self.store.state(parent_id)
        if sensitivity is not None:
            if sensitivity not in self.rules.sensitivity:
                raise ValueError("bad sensitivity")
            st.sensitivity = sensitivity
        if payment_threshold_paise is not None:
            if payment_threshold_paise < 100:
                raise ValueError("threshold too small")
            st.payment_threshold_paise = payment_threshold_paise
        if shadow_days is not None:
            if not 0 <= shadow_days <= 60:
                raise ValueError("bad shadow_days")
            st.shadow_days = shadow_days
        if support_window_minutes is not None:
            st.support_window_until_ms = self.now_ms() + max(0, support_window_minutes) * MIN
        self.store.touch(parent_id)  # written by the next save (needs a loaded store: after the first async call)

    def note_external(self, parent_id: str, name: str) -> None:
        """A fact from the family package, e.g. 'checkin_unanswered'."""
        self.store.state(parent_id).external[name] = self.now_ms()
        self.store.touch(parent_id)

    # ------------------------------------------------------------------ heartbeat
    @_persisted
    async def heartbeat(self, st: ParentState, body: HeartbeatIn) -> dict[str, Any]:
        now = self.now_ms()
        dev = st.device
        assert dev is not None
        gap_ms = now - dev.last_seen_ms
        dev.last_seen_ms = now
        dev.app_version, dev.os_sdk = body.app_version, body.os_sdk
        dev.roles = body.roles.model_dump()
        dev.battery_low = body.battery_low
        st.bump("heartbeats")
        async with self._lock(st.parent_id):
            if st.s7_open and gap_ms > 30 * MIN:
                st.s7_open = False
                st.fired.pop("S7", None)
                await self._tell_child(st, "INFO", "S7", "phone is active again", {})
            await self._run(st)
        return await self._state_reply(st)

    async def _state_reply(self, st: ParentState) -> dict[str, Any]:
        now = self.now_ms()
        return {
            "server_time_ms": now,
            "paused": st.paused_until_ms > now,
            "consent": await self._consent_map(st.parent_id),
            "prompts": await self.pending_prompts(st),
        }

    # ------------------------------------------------------------------ signals
    @_persisted
    async def ingest(self, st: ParentState, raw_events: list[Any]) -> dict[str, Any]:
        now = self.now_ms()
        if st.device:
            st.device.last_seen_ms = now
        out = {"accepted": 0, "duplicates": 0, "dropped_no_consent": 0, "dropped_paused": 0, "stale": 0,
               "invalid": 0, "invalid_detail": []}
        paused = st.paused_until_ms > now
        consent_cache: dict[str, bool] = {}
        retention_ms = int(self.rules.defaults.get("retention_h", 48)) * 3_600_000
        async with self._lock(st.parent_id):
            for i, raw in enumerate(raw_events[:MAX_BATCH]):
                ev, reason = validate_event(raw)
                if ev is None:
                    out["invalid"] += 1
                    out["invalid_detail"].append({"index": i, "reason": reason})
                    st.bump("invalid")
                    continue
                if paused:
                    out["dropped_paused"] += 1
                    st.bump("dropped_paused")
                    continue
                item = SIGNAL_CONSENT[ev.type]
                if item not in consent_cache:
                    consent_cache[item] = await self.consent.has(st.parent_id, item)
                if not consent_cache[item]:
                    out["dropped_no_consent"] += 1
                    st.bump(f"dropped_no_consent:{ev.type}")
                    continue
                if ev.ts_ms > now + STALE_FUTURE_MS or ev.ts_ms < now - retention_ms:
                    out["stale"] += 1
                    st.bump("stale")
                    continue
                if not st.remember_id(ev.id):
                    out["duplicates"] += 1
                    continue
                data = ev.model_dump(exclude={"id", "type", "ts_ms"})
                st.events.append(Event(ev.id, ev.type, ev.ts_ms, data))
                st.bump(f"accepted:{ev.type}")
                out["accepted"] += 1
            del st.events[:-2000]
            if out["accepted"]:
                await self._run(st)
        out["prompts"] = await self.pending_prompts(st)
        return out

    async def _run(self, st: ParentState) -> Any:
        info = await self.parents.get(st.parent_id)
        return await self.engine.run(st, self.now_ms(), info)

    async def sweep(self) -> int:
        """Periodic tick (``RobinHub.tick`` calls it): time-based scenarios (S7 unreachable, S8 season)."""
        n = 0
        await self.store.ensure_loaded()
        try:
            await self.retention()
        except Exception:  # noqa: BLE001 - retention never stops the safety scenarios
            log.exception("robin device: retention failed")
        for pid in self.store.parent_ids():
            async with self._lock(pid):
                st = await self.store.refresh(pid)  # another process may have fired already: never alert twice
                if st is None or st.device is None:
                    continue
                try:
                    res = await self._run(st)
                    n += res.alerts
                finally:
                    await self.store.save(pid)
        await self.store.save_dirty()
        return n

    # ------------------------------------------------------------------ call transcripts (family package)
    @_persisted
    async def feed_call_turn(
        self, parent_id: str, call_id: str, speaker: str, text: str, t: float = 0.0,
        context: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Score one transcript turn. The text is scored and dropped; only cues/tier/time are kept."""
        await self.store.ensure_loaded()
        st = self.store.state(parent_id)
        if not await self.consent.has(parent_id, "call_pattern"):
            st.bump("dropped_no_consent:call_pattern")
            return {"dropped": "no_consent"}
        key = (parent_id, call_id)
        an = self._analyzers.get(key)
        if an is None:
            an = self._analyzers[key] = CallPatternAnalyzer(context=context, retain_days=self.call_text_retain_days)
            self._analyzer_ms[key] = self.now_ms()
        state = await an.turn_with_llm(speaker, text, t, self.llm)
        now = self.now_ms()
        async with self._lock(parent_id):
            st.events = [e for e in st.events if not (e.type == "call_pattern" and e.data.get("call_id") == call_id)]
            if state.tier != "NONE":
                st.events.append(Event(f"cp-{secrets.token_hex(4)}", "call_pattern", now,
                                       {"call_id": call_id, "tier": state.tier, "score": state.score,
                                        "cue_ids": [c.id for c in state.cues]}))
                await self._run(st)
        return state.summary()

    def finish_call(self, parent_id: str, call_id: str) -> dict[str, Any] | None:
        self._analyzer_ms.pop((parent_id, call_id), None)
        an = self._analyzers.pop((parent_id, call_id), None)
        return an.finish(self.now_ms()) if an else None

    # ------------------------------------------------------------------ share intake
    @_persisted
    async def share(self, st: ParentState, kind: str, value: str) -> dict[str, Any]:
        if not await self.consent.has(st.parent_id, "share_check"):
            st.bump("dropped_no_consent:share")
            return {"error": "no_consent"}
        info = await self.parents.get(st.parent_id)
        lang = info.language if info else "hinglish"
        if kind == "screenshot_ref" and not scamcheck.re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value):
            return {"error": "bad_reference"}
        res = await scamcheck.check(kind, value, lang=lang, llm=self.llm)
        st.bump(f"share:{res.verdict}")
        told = False
        if res.alert_child and await self.consent.has(st.parent_id, "share_alert_child"):
            now = self.now_ms()
            cat = res.categories[0] if res.categories else "unknown"
            key = f"SHARE:{kind}:{cat}"
            rec = st.fired.get(key)
            if rec is None or now - rec.ts_ms > 10 * MIN:
                from friday.robindevice.store import Fired

                st.fired[key] = Fired(rank=2, ts_ms=now, shadow=False)
                tier = "HIGH" if res.verdict == "SCAM_LIKELY" else "WATCH"
                why = f"parent shared a {kind} that looks risky ({cat.replace('_', ' ')})"
                await self._tell_child(st, tier, "SHARE", why,
                                       {"kind": kind, "verdict": res.verdict, "categories": res.categories})
                told = True
        return {**res.to_dict(), "child_told": told}

    # ------------------------------------------------------------------ SOS and voice (always allowed)
    @_persisted
    async def sos(self, st: ParentState, location: Any = None) -> dict[str, Any]:
        """Works when paused or stopped, in the learning week, and without any consent item."""
        info = await self.parents.get(st.parent_id)
        lang = info.language if info else "hinglish"
        details: dict[str, Any] = {}
        if location is not None:
            if await self.consent.has(st.parent_id, "location"):
                details["location"] = {"lat": location.lat, "lon": location.lon}
            else:
                st.bump("dropped_no_consent:location")
        await self._tell_child(st, "EMERGENCY", "SOS", "SOS button pressed", details)
        st.bump("sos")
        return {"ok": True, "message": C.pick(C.PROMPTS, "sos_ack", lang)}

    @_persisted
    async def voice_message(self, st: ParentState, audio: bytes, mime: str, duration_s: int) -> dict[str, Any]:
        """The press-to-talk button. Explicit parent action, so it also works while paused. Audio is passed to
        the family-side intake (speech-to-text, then deleted) and never stored here."""
        if self.voice is None:
            return {"error": "voice_not_available"}
        if not await self.consent.has(st.parent_id, "voice_messages"):
            st.bump("dropped_no_consent:voice")
            return {"error": "no_consent"}
        try:
            res: VoiceResult = await self.voice.handle(st.parent_id, audio, mime, duration_s)
        finally:
            del audio
        st.bump("voice_messages")
        url: str | None = None
        if res.reply_audio and self.reply_audio is not None and self.public_base_url:
            token = self.reply_audio.put(st.parent_id, res.reply_audio, res.reply_audio_mime)
            url = f"{self.public_base_url}/robin/device/audio/{token}" if token else None
        return {"accepted": res.ok, "reply_text": res.reply_text, "reply_audio_url": url}

    # ------------------------------------------------------------------ acks
    @_persisted
    async def ack(self, st: ParentState, body: AckIn) -> dict[str, Any]:
        now = self.now_ms()
        info = await self.parents.get(st.parent_id)
        lang = info.language if info else "hinglish"
        if body.kind == "sos":
            return await self.sos(st, body.location)
        if body.kind == "i_am_ok":
            st.s7_open = False
            st.fired.pop("S7", None)
            await self._tell_child(st, "INFO", "ACK", "parent tapped I am OK", {})
            return {"ok": True, "message": C.pick(C.PROMPTS, "ok_ack", lang)}
        prompt = st.prompts.get(body.prompt_id or "")
        if body.prompt_id and prompt is None:
            return {"error": "unknown_prompt"}
        if prompt is None:
            return {"ok": True}
        if body.kind == "dismissed":
            prompt.state = "dismissed"
            return {"ok": True}
        if body.kind == "call_son_tapped":
            st.bump("call_child_tapped")
            return {"ok": True}
        # this_was_fine
        prompt.state = "acked"
        sc = self.rules.get(prompt.scenario)
        rec = st.fired.get(prompt.incident)
        until = now + max(sc.cooldown_min, 60) * MIN
        if rec is not None:
            rec.resolved_until_ms = until
        if sc.suppressible:
            if prompt.call_hash:
                st.trusted.add(prompt.call_hash)
            st.fine_counts[prompt.pattern] = st.fine_counts.get(prompt.pattern, 0) + 1
        st.bump(f"fine:{prompt.scenario}")
        await self._tell_child(st, "INFO", prompt.scenario, "parent says this was fine", {"resolved": True})
        return {"ok": True, "message": C.pick(C.PROMPTS, "fine_ack", lang)}

    # ------------------------------------------------------------------ consent
    async def _consent_map(self, parent_id: str) -> dict[str, bool]:
        return {i: await self.consent.has(parent_id, i) for i in CONSENT_ITEMS}

    @_persisted
    async def sync_consent(self, st: ParentState, items: dict[str, bool]) -> dict[str, Any]:
        """From the PARENT'S device: it may only WITHDRAW. Consent is given by the family admin on the parent's
        behalf (consent_basis 'admin_on_behalf'); a grant attempt from the phone is refused."""
        bad = [k for k in items if k not in CONSENT_ITEMS]
        if bad:
            raise ValueError("unknown consent item")
        if any(items.values()):
            raise PermissionError("consent is given by your family admin, not from the phone")
        await self._withdraw(st, [k for k, g in items.items() if not g])
        return await self.consent_view(st)

    async def _withdraw(self, st: ParentState, names: list[str]) -> None:
        async with self._lock(st.parent_id):
            for item in names:
                await self.consent.set(st.parent_id, item, False, "parent_device")
                types = {t for t, i in SIGNAL_CONSENT.items() if i == item}
                if item == "call_pattern":
                    types.add("call_pattern")
                st.events = [e for e in st.events if e.type not in types]  # withdrawal erases what it allowed
            st.bump("consent_withdrawn", len(names))

    @_persisted
    async def admin_set_consent(self, parent_id: str, items: dict[str, bool]) -> None:
        """Family side (the child, admin_on_behalf). The parent is told by the family package on WhatsApp."""
        bad = [k for k in items if k not in CONSENT_ITEMS]
        if bad:
            raise ValueError("unknown consent item")
        await self.store.ensure_loaded()
        st = self.store.state(parent_id)
        for item, granted in items.items():
            if granted:
                await self.consent.set(parent_id, item, True, "admin_on_behalf")
        await self._withdraw(st, [k for k, g in items.items() if not g])

    async def consent_view(self, st: ParentState) -> dict[str, Any]:
        return {"consent_basis": st.consent_basis, "items": await self._consent_map(st.parent_id)}

    # ------------------------------------------------------------------ pause / erase
    @_persisted
    async def pause(self, st: ParentState, minutes: int) -> dict[str, Any]:
        now = self.now_ms()
        st.paused_until_ms = now + minutes * MIN
        await self._tell_child(st, "INFO", "PAUSE", f"parent paused monitoring for {minutes} minutes", {"minutes": minutes})
        return {"paused": True, "until_ms": st.paused_until_ms}

    @_persisted
    async def stop(self, st: ParentState) -> dict[str, Any]:
        """The parent's STOP: every sensitive signal type is dropped until the PARENT resumes. SOS and the
        voice button keep working. There is no family-side resume on purpose."""
        st.stopped = True
        st.paused_until_ms = FOREVER_MS
        await self._tell_child(st, "WATCH", "STOP", "parent stopped Robin from the phone", {})
        return {"stopped": True, "paused": True}

    @_persisted
    async def resume(self, st: ParentState) -> dict[str, Any]:
        was = st.paused_until_ms > self.now_ms()
        st.paused_until_ms = 0
        st.stopped = False
        if was:
            await self._tell_child(st, "INFO", "PAUSE", "parent resumed monitoring", {})
        return {"paused": False}

    async def erase(self, st: ParentState) -> dict[str, Any]:
        """The PARENT erases what is stored about their phone (device API). The child is told once."""
        n_events = len(st.events)
        pid = st.parent_id
        await self._tell_child(st, "INFO", "ERASE", "parent erased the data stored about this phone", {})
        await self.erase_parent(pid)
        return {"erased": True, "events_deleted": n_events}

    async def erase_parent(self, parent_id: str) -> dict[str, int]:
        """Drop everything held for one parent: the DB rows (state + pairing codes), the token cache and the live
        in-memory analyzers. Called by 'delete everything' (family side, through the erase-hook registry) and by ``erase``.
        Silent (the family side tells the child); idempotent. The device token stops authenticating at once."""
        await self.store.ensure_loaded()
        st = self.store.peek(parent_id)
        n_events = len(st.events) if st else 0
        n_analyzers = 0
        for key in [k for k in self._analyzers if k[0] == parent_id]:
            del self._analyzers[key]
            self._analyzer_ms.pop(key, None)
            n_analyzers += 1
        await self.store.drop(parent_id)  # rows, codes, token binding, cached state
        if self.reply_audio is not None:
            self.reply_audio.drop_parent(parent_id)
        self._locks.pop(parent_id, None)
        return {"events": n_events, "analyzers": n_analyzers, "state": 1 if st else 0}

    # ------------------------------------------------------------------ retention (called from sweep, i.e. from the Robin scheduler)
    async def retention(self) -> int:
        """Device events older than ``EVENT_RETAIN_DAYS`` (7), call-pattern cues older than ``call_text_retain_days`` (1 day
        when that is 0, they are only needed during and just after the call), and retained call text in live analyzers. Returns rows dropped."""
        now = self.now_ms()
        n = 0
        events_cut = now - EVENT_RETAIN_DAYS * DAY_MS
        cues_cut = now - max(self.call_text_retain_days, 1) * DAY_MS
        await self.store.ensure_loaded()
        for pid in self.store.parent_ids():
            st = self.store.peek(pid)
            if st is None:
                continue
            keep = [e for e in st.events if e.ts_ms >= (cues_cut if e.type == "call_pattern" else events_cut)]
            if len(keep) != len(st.events):
                n += len(st.events) - len(keep)
                st.events = keep
                await self.store.save(pid)
        for key, born in list(self._analyzer_ms.items()):  # an abandoned call never finished: drop its analyzer and any kept text
            if born < cues_cut and key in self._analyzers:
                del self._analyzers[key]
                n += 1
            if key not in self._analyzers:
                self._analyzer_ms.pop(key, None)
        for an in self._analyzers.values():
            an.purge(now)
        return n

    # ------------------------------------------------------------------ reads
    async def pending_prompts(self, st: ParentState) -> list[dict[str, Any]]:
        now = self.now_ms()
        info = await self.parents.get(st.parent_id)
        lang = info.language if info else "hinglish"
        out = []
        for p in st.prompts.values():
            if p.state == "open" and p.not_before_ms <= now < p.expires_ms:
                out.append(self.engine.payload(p, lang))
        return out

    async def transparency(self, st: ParentState) -> dict[str, Any]:
        """The 'what my son sees' screen: exactly what was counted and exactly what the child was told."""
        now = self.now_ms()
        shadow = self.engine.in_shadow(st, now)
        days_left = 0
        if shadow and st.shadow_start_ms is not None:
            days_left = max(0, int((st.shadow_start_ms + self.engine.shadow_days(st) * 86_400_000 - now) // 86_400_000) + 1)
        return {
            "collected": COLLECTED,
            "never_collected": NEVER,
            "counters": dict(sorted(st.counters.items())),
            "told_child": st.audit[-20:],
            "paused": st.paused_until_ms > now,
            "consent": await self._consent_map(st.parent_id),
            "learning_mode": {"active": shadow, "days_left": days_left,
                              "meaning": "During learning mode nothing is sent to your family; Robin only checks its own accuracy."},
            "status": C.STATUS,
        }

    def shadow_report(self, parent_id: str) -> dict[str, Any]:
        """The counter report for the shadow week (family/ops side)."""
        st = self.store.peek(parent_id)
        if st is None:
            return {}
        now = self.now_ms()
        per: dict[str, dict[str, int]] = {}
        for k, v in st.counters.items():
            if k.startswith("shadow:S"):
                _, sid, tier = k.split(":")
                per.setdefault(sid, {})[tier] = v
        return {
            "active": self.engine.in_shadow(st, now),
            "shadow_days": self.engine.shadow_days(st),
            "per_scenario": per,
            "would_alert_child": st.counters.get("shadow:would_alert_child", 0),
            "would_nudge": st.counters.get("shadow:would_nudge", 0),
            "would_nudge_ceiling_blocked": st.counters.get("shadow:would_nudge_ceiling_blocked", 0),
            "skipped": {k.split(":", 1)[1]: v for k, v in st.counters.items() if k.startswith("skipped:")},
            "accepted": {k.split(":", 1)[1]: v for k, v in st.counters.items() if k.startswith("accepted:")},
            "dropped_no_consent": {k.split(":", 1)[1]: v for k, v in st.counters.items() if k.startswith("dropped_no_consent:")},
            "fine_acks": {k.split(":", 1)[1]: v for k, v in st.counters.items() if k.startswith("fine:")},
            "rules_version": self.rules.version,
            "rules_unverified": self.rules.unverified,
        }

    # ------------------------------------------------------------------ child alerts
    async def _tell_child(self, st: ParentState, tier: str, scenario: str, why: str, details: dict[str, Any]) -> None:
        await self.alerts.raise_alert(st.parent_id, tier, scenario, why, details)
        st.record_audit({"ts_ms": self.now_ms(), "tier": tier, "scenario": scenario, "why": why, "details": details})


__all__ = ["DeviceService", "ParentInfo"]
