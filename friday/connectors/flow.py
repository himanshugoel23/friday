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
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from friday.connectors import catalog
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
from friday.connectors.sites import categories
from friday.connectors.sites.adapters import (
    ExecResult,
    Profile,
    Proposal,
    RunCtx,
    norm,
)
from friday.connectors.sites.copy import COPY, render
from friday.connectors.sites.errors import SiteBlocked, UnsafeAction, VerifyFailed
from friday.connectors.sites.planner import Planner, RulePlanner, classify
from friday.connectors.sites.summariser import Facts, summarise

ENABLE_ENV = "FRIDAY_BROWSER_ENABLED"
YES = {"yes", "y", "haan", "han", "ha", "ok", "okay", "theek hai", "kar do", "go ahead", "karo"}
NO = {"no", "n", "nahi", "nahin", "cancel", "stop", "ruko", "rehne do", "mat karo"}
PAID = {"paid", "done", "pay kar diya", "ho gaya", "kar diya", "payment done"}
QUESTION_KEY = {"items": "q_food_items", "restaurant": "q_food_restaurant", "address": "q_address",
                "title": "q_movie_title", "seats": "q_movie_seats", "time": "q_movie_time",
                "area": "q_movie_area", "pickup": "q_pickup", "drop": "q_drop", "origin": "q_origin",
                "dest": "q_dest", "date": "q_date", "city": "q_city", "checkin": "q_checkin",
                "nights": "q_nights", "guests": "q_guests", "passengers": "q_passengers",
                "query": "q_query"}
# profile facts that stand in for a slot the user did not give (never asked twice)
PROFILE_NEEDS = {"food": ("address",), "movie": ("area",), "grocery": ("address",),
                 "shopping": ("address",)}
INT_SLOTS = {"nights": (1, 30), "guests": (1, 20), "rooms": (1, 8), "passenger_count": (1, 9),
             "seats": (1, 10)}
# planner slot -> the name an adapter may use for it (first match in ``required`` wins)
SLOT_ALIASES = {"origin": ("from",), "dest": ("destination", "to"), "city": ("destination",),
                "date": ("depart_date",), "checkin": ("checkin",)}
DATE_SLOTS = {"date", "checkin", "checkout", "depart_date", "return_date"}
OPEN_MODES = {"scripted", "official"}


def _default_mode_of(site: str) -> str:
    """Production gate: catalog.effective_mode with the FRIDAY_BROWSER_* settings (all OFF)."""
    from friday.connectors.session.settings import BrowserSettings

    return BrowserSettings().site_mode(site)


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
    """"<site>.<use case>" when the text is a browser request, else None (sync, no side effects)."""
    from friday.connectors.sites.planner import named_site

    t = text or ""
    hit = classify(t)
    if hit is None:
        return None
    site, use_case = hit
    if use_case == "movie" and not re.search(r"(?i)\b(book|ticket|tickets|seats?|movie|film)\b", t):
        return None  # "show me ...": not a booking request
    if use_case == "food" and not re.search(r"(?i)\b(order|mangao|mangwao|mangwa)\b", t) \
            and named_site(t) not in {"zomato", "swiggy"}:
        return None  # "pizza" alone is chat, not an order
    return f"{site}.{use_case}"


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
        adapters: Mapping[str, Any] | None = None,
        mode_of: Callable[[str], str] | None = None,
        credentials: Any = None,
        takeover_link: LinkFactory | None = None,
        otp_wait_s: float = 120.0,
        poll_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._send, self._reg, self._sessions, self._otp = send, registry, sessions, otp
        self._profile, self._link, self._urls = profile, login_link, dict(base_urls)
        self._planner, self._store = planner or RulePlanner(), store or MemoryTaskStore()
        self._repairer, self._enabled, self._now = repairer, enabled, now
        self._adapters = dict(categories.all_adapters() if adapters is None else adapters)
        self._mode_of = mode_of or _default_mode_of
        self._credentials = credentials
        self._takeover = takeover_link
        self._otp_wait_s, self._poll_s, self._sleep = otp_wait_s, poll_s, sleep
        self._rt: dict[str, Any] = {}  # task_id -> adapter (live browser objects, not persisted)
        self._bg: set[asyncio.Task] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    # ---- protocol surface
    def enabled(self) -> bool:
        return self._enabled()

    def matches(self, text: str) -> bool:
        return self.enabled() and _quick(text) is not None

    def has_active_task(self, user_id: str) -> bool:
        return self._store.active(user_id) is not None

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
        if not self._automated(plan.connector):
            return await self._handover(user_id, plan.connector, lang)
        task_id = f"bf-{int(self._now().timestamp() * 1000)}-{abs(hash(user_id)) % 10_000}"
        st = TaskState(task_id=task_id, user_id=user_id, lang=lang if lang in {"en", "hi"} else "en",
                       connector=plan.connector, slots=dict(plan.slots))
        self._save(st)
        await self._out(st, "ack", render("ack", st.lang))  # the ONE acknowledgement
        await self._next(st)

    # ---- the gate: automate only what catalog.effective_mode allows AND an adapter exists
    def _automated(self, connector: str) -> bool:
        site, use_case = connector.split(".", 1)
        return connector in self._adapters and self._mode_of(site) in OPEN_MODES \
            and self._reg.select(site, use_case) is not None

    async def _handover(self, user_id: str, connector: str, lang: str) -> None:
        """No automation for this site today (not cleared / not enabled / no adapter / killed): hand
        the user the public link, once. Nothing is started, nothing is stored."""
        site, use_case = connector.split(".", 1)
        spec = catalog.site(site)
        link = self._reg.fallback_url(site, use_case) or (spec.home if spec else "")
        name = spec.name if spec else site
        lg = lang if lang in {"en", "hi"} else "en"
        await self._send(Outgoing(user_id=user_id, kind="outcome", text=scrub_text(
            render("handover", lg, site=name, link=link))))

    def _canon(self, st: TaskState, ad: Any) -> None:
        """Planner slot names -> the adapter's own (``origin`` -> ``from``; checkout = checkin +
        nights; a rider count -> ``passenger_count``). Never overwrites what the user gave."""
        need = set(ad.required) | set(getattr(ad, "optional", ()))
        for src, targets in SLOT_ALIASES.items():
            if src in st.slots:
                for t in targets:
                    if t in need and t not in st.slots:
                        st.slots[t] = st.slots[src]
                        break
        if "checkout" in need and "checkout" not in st.slots and st.slots.get("checkin") \
                and st.slots.get("nights"):
            from datetime import date as _d

            try:
                st.slots["checkout"] = (_d.fromisoformat(str(st.slots["checkin"]))
                                        + timedelta(days=int(st.slots["nights"]))).isoformat()
            except ValueError:
                pass

    def _missing(self, st: TaskState) -> str | None:
        prof = self._profile(st.user_id)
        ad = self._adapters[st.connector]
        use_case = st.connector.split(".", 1)[1]
        have = {"address": prof.address, "area": prof.area, "pickup": prof.address}
        self._canon(st, ad)
        for slot in ad.required:
            if slot not in st.slots:
                if have.get(slot):  # the profile answers it: do not ask
                    st.slots[slot] = have[slot]
                    continue
                return slot
        for slot in getattr(ad, "profile_needs", PROFILE_NEEDS.get(use_case, ())):
            if not (st.slots.get(slot) or have.get(slot)):
                return slot
        return None

    async def _next(self, st: TaskState) -> None:
        slot = self._missing(st)
        if slot:
            await self._ask(st, slot)
        else:
            await self._prepare(st)

    def _question_key(self, st: TaskState, slot: str) -> str | None:
        use = st.connector.split(".", 1)[1]
        pkgs = {"hotel": ("stay",), "flight": ("stay",)}.get(use, ())
        for k in (f"q_{use}_{slot}", *(f"q_{p}_{slot}" for p in pkgs), QUESTION_KEY.get(slot, "")):
            if k and k in COPY:
                return k
        return None

    async def _ask(self, st: TaskState, slot: str) -> None:
        st.pending_slot = slot
        self._save(st, Phase.clarify)
        if slot == "substitute":
            sub = st.slots.get("_sub", {})
            opts = ", ".join(sub.get("options", []))
            text = render("grocery_out_of_stock", st.lang, name=sub.get("what", "it"),
                          options=render("grocery_options", st.lang, options=opts) if opts else "")
            return await self._out(st, "question", text)
        key = self._question_key(st, slot)
        text = render(key, st.lang) if key else render("q_generic", st.lang, slot=slot)
        await self._out(st, "question", text)

    def _take_answer(self, st: TaskState, text: str) -> bool:
        slot = st.pending_slot
        t = text.strip()
        if not slot or not t:
            return False
        if slot == "substitute":
            return self._take_substitute(st, t)
        if slot == "items":
            from friday.connectors.sites.planner import _food_slots, _grocery_slots

            use_case = st.connector.split(".", 1)[1]
            if use_case == "grocery":
                items = _grocery_slots(t).get("items")
            else:
                items = _food_slots(f"order {t}").get("items") or [{"query": t, "qty": 1}]
            if not items:
                return False
            st.slots["items"] = items
        elif slot in INT_SLOTS:
            m = re.search(r"\d+", t)
            lo, hi = INT_SLOTS[slot]
            if not m or not lo <= int(m.group()) <= hi:
                return False
            st.slots[slot] = int(m.group())
        elif slot in DATE_SLOTS:
            from datetime import date as _date

            from friday.connectors.sites.planner import _date_slot

            iso = t if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else _date_slot(t, (self._now() + timedelta(hours=5, minutes=30)).date())[0]
            if not iso:
                return False
            try:
                _date.fromisoformat(iso)
            except ValueError:
                return False
            st.slots[slot] = iso
        elif slot == "time":
            from friday.connectors.sites.adapters import parse_minutes

            if parse_minutes(t) is None:
                return False
            st.slots["time"] = t
        else:
            st.slots[slot] = t[:200]
        st.pending_slot = None
        return True

    def _take_substitute(self, st: TaskState, t: str) -> bool:
        sub = st.slots.get("_sub") or {}
        what, opts = str(sub.get("what", "")), [str(o) for o in sub.get("options", [])]
        items = list(st.slots.get("items", []))
        idx = next((i for i, it in enumerate(items) if norm(what) in norm(it.get("query", ""))
                    or norm(it.get("query", "")) in norm(what)), None)
        low = t.lower()
        pick = next((o for o in opts if norm(o) and norm(o) in norm(t)), None)
        if pick and idx is not None:
            items[idx] = {**items[idx], "query": pick}
        elif re.search(r"(?i)\b(skip|chhod|chod|nahi|no|rehne|hata)\b", low) and idx is not None:
            items.pop(idx)
        else:
            return False
        if items:
            st.slots["items"] = items
        else:
            st.slots.pop("items", None)  # nothing left: ask what to order
        st.slots.pop("_sub", None)
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
                     base_url=self._base_url(st.connector), repairer=self._repairer, now=self._now,
                     otp_wait_s=self._otp_wait_s, poll_s=self._poll_s, sleep=self._sleep,
                     credentials=self._credentials)
        self._rt[st.task_id] = adapter_cls(ctx)
        _ = use_case
        return self._rt[st.task_id]

    def _base_url(self, connector: str) -> str:
        spec = catalog.site(connector.split(".", 1)[0])
        return self._urls.get(connector) or (spec.home if spec else "")

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
            return await self._problem(st, ad, prep.problem)
        st.proposal = prep.proposal
        self._save(st, Phase.await_approval)
        await self._show_approval(st)

    async def _problem(self, st: TaskState, ad: Any, prob: Any) -> None:
        """Map a ``Problem`` (kinds: no_match, out_of_stock, needs_login, closed, below_minimum,
        no_slot) to wording. A login problem sends the takeover link and waits; a sold-out item with
        in-stock ``options`` becomes a "substitute?" question; everything else ends the task."""
        use = st.connector.split(".", 1)[1]
        kind, what = str(prob.kind), str(prob.what)
        opts = tuple(getattr(prob, "options", ()) or ())
        if kind == "needs_login":
            return await self._ask_login(st, ad)
        if kind == "out_of_stock" and opts and use == "grocery":
            st.slots["_sub"] = {"what": what, "options": list(opts)[:5]}
            st.pending_slot = "substitute"
            self._save(st, Phase.clarify)
            return await self._ask(st, "substitute")
        text = self._problem_text(st, ad, use, kind, what)
        await self._finish(st, Phase.failed, "outcome", text)

    def _problem_text(self, st: TaskState, ad: Any, use: str, kind: str, what: str) -> str:
        site = ad.site_name
        aliases = {"no_match": ("no_match", "place_not_found"), "out_of_stock": ("out_of_stock", "unavailable"),
                   "closed": ("closed",), "below_minimum": ("below_minimum",), "no_slot": ("no_slot",)}
        for suffix in aliases.get(kind, (kind,)):
            key = f"{use}_{suffix}"
            if key in COPY:
                return render(key, st.lang, name=what, options="", what=what, site=site, names=what)
        key = "out_of_stock" if kind == "out_of_stock" else "no_match"
        return render(key, st.lang, names=what, what=what, site=site)

    async def _ask_login(self, st: TaskState, ad: Any) -> None:
        """The site logged the user out: hand over the takeover link (the user logs in on the site's
        own page); Friday never sees the password or code. The session stays open to continue."""
        use = st.connector.split(".", 1)[1]
        link = (self._takeover or self._link)(st.task_id)
        key = f"{use}_login_needed" if f"{use}_login_needed" in COPY else "login_needed"
        self._save(st, Phase.await_login)
        await self._out(st, "login", render(key, st.lang, site=ad.site_name, link=link),
                        [(f"bf:retry:{st.task_id}", render("btn_retry", st.lang)),
                         (f"bf:no:{st.task_id}", render("btn_no", st.lang))])

    def _approval_text(self, st: TaskState, *, reask_reason: str = "", old_max: int = 0) -> str:
        p = st.proposal
        assert p is not None
        use_case = st.connector.split(".", 1)[1]
        if reask_reason:
            return render("reapprove", st.lang, reason=reask_reason, total=format_rupees(
                p.max_total_paise), old_max=format_rupees(old_max), lines="\n".join(p.lines))
        terms = str(p.details.get("terms") or "")
        extra = {k: v for k, v in p.details.items() if isinstance(v, str | int | float)}
        common = dict(
            lines=(", ".join(x.split(" ")[0] for x in p.lines) if use_case == "movie"
                   else "\n".join(p.lines)),
            merchant=p.merchant, address=p.address or "-", subtotal=format_rupees(p.subtotal_paise),
            max_total=format_rupees(p.max_total_paise), extra=f"\n{terms}" if terms else "",
            area=p.area, **{k: v for k, v in extra.items() if k not in {"lines", "merchant"}})
        if use_case == "movie":
            return render("approve_movie", st.lang, movie=p.movie, when=p.when, **common)
        key = "approve_food" if use_case == "food" else f"approve_{use_case}"
        key = key if key in COPY else "approve_shopping"
        return render(key, st.lang, loose=True, when=p.when, movie=p.movie, **common)

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
            if st.proposal is None:  # the login came before any approval card: prepare again
                self._save(st, Phase.running)
                self._spawn(self._prepare(st))
                return
            if st.proposal.expires_at <= self._now():
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
        use = st.connector.split(".", 1)[1]
        if res.status == "ride_requested":
            return await self._ride_done(st, res)
        if res.status == "out_of_stock":
            if use == "ride":
                key = "ride_no_driver" if str(res.names).startswith("a driver") else "ride_unavailable"
                text = render(key, st.lang, site=self._site(st), what=res.names or "that ride")
            else:
                text = render("out_of_stock", st.lang, names=res.names or "it")
            return await self._finish(st, Phase.failed, "outcome", text)
        if res.status == "no_match":
            what = res.reason or "it"
            return await self._finish(st, Phase.failed, "outcome", self._problem_text(
                st, self._adapters[st.connector], use, "no_match", what))
        h = res.handoff
        if h is None:
            return await self._finish(st, Phase.failed, "outcome", render("error", st.lang))
        st.pay = {"amount": h.amount_paise, "merchant": h.merchant, "order_ref": h.order_ref,
                  "upi_link": h.upi_link}
        self._save(st, Phase.await_payment)
        link = render("link_part", st.lang, link=h.upi_link) if h.upi_link else ""
        await self._out(st, "payment", render("payment_ready", st.lang, amount=format_rupees(
            h.amount_paise), merchant=h.merchant, link_part=link),
            [(f"bf:paid:{st.task_id}", render("btn_paid", st.lang)),
             (f"bf:no:{st.task_id}", render("btn_no", st.lang))], h.qr_png)

    async def _ride_done(self, st: TaskState, res: Any) -> None:
        """A ride was requested: driver text, the one-time page link for the start code, the trip
        share link. No payment phase (the user pays the driver or in the app). The start code
        itself never passes through here, only the link token."""
        d = getattr(res, "driver", None)
        driver = " ".join(x for x in (getattr(d, "name", ""), getattr(d, "vehicle_no", ""),
                                      getattr(d, "vehicle_model", "")) if x) or "on the way"
        share = str(getattr(res, "share_link", "") or "")
        text = render("ride_booked", st.lang, driver=driver, otp_link=getattr(res, "otp_link", ""),
                      share_link=share)
        if not share:
            text = text.rsplit("\n", 1)[0]
        await self._finish(st, Phase.done, "outcome", text, keep_reveal=True)

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

    async def _finish(self, st: TaskState, phase: Phase, kind: str, text: str, *,
                      keep_reveal: bool = False) -> None:
        self._save(st, phase)
        self._rt.pop(st.task_id, None)
        self._otp.wipe(st.task_id)
        if not keep_reveal:  # a booked ride keeps its start-code link (15 min, one use) for pickup
            with contextlib.suppress(Exception):
                from friday.connectors.sites.ride import DEFAULT_REVEAL

                DEFAULT_REVEAL.wipe(st.task_id)
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
        from friday.connectors.session.manager import SessionRefused

        if isinstance(e, SessionRefused):  # switch off / cap / kill latch: not the site's fault
            return await self._degraded(st, "degraded")
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
