# ruff: noqa: E501
"""Plumbing: the ``receptionist`` component (None unless the switch or the probe is on).

    InboundCallReceived(redirecting=...)  --CallbackService--> Receptionist.claims -> serve
    WhatsApp button rcp:<id>:<action> / text "what did I miss?" --InboundPipeline--> Receptionist.handle
    morning digest + purge --Runtime--> Receptionist.loop

With FRIDAY_RECEPTIONIST_ENABLED false (default) ``build_receptionist`` returns None unless only the
probe is on (FRIDAY_RECEPTIONIST_PROBE): then it just records the masked webhook keys.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from friday.core.clock import to_ist
from friday.core.logging import get_logger, mask_phone
from friday.core.models import ReplyButton, User
from friday.receptionist import probe as probe_mod
from friday.receptionist.classify import Classifier
from friday.receptionist.identify import RedirectResolver, Resolution, Route, UserRef
from friday.receptionist.service import BUTTON_PREFIX, ReceptionistService
from friday.receptionist.store import ReceptionistStore, SqlReceptionistStore

log = get_logger(__name__)


class RepoDirectory:
    """Redirecting number -> Friday user (phone blind index) with the receptionist on?"""

    def __init__(self, repos: Any, store: ReceptionistStore) -> None:
        self.repos, self.store = repos, store

    async def user_for_phone(self, phone: str) -> UserRef | None:
        user = await self.repos.users.get_by_phone(phone)
        if user is None or getattr(user.status, "value", user.status) not in {"active", "onboarding"}:
            return None
        cfg = await self.store.get_config(user.id)
        return UserRef(user.id, bool(cfg and cfg.enabled))


class LifeCalendar:
    """Today's events from the life-state store (filled by the Google calendar sync)."""

    def __init__(self, life: Any) -> None:
        self.life = life

    async def events_today(self, user_id: str, now: Any) -> list[str]:
        from friday.core.clock import ist_day_bounds  # noqa: PLC0415

        start, end = ist_day_bounds(now)
        evs = await self.life.events_between(user_id, start, end)
        return [f"{to_ist(e.start).strftime('%I:%M %p').lstrip('0')} {e.title}" for e in evs[:6]]


class Receptionist:
    def __init__(self, c: Any, service: ReceptionistService) -> None:
        self.c, self.service = c, service
        self.enabled = True

    def _telephony(self) -> Any:
        try:
            return self.c.get("telephony")
        except Exception:  # noqa: BLE001
            return None

    async def claims(self, event: Any) -> Resolution | None:
        """A forwarded call for a known user (or an unknown redirecting number)? Anything else,
        including a direct call to Friday, stays with the front door."""
        raw = getattr(event, "redirecting", None)
        res = await self.service.claims(raw, getattr(event, "from_phone", None))
        return None if res.route == Route.NOT_FORWARDED else res

    async def serve(self, event: Any, res: Resolution) -> None:
        from friday.liveagent.sarvam_adapter import SarvamLegPort  # noqa: PLC0415

        tel = self._telephony()
        take = getattr(tel, "take_inbound", None)
        ref = getattr(event, "provider_call_id", None)
        leg = take(ref) if callable(take) and ref else None
        if leg is None:
            log.warning("receptionist: no parked leg for call %s", ref)
            return
        caller = getattr(event, "from_phone", None)
        try:
            await self.service.handle_call(SarvamLegPort(leg), caller, getattr(event, "redirecting", None), resolution=res)
        except Exception:  # noqa: BLE001 - the line must never stay open
            log.exception("receptionist call failed (caller %s)", mask_phone(caller))
            with contextlib.suppress(Exception):
                await leg.hangup()

    async def handle(self, user: User, msg: Any) -> bool:
        """WhatsApp: our buttons and "what did I miss?". False -> not ours."""
        bid = getattr(msg, "button_id", None) or ""
        if bid.startswith(BUTTON_PREFIX + ":"):
            out = await self.service.on_button(user.id, bid)
            if out is not None:
                text, buttons = out
                await self.service.send(user.id, text, list(buttons))
                return True
        text = getattr(msg, "text", None) or ""
        return bool(text) and await self.service.handle_text(user.id, text)

    async def loop(self) -> None:  # pragma: no cover - runtime plumbing
        await self.service.loop()


def build_receptionist(c: Any) -> Receptionist | None:
    s = c.settings
    fields = list(s.receptionist_redirect_fields)
    probe = None
    if s.receptionist_probe:
        probe = probe_mod.InboundProbe(fields, Path(s.receptionist_store_dir) / probe_mod.PROBE_FILE)
    # the adapter hook: reads the configured keys (and feeds the probe) even while the switch is off
    probe_mod.configure(fields if (s.receptionist_enabled or probe) else (), probe)
    if not s.receptionist_enabled:
        return None
    repos = c.get("repos")
    store = SqlReceptionistStore(repos.db, c.clock)

    async def send(user_id: str, text: str, buttons: Sequence[ReplyButton]) -> None:
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    from friday.pause import is_paused

    numbers = [n for n in ([s.receptionist_inbound_number] + list(s.friday_numbers)) if n]
    resolver = RedirectResolver(
        RepoDirectory(repos, store), fields=fields, default_cc=s.default_country_code,
        friday_numbers=lambda: numbers,
    )  # fmt: skip
    life = getattr(repos, "life", None)
    svc = ReceptionistService(
        store, Classifier(), send, c.clock, resolver, paused=lambda: is_paused(s),
        per_user_per_day=s.receptionist_per_user_per_day,
        per_caller_per_hour=s.receptionist_per_caller_per_hour,
        max_call_s=float(s.receptionist_max_call_s), snippet_days=s.receptionist_snippet_days,
        calendar=LifeCalendar(life) if life is not None else None,
    )  # fmt: skip
    return Receptionist(c, svc)
