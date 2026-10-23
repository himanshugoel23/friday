# ruff: noqa: E501
"""The user flow for "order / book X" through the private browser. Default OFF.

request -> (one ack) -> clarifying question if needed -> APPROVAL card (exact items, merchant,
address, price ceiling) -> run -> checkpoints that need the user (login code on the secure one-time
page; payment by QR in the user's own UPI app) -> ONE final summary. Between the ack and the
outcome the user hears only questions. Task state is a small JSON model (no secrets), saved after
every phase, so a task survives a restart (``resume``).

The chatbot does NOT import this file's internals: it uses the ``BrowserRequestHandler`` protocol and
``register_browser_handler`` / ``get_browser_handler`` (wiring in docs/PRIVATE_BROWSER_FLOWS.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from friday.connectors.browser.port import BrowserError, BrowserSession
from friday.connectors.contract import (
    ConnectorError,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    format_rupees,
)
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.registry import ConnectorRegistry, Status
from friday.connectors.scrub import scrub_text
from friday.connectors.sites.adapters import (
    ADAPTERS,
    ExecResult,
    Profile,
    Proposal,
    RunCtx,
    norm,
)
from friday.connectors.sites.copy import render
from friday.connectors.sites.errors import SiteBlocked, UnsafeAction, VerifyFailed
from friday.connectors.sites.planner import Planner, RulePlanner
from friday.connectors.sites.summariser import Facts, summarise

ENABLE_ENV = "FRIDAY_BROWSER_ENABLED"
YES = {"yes", "y", "haan", "han", "ha", "ok", "okay", "theek hai", "kar do", "go ahead", "karo"}
NO = {"no", "n", "nahi", "nahin", "cancel", "stop", "ruko", "rehne do", "mat karo"}
PAID = {"paid", "done", "pay kar diya", "ho gaya", "kar diya", "payment done"}
QUESTION_KEY = {"items": "q_food_items", "restaurant": "q_food_restaurant", "address": "q_address",
                "title": "q_movie_title", "seats": "q_movie_seats", "time": "q_movie_time",
                "area": "q_movie_area"}


def browser_enabled(env: Mapping[str, str] | None = None) -> bool:
    raw = (env if env is not None else os.environ).get(ENABLE_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------ messages and ports
class Outgoing(BaseModel):
    user_id: str
    kind: str  # ack | question | approval | login | payment | outcome
    text: str
    buttons: list[tuple[str, str]] = []  # (button id, title <= 20 chars)
    image_png: bytes | None = Field(default=None, repr=False)


Send = Callable[[Outgoing], Awaitable[None]]
ProfileLookup = Callable[[str], Profile]
LinkFactory = Callable[[str], str]  # task_id -> secure one-time page URL (token inside)


class SessionProvider(Protocol):
    """Adapts Developer A's SessionManager: a per-task isolated browser session."""

    async def open(self, user_id: str, task_id: str, site: str) -> BrowserSession: ...

    async def close(self, task_id: str) -> None: ...


class BrowserRequestHandler(Protocol):
    """What the chatbot sees. Every method returns True when the flow consumed the event."""

    def enabled(self) -> bool: ...

    def matches(self, text: str) -> bool: ...

    async def handle_text(self, user_id: str, text: str, lang: str = "en") -> bool: ...

    async def handle_button(self, user_id: str, button_id: str) -> bool: ...

    async def handle_event(self, user_id: str, event: str) -> bool:
        """event: "login_code_ready" (the secure page stored a code) | "paid"."""
        ...


_HANDLER: BrowserRequestHandler | None = None


def register_browser_handler(handler: BrowserRequestHandler | None) -> None:
    global _HANDLER
    _HANDLER = handler


def get_browser_handler() -> BrowserRequestHandler | None:
    return _HANDLER


# ------------------------------------------------------------------ task state
class Phase(StrEnum):
    clarify = "clarify"
    await_approval = "await_approval"
    running = "running"
    await_login = "await_login"
    await_payment = "await_payment"
    done = "done"
    cancelled = "cancelled"
    failed = "failed"


TERMINAL = {Phase.done, Phase.cancelled, Phase.failed}


class TaskState(BaseModel):
    task_id: str
    user_id: str
    lang: str = "en"
    connector: str
    phase: Phase = Phase.clarify
    slots: dict[str, Any] = {}
    pending_slot: str | None = None
    proposal: Proposal | None = None
    reapprovals: int = 0
    pay: dict[str, Any] = {}  # amount, merchant, upi_link, order_ref (no QR bytes, no secrets)
    notes: dict[str, bool] = {}
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskStore(Protocol):
    def save(self, st: TaskState) -> None: ...

    def active(self, user_id: str) -> TaskState | None: ...


class MemoryTaskStore:
    def __init__(self) -> None:
        self._d: dict[str, TaskState] = {}

    def save(self, st: TaskState) -> None:
        self._d[st.task_id] = st.model_copy(deep=True)

    def active(self, user_id: str) -> TaskState | None:
        for st in self._d.values():
            if st.user_id == user_id and st.phase not in TERMINAL:
                return st.model_copy(deep=True)
        return None


class JsonTaskStore(MemoryTaskStore):
    """Same, mirrored to one JSON file so tasks survive a restart. Holds no secrets."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        if path.exists():
            for raw in json.loads(path.read_text()).values():
                st = TaskState.model_validate(raw)
                self._d[st.task_id] = st

    def save(self, st: TaskState) -> None:
        super().save(st)
        self._path.write_text(json.dumps({k: json.loads(v.model_dump_json())
                                          for k, v in self._d.items()}))


def _quick(text: str) -> str | None:
    from friday.connectors.sites import planner as pl

    t = text or ""
    if pl._MOVIE.search(t) and re.search(r"(?i)\b(book|ticket|tickets|seats?|movie|film)\b", t):
        return "bookmyshow.movie"
    if pl._FOOD.search(t) and re.search(r"(?i)\b(order|mangao|mangwao|mangwa)\b", t):
        return "zomato.food"
    return None


# ------------------------------------------------------------------ the flow
class BrowserFlow:
    def __init__(
        self,
        *,
        send: Send,
        registry: ConnectorRegistry,
        sessions: SessionProvider,
        otp: OneTimeOtpChannel,
        profile: ProfileLookup,
        login_link: LinkFactory,
        base_urls: Mapping[str, str],
        planner: Planner | None = None,
        store: TaskStore | None = None,
        repairer: Any = None,
        enabled: Callable[[], bool] = browser_enabled,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        adapters: Mapping[str, Any] = ADAPTERS,
        otp_wait_s: float = 120.0,
        poll_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._send, self._reg, self._sessions, self._otp = send, registry, sessions, otp
        self._profile, self._link, self._urls = profile, login_link, dict(base_urls)
        self._planner, self._store = planner or RulePlanner(), store or MemoryTaskStore()
        self._repairer, self._enabled, self._now = repairer, enabled, now
        self._adapters = dict(adapters)
        self._otp_wait_s, self._poll_s, self._sleep = otp_wait_s, poll_s, sleep
        self._rt: dict[str, Any] = {}  # task_id -> adapter (live browser objects, not persisted)
        self._bg: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    # ---- protocol surface
    def enabled(self) -> bool:
        return self._enabled()

    def matches(self, text: str) -> bool:
        return self.enabled() and _quick(text) is not None

    async def idle(self) -> None:
        while self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)

    async def handle_text(self, user_id: str, text: str, lang: str = "en") -> bool:
        if not self.enabled():
            return False
        st = self._store.active(user_id)
        if st is not None:
            return await self._on_text(st, text)
        if _quick(text) is None:
            return False
        await self._start(user_id, text, lang)
        return True

    async def handle_button(self, user_id: str, button_id: str) -> bool:
        if not self.enabled() or not button_id.startswith("bf:"):
            return False
        _, action, task_id = (button_id.split(":", 2) + ["", ""])[:3]
        st = self._store.active(user_id)
        if st is None or st.task_id != task_id:
            return True  # stale button: ignore quietly
        if action == "yes":
            await self._approve(st)
        elif action == "no":
            await self._cancel(st)
        elif action == "retry":
            await self._retry(st)
        elif action == "paid":
            await self._paid(st)
        return True

    async def handle_event(self, user_id: str, event: str) -> bool:
        st = self._store.active(user_id) if self.enabled() else None
        if st is None:
            return False
        if event == "paid" and st.phase == Phase.await_payment:
            await self._paid(st)
        # "login_code_ready": the running connector is polling the channel; nothing to do
        return True

    async def resume(self, user_id: str) -> bool:
        """After a restart: bring the user's active task back to a state it can continue from."""
        st = self._store.active(user_id)
        if st is None or not self.enabled():
            return False
        if st.phase == Phase.clarify and st.pending_slot:
            await self._ask(st, st.pending_slot)
        elif st.phase == Phase.await_approval:
            await self._show_approval(st)
        elif st.phase in {Phase.running, Phase.await_login}:
            await self._retry(st)
        elif st.phase == Phase.await_payment:
            await self._out(st, "payment", render("payment_ready", st.lang,
                            amount=format_rupees(st.pay.get("amount", 0)),
                            merchant=st.pay.get("merchant", ""),
                            link_part=render("link_part", st.lang, link=st.pay["upi_link"])
                            if st.pay.get("upi_link") else ""),
                            [(f"bf:paid:{st.task_id}", render("btn_paid", st.lang))])
        return True

    # ---- helpers
    async def _out(self, st: TaskState, kind: str, text: str,
                   buttons: list[tuple[str, str]] | None = None, png: bytes | None = None) -> None:
        await self._send(Outgoing(user_id=st.user_id, kind=kind, text=scrub_text(text),
                                  buttons=buttons or [], image_png=png))

    def _save(self, st: TaskState, phase: Phase | None = None) -> None:
        if phase:
            st.phase = phase
        self._store.save(st)

    def _lock(self, task_id: str) -> asyncio.Lock:
        return self._locks.setdefault(task_id, asyncio.Lock())

    def _spawn(self, coro: Awaitable[None]) -> None:
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ---- start / clarify
    async def _start(self, user_id: str, text: str, lang: str) -> None:
        plan = await self._planner.plan(text)
        if plan.connector is None:
            return
        task_id = f"bf-{int(self._now().timestamp() * 1000)}-{abs(hash(user_id)) % 10_000}"
        st = TaskState(task_id=task_id, user_id=user_id, lang=lang if lang in {"en", "hi"} else "en",
                       connector=plan.connector, slots=dict(plan.slots))
        self._save(st)
        await self._out(st, "ack", render("ack", st.lang))  # the ONE acknowledgement
        await self._next(st)

    def _missing(self, st: TaskState) -> str | None:
        prof = self._profile(st.user_id)
        order = self._adapters[st.connector].required
        for slot in order:
            if slot not in st.slots:
                return slot
        if st.connector == "zomato.food" and not (st.slots.get("address") or prof.address):
            return "address"
        if st.connector == "bookmyshow.movie" and not (st.slots.get("area") or prof.area):
            return "area"
        return None

    async def _next(self, st: TaskState) -> None:
        slot = self._missing(st)
        if slot:
            await self._ask(st, slot)
        else:
            await self._prepare(st)

    async def _ask(self, st: TaskState, slot: str) -> None:
        st.pending_slot = slot
        self._save(st, Phase.clarify)
        await self._out(st, "question", render(QUESTION_KEY[slot], st.lang))

    def _take_answer(self, st: TaskState, text: str) -> bool:
        slot = st.pending_slot
        t = text.strip()
        if not slot or not t:
            return False
        if slot == "items":
            from friday.connectors.sites.planner import _food_slots

            items = _food_slots(f"order {t}").get("items") or [{"query": t, "qty": 1}]
            st.slots["items"] = items
        elif slot == "seats":
            m = re.search(r"\d+", t)
            if not m or not 1 <= int(m.group()) <= 10:
                return False
            st.slots["seats"] = int(m.group())
        elif slot == "time":
            from friday.connectors.sites.adapters import parse_minutes

            if parse_minutes(t) is None:
                return False
            st.slots["time"] = t
        else:
            st.slots[slot] = t[:200]
        st.pending_slot = None
        return True

    # ---- text routing for an active task
    async def _on_text(self, st: TaskState, text: str) -> bool:
        t = text.strip().lower()
        if st.phase == Phase.clarify:
            if t in {"cancel", "stop", "ruko"}:
                await self._cancel(st)
            elif self._take_answer(st, text):
                await self._next(st)
            else:
                await self._ask(st, st.pending_slot or "items")
            return True
        if t in NO:
            await self._cancel(st)
        elif st.phase == Phase.await_approval:
            if t in YES:
                await self._approve(st)
            else:
                await self._show_approval(st)
        elif st.phase == Phase.await_payment and t in PAID:
            await self._paid(st)
        return True

    # ---- prepare (read-only) and approval
    async def _open(self, st: TaskState) -> Any:
        if st.task_id in self._rt:
            return self._rt[st.task_id]
        adapter_cls = self._adapters[st.connector]
        site, use_case = st.connector.split(".")
        session = await self._sessions.open(st.user_id, st.task_id, site)

        async def on_wait() -> None:
            self._save(st, Phase.await_login)
            await self._out(st, "login", render("login_needed", st.lang,
                                                site=adapter_cls.site_name,
                                                link=self._link(st.task_id)))

        ctx = RunCtx(task_id=st.task_id, user_id=st.user_id, session=session,
                     profile=self._profile(st.user_id), otp=self._otp, on_code_wait=on_wait,
                     base_url=self._urls[st.connector], repairer=self._repairer, now=self._now,
                     otp_wait_s=self._otp_wait_s, poll_s=self._poll_s, sleep=self._sleep)
        self._rt[st.task_id] = adapter_cls(ctx)
        _ = use_case
        return self._rt[st.task_id]

    def _usable(self, st: TaskState) -> bool:
        site, use_case = st.connector.split(".")
        return self._reg.select(site, use_case) is not None

    async def _prepare(self, st: TaskState) -> None:
        if not self._usable(st):
            return await self._degraded(st, "degraded")
        try:
            ad = await self._open(st)
            slots = {**st.slots}
            prep = await ad.prepare(slots)
        except Exception as e:  # noqa: BLE001 - mapped to a safe outcome
            return await self._failure(st, e)
        if prep.problem:
            key = "out_of_stock" if prep.problem.kind == "out_of_stock" else "no_match"
            text = render(key, st.lang, names=prep.problem.what, what=prep.problem.what,
                          site=ad.site_name)
            return await self._finish(st, Phase.failed, "outcome", text)
        st.proposal = prep.proposal
        self._save(st, Phase.await_approval)
        await self._show_approval(st)

    def _approval_text(self, st: TaskState, *, reask_reason: str = "", old_max: int = 0) -> str:
        p = st.proposal
        assert p is not None
        common = dict(lines="\n".join(p.lines) if st.connector == "zomato.food" else ", ".join(
            x.split(" ")[0] for x in p.lines), merchant=p.merchant, address=p.address or "-",
            subtotal=format_rupees(p.subtotal_paise), max_total=format_rupees(p.max_total_paise))
        if reask_reason:
            return render("reapprove", st.lang, reason=reask_reason, total=format_rupees(
                p.max_total_paise), old_max=format_rupees(old_max), lines="\n".join(p.lines))
        key = "approve_movie" if st.connector == "bookmyshow.movie" else "approve_food"
        return render(key, st.lang, movie=p.movie, when=p.when, **common)

    async def _show_approval(self, st: TaskState, *, reason: str = "", old_max: int = 0) -> None:
        await self._out(st, "approval", self._approval_text(st, reask_reason=reason, old_max=old_max),
                        [(f"bf:yes:{st.task_id}", render("btn_yes", st.lang)),
                         (f"bf:no:{st.task_id}", render("btn_no", st.lang))])

    async def _approve(self, st: TaskState) -> None:
        async with self._lock(st.task_id):
            st = self._store.active(st.user_id) or st
            if st.phase != Phase.await_approval or st.proposal is None:
                return  # double tap / stale
            if st.proposal.expires_at <= self._now():
                return await self._finish(st, Phase.cancelled, "outcome", render("expired", st.lang))
            self._save(st, Phase.running)
        self._spawn(self._run(st))

    async def _retry(self, st: TaskState) -> None:
        async with self._lock(st.task_id):
            st = self._store.active(st.user_id) or st
            if st.proposal is None or st.proposal.expires_at <= self._now():
                return await self._finish(st, Phase.cancelled, "outcome", render("expired", st.lang))
            self._save(st, Phase.running)
        self._spawn(self._run(st))

    # ---- run
    async def _run(self, st: TaskState) -> None:
        assert st.proposal is not None
        if not self._usable(st):
            return await self._degraded(st, "degraded")
        try:
            ad = await self._open(st)
            res: ExecResult = await ad.execute(st.proposal)
        except (LoginRequired, LoginFailed) as e:
            key = "login_failed" if isinstance(e, LoginFailed) else "login_timeout"
            self._save(st, Phase.await_login)
            return await self._out(st, "login", render(key, st.lang, site=self._site(st)),
                                   [(f"bf:retry:{st.task_id}", render("btn_retry", st.lang)),
                                    (f"bf:no:{st.task_id}", render("btn_no", st.lang))])
        except Exception as e:  # noqa: BLE001
            return await self._failure(st, e)
        st = self._store.active(st.user_id) or st
        if st.phase in TERMINAL:  # cancelled while running
            return
        st.notes = {**st.notes, **res.notes}
        if res.status == "reapprove":
            old = st.proposal.max_total_paise if st.proposal else 0
            st.proposal, st.reapprovals = res.proposal, st.reapprovals + 1
            if st.reapprovals > 2:
                return await self._finish(st, Phase.failed, "outcome", render("error", st.lang))
            self._save(st, Phase.await_approval)
            return await self._show_approval(st, reason=res.reason, old_max=old)
        if res.status == "out_of_stock":
            return await self._finish(st, Phase.failed, "outcome",
                                      render("out_of_stock", st.lang, names=res.names or "it"))
        if res.status == "no_match":
            return await self._finish(st, Phase.failed, "outcome", render(
                "no_match", st.lang, what="it", site=self._site(st)))
        h = res.handoff
        assert h is not None
        st.pay = {"amount": h.amount_paise, "merchant": h.merchant, "order_ref": h.order_ref,
                  "upi_link": h.upi_link}
        self._save(st, Phase.await_payment)
        link = render("link_part", st.lang, link=h.upi_link) if h.upi_link else ""
        await self._out(st, "payment", render("payment_ready", st.lang, amount=format_rupees(
            h.amount_paise), merchant=h.merchant, link_part=link),
            [(f"bf:paid:{st.task_id}", render("btn_paid", st.lang)),
             (f"bf:no:{st.task_id}", render("btn_no", st.lang))], h.qr_png)

    def _site(self, st: TaskState) -> str:
        return self._adapters[st.connector].site_name

    # ---- end states
    async def _paid(self, st: TaskState) -> None:
        async with self._lock(st.task_id):
            st = self._store.active(st.user_id) or st
            if st.phase != Phase.await_payment or st.proposal is None:
                return
            p = st.proposal
            f = Facts(use_case=st.connector.split(".")[1], merchant=p.merchant,
                      lines=", ".join(p.lines) if st.connector == "bookmyshow.movie"
                      else ", ".join(x.rsplit(" (", 1)[0] for x in p.lines),
                      address=p.address, movie=p.movie, when=p.when,
                      amount_paise=st.pay.get("amount", 0),
                      injection_seen=st.notes.get("injection", False),
                      repaired=st.notes.get("repaired", False))
            await self._finish(st, Phase.done, "outcome", summarise(f, st.lang))

    async def _cancel(self, st: TaskState) -> None:
        async with self._lock(st.task_id):
            st = self._store.active(st.user_id) or st
            if st.phase in TERMINAL:
                return
            await self._finish(st, Phase.cancelled, "outcome", render("cancelled", st.lang))

    async def _finish(self, st: TaskState, phase: Phase, kind: str, text: str) -> None:
        self._save(st, phase)
        self._rt.pop(st.task_id, None)
        self._otp.wipe(st.task_id)
        with contextlib.suppress(Exception):  # closing must never hide the outcome
            await self._sessions.close(st.task_id)
        await self._out(st, kind, text)

    async def _degraded(self, st: TaskState, key: str) -> None:
        site, use_case = st.connector.split(".")
        link = self._reg.fallback_url(site, use_case) or ""
        await self._finish(st, Phase.failed, "outcome",
                           render(key, st.lang, site=self._site(st), link=link))

    async def _failure(self, st: TaskState, e: Exception) -> None:
        site, use_case = st.connector.split(".")
        if isinstance(e, SiteBlocked):
            self._mark(site, use_case)
            return await self._degraded(st, "blocked")
        if isinstance(e, LayoutChanged | BrowserError | VerifyFailed):
            self._mark(site, use_case)
            return await self._degraded(st, "degraded")
        if isinstance(e, UnsafeAction | ConnectorError):
            return await self._finish(st, Phase.failed, "outcome", render("error", st.lang))
        return await self._finish(st, Phase.failed, "outcome", render("error", st.lang))

    def _mark(self, site: str, use_case: str) -> None:
        from friday.connectors.registry import PREFERENCE

        for backend in PREFERENCE:
            self._reg.set_status(site, use_case, backend, Status.degraded)


__all__ = ["BrowserFlow", "BrowserRequestHandler", "Outgoing", "Phase", "TaskState",
           "browser_enabled", "register_browser_handler", "get_browser_handler",
           "MemoryTaskStore", "JsonTaskStore", "SessionProvider", "norm"]
