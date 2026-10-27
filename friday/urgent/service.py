# ruff: noqa: E501
"""The urgent-call escalation, end to end (docs/URGENT_ESCALATION.md).

    receptionist classifies a call URGENT
        -> ``open``            one escalation per message (idempotent), timer = alert time + N minutes
        -> WhatsApp alert with [Acknowledge] (the receptionist sends it; ``confirm_alert`` starts the timer)
    ``tick`` (runtime loop, every few seconds)
        -> ``policy.decide``   kill switch, opt-in, own number, quiet hours, stale, daily cap
        -> ``OwnNumberGate``   the real CallGate (allow-list, DNC, caps ...)
        -> claim (persisted BEFORE the dial) -> ring the user's OWN number -> record the result
    stops: Acknowledge / Call back / Ignore / Block on the alert, the user rings Friday, the user
    picks up the escalation call, all calls used, any rule that says no.

Restart safety: every step is a compare-and-set in the store. A crash while ringing leaves
``in_flight``; after a grace period that attempt is recorded as made (result ``unknown``) and the next
one is scheduled by the spacing, so an attempt is never dialled twice and never lost silently.
"""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from friday.core.clock import Clock, ist_day_bounds, to_ist
from friday.core.logging import get_logger, mask_phone
from friday.core.models import ReplyButton
from friday.receptionist.models import QuietHours
from friday.urgent import copy
from friday.urgent.gate import OwnNumberGate
from friday.urgent.models import (
    EscalationState,
    EscStatus,
    Policy,
    RingOutcome,
    RingResult,
    UserEscalationConfig,
)
from friday.urgent.policy import Facts, decide, is_emergency, plan
from friday.urgent.ports import OwnNumberCaller
from friday.urgent.store import EscalationStore

log = get_logger(__name__)

BUTTON_PREFIX = "urg"
INFLIGHT_GRACE_S = 120.0  # an attempt "in flight" longer than this belongs to a crashed process
Sender = Callable[[str, str, list[ReplyButton]], Awaitable[None]]

_ON = re.compile(r"^\W*urgent\s+calls?\s+(on|chalu|start|shuru)\W*$", re.I)
_OFF = re.compile(r"^\W*urgent\s+calls?\s+(off|band|stop)\W*$", re.I)
_MIN = re.compile(r"^\W*urgent\s+calls?\s+(?:after\s+)?(\d{1,3})\s*(?:min|mins|minute|minutes)\W*$", re.I)
_STATUS = re.compile(r"^\W*urgent\s+calls?\s+(status|kya hai)\W*$", re.I)


@dataclass
class Opened:
    state: EscalationState
    created: bool  # False: this message already had an escalation (a replay); send no second alert


class UrgentEscalation:
    def __init__(
        self,
        store: EscalationStore,
        send: Sender,
        caller: OwnNumberCaller,
        clock: Clock,
        *,
        users: Any,  # .get(user_id) -> User | None, .get_by_phone(phone) -> User | None
        gate: OwnNumberGate | None,
        policy: Policy | None = None,
        enabled: Callable[[], bool] = lambda: True,
        paused: Callable[[], bool] = lambda: False,
        rcp_config: Callable[[str], Awaitable[Any]] | None = None,  # -> ReceptionistConfig | None
        tick_s: float = 20.0,
    ) -> None:
        self.store, self.send, self.caller, self.clock = store, send, caller, clock
        self.users, self.gate = users, gate
        self.policy = policy or Policy()
        self.enabled, self.paused, self.rcp_config, self.tick_s = enabled, paused, rcp_config, tick_s

    # ================================================================== opening (from the receptionist)
    async def open(self, user_id: str, message_id: str, reasons: Sequence[str], source: str = "rules") -> Opened | None:
        """Called when the receptionist is about to alert an URGENT call. None: no escalation for this
        user (switch off, paused, not opted in); the receptionist then sends its normal alert."""
        if not self.enabled() or self.paused():
            return None
        cfg = await self.store.get_config(user_id)
        if cfg is None or not cfg.opted_in:
            return None
        p = plan(cfg, self.policy)
        now = self.clock.now()
        st = EscalationState(
            user_id=user_id, message_id=message_id, emergency=is_emergency(list(reasons), source=source),
            wait_s=p.wait_s, max_calls=p.max_calls, spacing_s=p.spacing_s,
            next_action_at=now + timedelta(seconds=p.wait_s), created_at=now,
        )  # fmt: skip
        st, created = await self.store.create(st)
        return Opened(st, created)

    def alert_additions(self, st: EscalationState, lang: str) -> tuple[str, list[ReplyButton]]:
        """(hint line to append to the alert, the Acknowledge button)."""
        minutes = max(1, math.ceil(st.wait_s / 60))
        key = "alert.hint.emergency" if st.emergency else "alert.hint"
        return (
            copy.t(key, lang, minutes=minutes),
            [ReplyButton(id=f"{BUTTON_PREFIX}:{st.id}:ack", title=copy.button_title("ack", lang))],
        )

    async def confirm_alert(self, st: EscalationState, ok: bool) -> None:
        """The alert was sent (or failed): the timer runs from NOW. A failed alert still escalates, from
        the moment of opening: the user has seen nothing, so ringing is the better fallback."""
        now = self.clock.now()
        base = now if ok else (st.created_at or now)
        await self.store.set_alert(
            st.id, ok=ok, sent_at=now if ok else None, next_action_at=base + timedelta(seconds=st.wait_s)
        )

    # ================================================================== stopping
    async def on_button(self, user_id: str, button_id: str) -> tuple[str, list[ReplyButton]] | None:
        """``urg:<escalation id>:ack``. Not ours -> None."""
        parts = (button_id or "").split(":")
        if len(parts) != 3 or parts[0] != BUTTON_PREFIX or parts[2] != "ack":
            return None
        lang = await self._lang(user_id)
        st = await self.store.get(user_id, parts[1])  # another user's id finds nothing
        if st is None:
            return copy.t("reply.stale", lang), []
        if st.status == EscStatus.PENDING:
            await self.store.close(user_id, st.id, EscStatus.ACKED, "ack_button", self.clock.now())
            return copy.t("reply.ack", lang), []
        if st.status == EscStatus.ACKED:
            return copy.t("reply.ack", lang), []  # a double tap
        return copy.t("reply.stale", lang), []

    async def user_acted(self, user_id: str, message_id: str, action: str) -> int:
        """The user used Call back / Ignore / Block on the receptionist alert: they have seen it."""
        return await self.store.close_for_message(user_id, message_id, EscStatus.ACKED, f"button_{action}", self.clock.now())

    async def note_inbound_call(self, from_phone: str | None) -> int:
        """Someone rang a Friday number. If it is a user with a running escalation, they are calling
        back: stop. (Only the user's own number matches; nobody else can stop an escalation.)"""
        if not from_phone:
            return 0
        try:
            user = await self.users.get_by_phone(from_phone)
        except Exception:  # noqa: BLE001 - an odd caller id never breaks call handling
            return 0
        if user is None:
            return 0
        return await self.store.close_open_for_user(user.id, EscStatus.STOPPED, "user_called", self.clock.now())

    # ================================================================== the user's switch (WhatsApp text)
    async def handle_text(self, user: Any, text: str) -> bool:
        t = (text or "").strip()
        if not (_ON.match(t) or _OFF.match(t) or _MIN.match(t) or _STATUS.match(t)):
            return False
        lang = await self._lang(user.id)
        cfg = await self.store.get_config(user.id) or UserEscalationConfig()
        if _ON.match(t):
            if not self.enabled():
                await self.send(user.id, copy.t("optin.unavailable", lang), [])
                return True
            cfg = cfg.model_copy(update={"opted_in": True, "number": user.phone, "language": lang})
            await self.store.save_config(user.id, cfg)
            await self.send(user.id, copy.t("optin.on", lang, minutes=plan(cfg, self.policy).wait_s // 60), [])
        elif _OFF.match(t):
            await self.store.save_config(user.id, cfg.model_copy(update={"opted_in": False}))
            await self.store.close_open_for_user(user.id, EscStatus.CANCELLED, "opted_out", self.clock.now())
            await self.send(user.id, copy.t("optin.off", lang), [])
        elif m := _MIN.match(t):
            cfg = UserEscalationConfig.model_validate({**cfg.model_dump(), "minutes": int(m.group(1))})  # clamped
            await self.store.save_config(user.id, cfg)
            await self.send(user.id, copy.t("optin.minutes", lang, minutes=plan(cfg, self.policy).wait_s // 60), [])
        else:
            if cfg.opted_in:
                p = plan(cfg, self.policy)
                await self.send(user.id, copy.t("optin.status.on", lang, minutes=p.wait_s // 60, calls=p.max_calls), [])
            else:
                await self.send(user.id, copy.t("optin.status.off", lang), [])
        return True

    async def _lang(self, user_id: str) -> str:
        rc = await self._rcp(user_id)
        return "en" if rc is not None and rc.language == "en" else "hinglish"

    async def _rcp(self, user_id: str) -> Any:
        if self.rcp_config is None:
            return None
        try:
            return await self.rcp_config(user_id)
        except Exception:  # noqa: BLE001
            return None

    # ================================================================== the scheduler
    async def tick(self) -> dict[str, int]:
        """One pass over every due escalation. Safe to run on several replicas at once."""
        now = self.clock.now()
        out = {"called": 0, "cancelled": 0, "refused": 0, "recovered": 0, "exhausted": 0, "answered": 0}
        for st in await self.store.due(now):
            try:
                await self._process(st, now, out)
            except Exception:  # noqa: BLE001 - one broken row never stops the others
                log.exception("urgent escalation %s failed", st.id)
        await self.store.purge_finished(now - timedelta(days=self.policy.retention_days))
        return out

    async def _process(self, st: EscalationState, now: datetime, out: dict[str, int]) -> None:
        if st.in_flight:
            await self._recover(st, now, out)
            return
        facts = await self._facts(st, now)
        d = decide(st, now, facts, self.policy)
        if d.action == "wait":
            return
        if d.action in {"cancel", "refuse"}:
            assert d.status is not None
            if await self.store.close(st.user_id, st.id, d.status, d.reason, now):
                out["refused" if d.status == EscStatus.REFUSED else "cancelled" if d.status == EscStatus.CANCELLED else "exhausted"] += 1
                if d.status == EscStatus.EXHAUSTED:
                    await self._say_exhausted(st, st.calls_made)
                log.info("urgent escalation %s closed: %s", st.id, d.reason)
            return
        # ---- a call is due: the CallGate has the last word
        user = await self.users.get(st.user_id)
        cfg = await self.store.get_config(st.user_id)
        number = cfg.number if cfg else None
        assert user is not None and number is not None
        if self.gate is None:
            await self.store.close(st.user_id, st.id, EscStatus.REFUSED, "no_gate", now)
            out["refused"] += 1
            return
        verdict = await self.gate.check(user, number, emergency=st.emergency, now=now)
        if not verdict.allowed:
            reason = ("gate:" + ",".join(verdict.reasons))[:32]
            status = EscStatus.REFUSED if "not_own_number" in verdict.reasons or "test_allowlist" in verdict.reasons else EscStatus.CANCELLED
            await self.store.close(st.user_id, st.id, status, reason, now)
            out["refused" if status == EscStatus.REFUSED else "cancelled"] += 1
            log.info("urgent escalation %s not placed: %s", st.id, reason)
            return
        # ---- persist the attempt BEFORE dialling (restart safe, at most once per attempt number)
        if not await self.store.claim(st.id, st.calls_made, now):
            return  # acknowledged, or another replica took this attempt
        rc = await self._rcp(st.user_id)
        lang = "en" if rc is not None and rc.language == "en" else "hinglish"
        key = "ring.emergency" if st.emergency else "ring.urgent"
        try:
            res = await self.caller.ring(
                user_id=st.user_id, number=number, line_key=key, lang=lang,
                user_name=(rc.user_name if rc is not None else ""), dedupe_key=f"{st.id}:{st.calls_made + 1}",
            )  # fmt: skip
        except Exception as e:  # noqa: BLE001
            log.warning("urgent escalation %s: ring raised %s", st.id, type(e).__name__)
            res = RingOutcome(result=RingResult.FAILED, detail=type(e).__name__)
        out["called"] += 1
        log.info("urgent escalation %s attempt %d to %s: %s", st.id, st.calls_made + 1, mask_phone(number), res.result.value)
        await self._after_ring(st, st.calls_made + 1, res, now, out)

    async def _after_ring(self, st: EscalationState, made: int, res: RingOutcome, now: datetime, out: dict[str, int]) -> None:
        nxt = self.clock.now() + timedelta(seconds=st.spacing_s)
        await self.store.finish_attempt(st.id, result=res.result.value, next_action_at=nxt)
        if res.result == RingResult.ANSWERED:
            if await self.store.close(st.user_id, st.id, EscStatus.ANSWERED, "call_answered", self.clock.now()):
                out["answered"] += 1
        elif res.result == RingResult.REFUSED:
            await self.store.close(st.user_id, st.id, EscStatus.REFUSED, ("ring:" + res.detail)[:32], self.clock.now())
            out["refused"] += 1
        elif made >= st.max_calls and await self.store.close(
            st.user_id, st.id, EscStatus.EXHAUSTED, "no_answer", self.clock.now()
        ):
            out["exhausted"] += 1
            await self._say_exhausted(st, made)

    async def _recover(self, st: EscalationState, now: datetime, out: dict[str, int]) -> None:
        """A row stuck 'in flight' after a crash: count the attempt as made and move on."""
        if st.last_call_at is not None and (now - st.last_call_at).total_seconds() < INFLIGHT_GRACE_S:
            return  # another worker is probably ringing right now
        out["recovered"] += 1
        nxt = (st.last_call_at or now) + timedelta(seconds=st.spacing_s)
        await self.store.finish_attempt(st.id, result=RingResult.UNKNOWN.value, next_action_at=max(nxt, now))
        if st.calls_made >= st.max_calls and await self.store.close(st.user_id, st.id, EscStatus.EXHAUSTED, "crash_recovered", now):
            out["exhausted"] += 1
            await self._say_exhausted(st, st.calls_made)

    async def _say_exhausted(self, st: EscalationState, n: int) -> None:
        if n <= 0:
            return
        try:
            await self.send(st.user_id, copy.t("exhausted", await self._lang(st.user_id), n=n), [])
        except Exception as e:  # noqa: BLE001
            log.warning("urgent escalation: final text failed (%s)", type(e).__name__)

    async def _facts(self, st: EscalationState, now: datetime) -> Facts:
        user = await self.users.get(st.user_id)
        cfg = await self.store.get_config(st.user_id)
        rc = await self._rcp(st.user_id)
        if rc is not None:
            quiet = rc.quiet_hours.contains(to_ist(now).hour)
        else:
            quiet = QuietHours().contains(to_ist(now).hour)
        day_start, _ = ist_day_bounds(now)
        capped = (await self.store.escalations_with_calls_since(st.user_id, day_start)) >= self.policy.daily_cap
        return Facts(
            switch_on=self.enabled(), paused=self.paused(),
            user_active=bool(user is not None and getattr(user.status, "value", user.status) == "active"),
            opted_in=bool(cfg and cfg.opted_in), own_number=getattr(user, "phone", None),
            cfg_number=cfg.number if cfg else None, in_quiet_hours=quiet,
            emergency_in_quiet=bool(cfg.emergency_in_quiet_hours) if cfg else True, daily_capped=capped,
        )  # fmt: skip

    async def loop(self) -> None:  # pragma: no cover - runtime plumbing
        import asyncio

        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("urgent escalation tick failed")
            await asyncio.sleep(self.tick_s)


__all__ = ["BUTTON_PREFIX", "Opened", "UrgentEscalation"]
