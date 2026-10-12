# ruff: noqa: E501
"""WhatsApp quotes flow: the conversation state machine (docs/WHATSAPP_QUOTES_FLOW.md).

    COLLECTING -> CONFIRMING -> QUEUED/CALLING -> AWAITING_BOOK -> BOOKING -> DONE
        (any state) -> CANCELLED   (user said cancel/stop)

Rules (founder): everything after the user's approval runs on the SERVER (docs/HANDOFF.md 2b):
the vendor calls, the single retry and the comparison do not need the user's phone to be on.
The state lives in the DB (``quote_conversations``); ``tick()`` resumes anything interrupted by
a restart; the result is delivered over WhatsApp, with an SMS summary as the fallback, and the
user can ask "status" at any later time to get the stored result.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from friday.core.clock import at_ist, ist_day_bounds, to_ist
from friday.core.container import ComponentNotAvailable
from friday.core.events import TaskStatusChanged
from friday.core.logging import get_logger
from friday.core.models import (
    Channel,
    GeoPoint,
    InboundMessage,
    MessageKind,
    OutboundMessage,
    ReplyButton,
    TaskStatus,
    TemplateRef,
    User,
    new_id,
)
from friday.discovery.geo import haversine_km
from friday.pause import is_paused
from friday.playbooks.model import PlaybookError
from friday.quotes import messages as M
from friday.quotes import parse as P
from friday.quotes.calls import EngineVendorCalls
from friday.quotes.finder import VendorFinder
from friday.quotes.models import (
    Conv,
    Delivery,
    Location,
    Outcome,
    State,
    Vendor,
    VStatus,
)
from friday.quotes.store import QuoteStore

if TYPE_CHECKING:
    from friday.api.inbound import InboundPipeline
    from friday.core.container import Container

log = get_logger(__name__)

CITY_CENTERS = {
    "gurgaon": (GeoPoint(lat=28.4595, lng=77.0266), "Gurgaon"),
    "bangalore": (GeoPoint(lat=12.9716, lng=77.5946), "Bangalore"),
}
CITY_RADIUS_KM = 45.0
VENDOR_TIMEOUT_MIN = 20  # a vendor call that never reports back is given up after this
CLAIM_GRACE_MIN = 2
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
BTN = "qf"
MAX_SEEN = 30
DAYS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "hinglish": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "hi": ["सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"],
}
WORDS = {
    "en": {"aaj": "today", "kal": "tomorrow", "parso": "day after tomorrow", "subah": "morning",
           "dopahar": "afternoon", "shaam": "evening", "raat": "night", "baje": "o'clock"},
    "hi": {"aaj": "आज", "kal": "कल", "parso": "परसों", "subah": "सुबह", "dopahar": "दोपहर",
           "shaam": "शाम", "raat": "रात", "baje": "बजे"},
}  # fmt: skip


def city_for_point(point: GeoPoint) -> str | None:
    best: tuple[float, str] | None = None
    for key, (center, _label) in CITY_CENTERS.items():
        d = haversine_km(point, center)
        if d <= CITY_RADIUS_KM and (best is None or d < best[0]):
            best = (d, key)
    return best[1] if best else None


def city_label(city: str | None) -> str:
    return CITY_CENTERS[city][1] if city in CITY_CENTERS else ""


def short_name(name: str, limit: int) -> str:
    n = " ".join(name.split())
    if len(n) <= limit:
        return n
    for w in ("Unisex", "Beauty", "Parlour", "Salon", "Studio", "&", "and", "The"):
        n = " ".join(x for x in n.split() if x.lower() != w.lower()) or n
        if len(n) <= limit:
            return n
    return n[:limit].rstrip()


def _when_words(conv: Conv, lang: str) -> str:
    sl = conv.slots
    text = sl.when_text or ""
    if lang == "hinglish" or not text:
        return text
    table = WORDS.get(lang, WORDS["en"])
    out = []
    for w in text.split():
        out.append(table.get(w.lower(), w))
    return " ".join(out)


def _time_label(dt: datetime, lang: str, now: datetime) -> str:
    local = to_ist(dt)
    days = (local.date() - to_ist(now).date()).days
    if days == 0:
        day = {"en": "today", "hinglish": "aaj", "hi": "आज"}[lang]
    elif days == 1:
        day = {"en": "tomorrow", "hinglish": "kal", "hi": "कल"}[lang]
    else:
        day = DAYS[lang][local.weekday()]
    h12 = local.hour % 12 or 12
    mm = f":{local.minute:02d}" if local.minute else ""
    return f"{day} {h12}{mm} {'AM' if local.hour < 12 else 'PM'}"


class QuotesFlow:
    def __init__(self, c: Container, pipeline: InboundPipeline | None = None) -> None:
        self.c = c
        self.p = pipeline
        self.settings = c.settings
        self.clock = c.clock
        self._store: QuoteStore | None = None
        self._finder: VendorFinder | None = None
        self.calls: Any = None  # EngineVendorCalls (tests may inject a fake)
        self._subscribed = False
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ wiring
    @property
    def enabled(self) -> bool:
        return bool(self.settings.quotes_flow_enabled)

    @property
    def store(self) -> QuoteStore:
        if self._store is None:
            self._store = QuoteStore(self.c.repos.db, self.clock)
        return self._store

    def _opt(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except ComponentNotAvailable:
            return None
        except Exception:  # noqa: BLE001 - a missing key must not break chat
            log.exception("component %s failed to build", name)
            return None

    @property
    def finder(self) -> VendorFinder:
        if self._finder is None:
            s = self.settings
            self._finder = VendorFinder(
                self._opt("directory"),
                cache=self._opt("cache"),
                pool=self._opt("number_pool"),
                radius_km=s.quotes_radius_km,
                min_rating=s.discovery_min_rating,
                max_calls=s.quotes_max_places_calls_per_request,
                cache_ttl_s=s.quotes_places_cache_ttl_s,
            )
        return self._finder

    def _calls(self) -> Any:
        if self.calls is None:
            self.calls = EngineVendorCalls(self.c, self.finder)
        return self.calls

    def subscribe(self) -> None:
        if not self._subscribed:
            self.c.bus.subscribe(TaskStatusChanged, self.on_task_status)
            self._subscribed = True

    def unsubscribe(self) -> None:
        if self._subscribed:
            self.c.bus.unsubscribe(TaskStatusChanged, self.on_task_status)
            self._subscribed = False

    @contextlib.asynccontextmanager
    async def _hold(self, user_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            yield

    # ------------------------------------------------------------------ sending
    async def _user(self, user_id: str) -> User | None:
        return await self.c.repos.users.get(user_id)

    async def _say(
        self, conv: Conv, key: str, *, buttons: list[tuple[str, str]] | None = None, **kw: Any
    ) -> None:
        text = M.msg(key, conv.lang, **kw)
        await self._send_text(conv, text, buttons)

    async def _send_text(
        self, conv: Conv, text: str, buttons: list[tuple[str, str]] | None = None
    ) -> Any:
        notifier = self._opt("notifier")
        user = await self._user(conv.user_id)
        if notifier is None or user is None:
            return None
        btns = [ReplyButton(id=i, title=t[:20]) for i, t in (buttons or [])][:3]
        try:
            return await notifier.notify_user(user.id, text, buttons=btns)
        except Exception as e:  # noqa: BLE001 - a send problem never kills the flow
            log.warning("quotes: send failed: %s", type(e).__name__)
            return None

    # ------------------------------------------------------------------ entry from the pipeline
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        """True when the flow consumed the message."""
        if not self.enabled:
            return False
        text = (msg.text or "").strip()
        is_btn = msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith(f"{BTN}:")
        async with self._hold(user.id):
            got = await self.store.active_for_user(user.id)
            latest = await self.store.latest_for_user(user.id)
            pid = msg.provider_message_id
            if pid and latest and pid in latest[0].seen_ids:
                return True  # duplicate delivery (Meta retry): already handled
            if is_btn:
                return await self._on_button(user, msg, got)
            if msg.kind == MessageKind.VOICE_NOTE:
                if got is not None or (text and P.looks_like_request(text)):
                    await self._reply_new(user, got, "voice_note", pid, text)
                    return True
                return False
            if msg.kind not in (MessageKind.TEXT, MessageKind.LOCATION):
                return False
            if msg.kind == MessageKind.TEXT and P.STATUS_RE.match(text):
                return await self._status(user, latest, pid)
            if got is None:
                if msg.kind == MessageKind.TEXT and P.looks_like_request(text):
                    open_q = await self.c.repos.tasks.open_question_for_user(user.id)
                    if open_q is not None:
                        return False  # the user is answering a mid-call question
                    return await self._new(user, msg, text)
                return False
            conv, _ = got
            return await self._continue(user, msg, conv, text)

    async def _reply_new(
        self, user: User, got: tuple[Conv, int] | None, key: str, pid: str | None, text: str
    ) -> None:
        lang = got[0].lang if got else P.ui_lang(text, await self._profile_lang(user))
        stub = got[0] if got else Conv(user_id=user.id, lang=lang)
        stub = stub.model_copy(update={"lang": lang})
        await self._say(stub, key)
        if got and pid:
            await self._remember(got[0].id, pid)

    async def _profile_lang(self, user: User) -> str:
        prof = await self.c.repos.profiles.get_or_default(user.id)
        v = getattr(prof.language, "value", str(prof.language))
        return v if v in ("en", "hi", "hinglish") else "hinglish"

    async def _remember(self, conv_id: str, pid: str | None) -> None:
        if not pid:
            return

        def fn(c: Conv) -> None:
            if pid not in c.seen_ids:
                c.seen_ids = [*c.seen_ids, pid][-MAX_SEEN:]

        await self.store.mutate(conv_id, fn)

    # ------------------------------------------------------------------ new conversation
    async def _new(self, user: User, msg: InboundMessage, text: str) -> bool:
        now = self.clock.now()
        start, end = ist_day_bounds(now)
        used = await self.store.count_counted_between(user.id, start, end)
        cap = self.settings.quotes_max_requests_per_day
        lang = P.ui_lang(text, await self._profile_lang(user))
        conv = Conv(user_id=user.id, lang=lang, created_at=now, last_user_at=now)
        if msg.provider_message_id:
            conv.seen_ids = [msg.provider_message_id]
        if used >= cap:
            conv.state = State.CANCELLED
            await self.store.create(conv)
            await self._say(conv, "daily_cap", n=cap)
            return True
        parsed = P.parse_request(text, now, default_lang=lang)
        self._merge(conv, parsed, overwrite=True)
        if parsed.other_city and not parsed.city:
            conv.state = State.CANCELLED
            await self.store.create(conv)
            await self._say(conv, "wrong_city")
            return True
        if parsed.location_text and not P.city_only(parsed.location_text):
            conv.slots.location = Location(text=parsed.location_text, city=parsed.city)
        elif parsed.city:
            conv.slots.location = Location(city=parsed.city)
        await self.store.create(conv)
        await self._advance(conv.id, user)
        return True

    def _merge(self, conv: Conv, p: P.Parsed, *, overwrite: bool) -> None:
        sl = conv.slots
        if p.services and (overwrite or not sl.services):
            sl.services = p.services
        if p.for_name:
            sl.for_name = p.for_name
            sl.for_other_unnamed = False
        elif p.for_other_unnamed and not sl.for_name:
            sl.for_other_unnamed = True
        if p.when_text and (overwrite or not sl.when_text):
            sl.when_text, sl.when_start, sl.when_end = p.when_text, p.when_start, p.when_end
            sl.exact_time, sl.day_set = p.exact_time, p.day_set
        if p.budget_inr and (overwrite or not sl.budget_inr):
            sl.budget_inr = p.budget_inr
        if p.book_intent:
            sl.book_intent = True

    # ------------------------------------------------------------------ slot filling
    def _next_missing(self, conv: Conv) -> str | None:
        sl = conv.slots
        if not sl.services:
            return "services"
        if sl.for_other_unnamed and not sl.for_name:
            return "for_name"
        if not sl.when_text:
            return "when"
        if not sl.location.ok:
            return "location"
        return None

    async def _advance(self, conv_id: str, user: User) -> None:
        got = await self.store.get(conv_id)
        if got is None:
            return
        conv = got[0]
        missing = self._next_missing(conv)
        if missing is None:
            await self._resolve_then_search(conv, user)
            return
        if missing == "location" and conv.slots.location.text and not conv.slots.location.ok:
            await self._resolve_then_search(conv, user)
            return

        def fn(c: Conv) -> None:
            c.state, c.asking = State.COLLECTING, missing

        await self.store.mutate(conv.id, fn)
        key = {
            "services": "ask_services",
            "for_name": "ask_for_name",
            "when": "ask_when",
            "location": "ask_location",
        }[missing]
        await self._say(conv, key)

    async def _continue(self, user: User, msg: InboundMessage, conv: Conv, text: str) -> bool:
        pid = msg.provider_message_id
        now = self.clock.now()
        if msg.kind == MessageKind.TEXT:
            if P.STOP_RE.match(text):
                await self._remember(conv.id, pid)
                await self._stop_all(user, conv)
                return True
            if P.CANCEL_RE.match(text) or (conv.state == State.CONFIRMING and P.NO_RE.match(text)):
                await self._remember(conv.id, pid)
                await self._cancel(conv, "cancelled")
                return True
            if conv.state in (State.CONFIRMING, State.AWAITING_BOOK) and (
                P.looks_like_request(text) and conv.asking != "book_time"
            ):
                # a fresh request replaces the open one
                await self._cancel(conv, None)
                return await self._new(user, msg, text)
            lang = self._lang_from(conv, text)
        else:
            lang = conv.lang

        def touch(c: Conv) -> None:
            c.lang = lang
            c.last_user_at = now
            if pid and pid not in c.seen_ids:
                c.seen_ids = [*c.seen_ids, pid][-MAX_SEEN:]

        conv = await self.store.mutate(conv.id, touch) or conv
        if conv.state == State.COLLECTING:
            return await self._answer(user, msg, conv, text)
        if conv.state == State.CONFIRMING:
            if msg.kind == MessageKind.TEXT and P.YES_RE.match(text):
                await self._go(user, conv)
            elif msg.kind == MessageKind.TEXT and P.CHANGE_RE.match(text):
                await self._change(user, conv)
            elif msg.kind in (MessageKind.LOCATION, MessageKind.TEXT) and (
                msg.kind == MessageKind.LOCATION or P.parse_location_phrase(text)
            ):
                await self._new_area(user, conv, msg, text)
            else:
                await self._say(conv, "tap_choice", buttons=self._confirm_buttons(conv))
            return True
        if conv.state == State.AWAITING_BOOK:
            return await self._book_text(user, conv, text)
        if conv.state in (State.QUEUED, State.CALLING, State.BOOKING):
            if P.looks_like_request(text):
                await self._say(conv, "busy")
                return True
            return False
        return False

    def _lang_from(self, conv: Conv, text: str) -> str:
        words = re.findall(r"[\wऀ-ॿ]+", text)
        new = P.ui_lang(text, conv.lang)
        if re.search(r"[ऀ-ॿ]", text) or (new != "en" and len(words) >= 2):
            return new
        return new if (new == "en" and len(words) >= 5) else conv.lang

    async def _answer(self, user: User, msg: InboundMessage, conv: Conv, text: str) -> bool:
        now = self.clock.now()
        asking = conv.asking
        if asking == "location":
            await self._set_location(user, conv, msg, text)
            return True
        parsed = P.parse_request(text, now, default_lang=conv.lang) if text else P.Parsed()
        if asking == "for_name":
            name = re.sub(r"[^A-Za-zऀ-ॿ ]", "", text).strip().split(" ")[0] if text else ""
            if name:
                parsed.for_name = name.title() if name.isascii() else name

        def fn(c: Conv) -> None:
            self._merge(c, parsed, overwrite=True)
            if parsed.city and not c.slots.location.ok and not c.slots.location.text:
                c.slots.location = Location(city=parsed.city)

        conv = await self.store.mutate(conv.id, fn) or conv
        if parsed.other_city and not parsed.city and not conv.slots.location.ok:
            await self._cancel(conv, "wrong_city")
            return True
        await self._advance(conv.id, user)
        return True

    # ------------------------------------------------------------------ location
    async def _set_location(
        self, user: User, conv: Conv, msg: InboundMessage, text: str
    ) -> None:
        loc, problem = await self._locate(msg, text, conv)
        if problem == "wrong_city":
            await self._cancel(conv, "wrong_city")
            return
        if problem == "error":
            await self._say(conv, "places_failed")
            return
        if loc is None:
            await self._say(conv, "location_unclear")
            return

        def fn(c: Conv) -> None:
            c.slots.location = loc
            c.asking = None

        await self.store.mutate(conv.id, fn)
        await self._advance(conv.id, user)

    async def _locate(
        self, msg: InboundMessage, text: str, conv: Conv
    ) -> tuple[Location | None, str | None]:
        geocoder = self._opt("geocoder")
        if msg.kind == MessageKind.LOCATION and msg.location is not None:
            pt = GeoPoint(lat=msg.location.lat, lng=msg.location.lng)
            city = city_for_point(pt)
            if city is None:
                return None, "wrong_city"
            address = msg.location.address or msg.location.name
            if address is None and geocoder is not None:
                with contextlib.suppress(Exception):
                    rev = await geocoder.reverse(pt)
                    address = rev.formatted_address if rev else None
            return Location(
                text=address or city_label(city), lat=pt.lat, lng=pt.lng, city=city, address=address
            ), None
        parsed = P.parse_request(text, self.clock.now(), default_lang=conv.lang)
        if parsed.other_city and not parsed.city:
            return None, "wrong_city"
        phrase = text.strip()
        if not phrase or P.city_only(phrase):
            return None, None
        if geocoder is None:
            return None, "error"
        try:
            res = await geocoder.geocode(phrase)
        except Exception as e:  # noqa: BLE001
            log.warning("geocode failed: %s", type(e).__name__)
            return None, "error"
        if res is None:
            return None, None
        city = city_for_point(res.location)
        if city is None:
            return (None, "wrong_city") if not parsed.city else (None, None)
        return Location(
            text=phrase, lat=res.location.lat, lng=res.location.lng, city=city,
            address=res.formatted_address,
        ), None

    async def _resolve_then_search(self, conv: Conv, user: User) -> None:
        loc = conv.slots.location
        if not loc.ok:
            pseudo = InboundMessage(channel=Channel.WHATSAPP, from_phone=user.phone, text=loc.text)
            found, problem = await self._locate(pseudo, loc.text or "", conv)
            if problem == "wrong_city":
                await self._cancel(conv, "wrong_city")
                return
            if problem == "error":
                await self._say(conv, "places_failed")
                return
            if found is None:
                def clear(c: Conv) -> None:
                    c.state, c.asking = State.COLLECTING, "location"
                    c.slots.location = Location()

                await self.store.mutate(conv.id, clear)
                await self._say(conv, "location_unclear")
                return
            conv = await self.store.mutate(conv.id, lambda c: setattr(c.slots, "location", found)) or conv
        await self._search(conv, user, exclude=set())

    async def _new_area(self, user: User, conv: Conv, msg: InboundMessage, text: str) -> None:
        loc, problem = await self._locate(msg, text, conv)
        if problem == "wrong_city":
            await self._say(conv, "wrong_city")
            return
        if loc is None:
            await self._say(conv, "location_unclear")
            return

        def fn(c: Conv) -> None:
            c.slots.location = loc
            c.shortlist, c.alternates = [], []

        conv = await self.store.mutate(conv.id, fn) or conv
        await self._search(conv, user, exclude=set())

    # ------------------------------------------------------------------ search + shortlist
    async def _search(self, conv: Conv, user: User, *, exclude: set[str]) -> None:
        cap = self.settings.quotes_max_places_calls_per_request
        remaining = cap - conv.places_calls
        if remaining <= 0:
            await self._say(conv, "no_more_vendors")
            return
        loc = conv.slots.location
        point = GeoPoint(lat=loc.lat or 0.0, lng=loc.lng or 0.0)
        if conv.places_calls == 0:
            await self._say(conv, "searching")
        def mark(c: Conv) -> None:
            c.counted = True

        await self.store.mutate(conv.id, mark)
        when = conv.slots.when_start
        res = await self.finder.find(
            point,
            where_text=loc.address or loc.text or city_label(loc.city),
            when=when,
            exclude=exclude,
            max_calls=remaining,
        )

        def used(c: Conv) -> None:
            c.places_calls += res.calls_used

        conv = await self.store.mutate(conv.id, used) or conv
        if res.error and not res.vendors:
            await self._say(conv, "places_failed")
            return
        if not res.vendors:
            def ask(c: Conv) -> None:
                c.state, c.asking = State.COLLECTING, "location"
                c.slots.location = Location()

            await self.store.mutate(conv.id, ask)
            await self._say(conv, "no_vendors")
            return
        size = self.settings.discovery_shortlist_size
        shortlist, rest = res.vendors[:size], res.vendors[size:]

        def show(c: Conv) -> None:
            c.state, c.asking = State.CONFIRMING, None
            c.shortlist, c.alternates = shortlist, rest

        conv = await self.store.mutate(conv.id, show) or conv
        await self._say_shortlist(conv)

    def _confirm_buttons(self, conv: Conv) -> list[tuple[str, str]]:
        return [
            (f"{BTN}:{conv.id}:go", M.msg("btn_call", conv.lang)),
            (f"{BTN}:{conv.id}:chg", M.msg("btn_change", conv.lang)),
        ]

    async def _say_shortlist(self, conv: Conv) -> None:
        lines = []
        for i, v in enumerate(conv.shortlist, 1):
            rating = f"{v.rating:g}" if v.rating is not None else "new"
            reviews = f" ({v.review_count})" if v.review_count else ""
            dist = f", {v.distance_km:.1f} km" if v.distance_km is not None else ""
            lines.append(f"{i}. {v.name} - {rating}{reviews}{dist}")
        loc = conv.slots.location
        await self._say(
            conv,
            "shortlist",
            buttons=self._confirm_buttons(conv),
            n=len(conv.shortlist),
            where=short_name(loc.text or city_label(loc.city), 40),
            lines="\n".join(lines),
            services=M.services_text(conv.slots.services, conv.lang),
        )

    async def _change(self, user: User, conv: Conv) -> None:
        if not conv.alternates:
            # one more directory search, excluding what was already shown
            shown = {v.place_id for v in conv.shortlist}
            await self._search(conv, user, exclude=shown)
            return
        size = self.settings.discovery_shortlist_size

        def fn(c: Conv) -> None:
            c.shortlist, c.alternates = c.alternates[:size], c.alternates[size:]

        conv = await self.store.mutate(conv.id, fn) or conv
        await self._say_shortlist(conv)

    # ------------------------------------------------------------------ buttons
    async def _on_button(
        self, user: User, msg: InboundMessage, got: tuple[Conv, int] | None
    ) -> bool:
        parts = (msg.button_id or "").split(":")
        if len(parts) < 3:
            return True
        conv_id, action = parts[1], parts[2]
        arg = parts[3] if len(parts) > 3 else ""
        found = await self.store.get(conv_id)
        if found is None or found[0].user_id != user.id:
            return True  # not ours (SECURITY-9: never act on someone else's button)
        conv = found[0]
        pid = msg.provider_message_id
        if pid and pid in conv.seen_ids:
            return True
        await self._remember(conv.id, pid)
        if not conv.state.active:
            await self._say(conv, "stale")
            return True
        if action == "go" and conv.state == State.CONFIRMING:
            await self._go(user, conv)
        elif action == "chg" and conv.state == State.CONFIRMING:
            await self._change(user, conv)
        elif action == "book" and conv.state == State.AWAITING_BOOK and arg.isdigit():
            await self._book(user, conv, int(arg))
        elif action == "retry" and conv.state == State.AWAITING_BOOK:
            await self._redo(user, conv, same=True)
        elif action == "others" and conv.state == State.AWAITING_BOOK:
            await self._redo(user, conv, same=False)
        elif action in ("go", "chg", "book", "retry", "others"):
            return True  # a repeat tap of a button already acted on: idempotent, no reply
        else:
            await self._say(conv, "stale")
        return True

    # ------------------------------------------------------------------ approval -> calls
    def _window_ok(self, now: datetime) -> bool:
        s = self.settings
        local = to_ist(now)
        sh, sm = (int(x) for x in s.quotes_call_window_start.split(":"))
        eh, em = (int(x) for x in s.quotes_call_window_end.split(":"))
        return at_ist(local.date(), sh, sm) <= now < at_ist(local.date(), eh, em)

    def _next_window(self, now: datetime) -> datetime:
        s = self.settings
        local = to_ist(now)
        sh, sm = (int(x) for x in s.quotes_call_window_start.split(":"))
        start_today = at_ist(local.date(), sh, sm)
        if now < start_today:
            return start_today
        return at_ist(local.date() + timedelta(days=1), sh, sm)

    async def _go(self, user: User, conv: Conv) -> None:
        if is_paused(self.settings):
            await self._say(conv, "paused", buttons=self._confirm_buttons(conv))
            return
        first = conv.shortlist[0] if conv.shortlist else None
        if first is None:
            await self._say(conv, "no_vendors")
            return
        if self.settings.pilot_dial_blocked(self.settings.vendor_dial_number(first.phone)):
            await self._cancel(conv, "test_mode_blocked", state=State.FAILED)
            return
        sl = conv.slots
        book = bool(sl.book_intent and sl.exact_time and sl.budget_inr)

        def fn(c: Conv) -> None:
            c.mode = "book" if book else "quote_only"
            c.state = State.QUEUED
            for v in c.shortlist:
                v.status, v.outcome, v.attempts, v.task_id = VStatus.PENDING, None, 0, None

        conv = await self.store.mutate(conv.id, fn) or conv
        now = self.clock.now()
        if self._window_ok(now):
            await self._say(conv, "calling")
        else:
            when = self._time_phrase(self._next_window(now), conv.lang, now)
            await self._say(conv, "queued", when=when)
            def flag(c: Conv) -> None:
                c.extra["queued_msg"] = True

            await self.store.mutate(conv.id, flag)
        await self._pump(conv.id)

    def _time_phrase(self, dt: datetime, lang: str, now: datetime) -> str:
        local = to_ist(dt)
        days = (local.date() - to_ist(now).date()).days
        day = {
            "en": ("today", "tomorrow"), "hinglish": ("aaj", "kal"), "hi": ("आज", "कल")
        }[lang][min(max(days, 0), 1)] if days in (0, 1) else DAYS[lang][local.weekday()]
        h12 = local.hour % 12 or 12
        mm = f":{local.minute:02d}" if local.minute else ""
        suffix = {"en": f"{h12}{mm} {'AM' if local.hour < 12 else 'PM'}",
                  "hinglish": f"{'subah' if local.hour < 12 else 'shaam'} {h12}{mm} baje",
                  "hi": f"{'सुबह' if local.hour < 12 else 'शाम'} {h12}{mm} बजे"}[lang]
        return f"{day} {suffix}"

    async def _redo(self, user: User, conv: Conv, *, same: bool) -> None:
        if same:
            if conv.redo_count >= 1:
                await self._say(conv, "no_more_vendors")
                return

            def fn(c: Conv) -> None:
                c.redo_count += 1
                c.state = State.CONFIRMING

            conv = await self.store.mutate(conv.id, fn) or conv
            await self._go(user, conv)
            return
        shown = {v.place_id for v in conv.shortlist}

        def fn2(c: Conv) -> None:
            c.state = State.CONFIRMING
            c.delivery = None

        conv = await self.store.mutate(conv.id, fn2) or conv
        await self._search(conv, user, exclude=shown | {v.place_id for v in conv.alternates[:0]})

    # ------------------------------------------------------------------ the call pump
    async def _pump(self, conv_id: str) -> None:
        """Advance a conversation: place due calls, schedule the retry pass, or finish.
        Safe to call any number of times (claim-then-act under compare-and-set)."""
        got = await self.store.get(conv_id)
        if got is None:
            return
        conv = got[0]
        if conv.state == State.BOOKING:
            await self._pump_booking(conv)
            return
        if conv.state not in (State.QUEUED, State.CALLING):
            return
        now = self.clock.now()
        claims: list[tuple[int, str]] = []
        action: dict[str, Any] = {"finish": False}

        def fn(c: Conv) -> None:
            claims.clear()
            action["finish"] = False
            if c.state not in (State.QUEUED, State.CALLING):
                return
            inflight = sum(1 for v in c.shortlist if v.status == VStatus.CALLING)
            stop_book = c.mode == "book" and any(
                v.outcome == Outcome.BOOKED for v in c.shortlist
            )
            first_pass = [
                i for i, v in enumerate(c.shortlist)
                if v.status == VStatus.PENDING and v.attempts == 0
            ]
            if stop_book:
                for v in c.shortlist:
                    if v.status == VStatus.PENDING:
                        v.status = VStatus.DONE
                first_pass = []
            retry_pool = [
                i for i, v in enumerate(c.shortlist)
                if v.status == VStatus.PENDING and v.attempts == 1
                and v.outcome is not None and v.outcome.retryable
            ]
            if not first_pass and inflight == 0 and retry_pool:
                for i in retry_pool:
                    v = c.shortlist[i]
                    if v.next_try_at is None:
                        v.next_try_at = now + timedelta(
                            minutes=self.settings.quotes_retry_after_min
                        )
            due = list(first_pass) + [
                i for i in retry_pool
                if not first_pass and c.shortlist[i].next_try_at is not None
                and c.shortlist[i].next_try_at <= now
            ]
            waiting = [
                i for i in retry_pool
                if c.shortlist[i].next_try_at is not None and c.shortlist[i].next_try_at > now
            ]
            if not (first_pass or inflight or retry_pool):
                if all(v.status == VStatus.DONE for v in c.shortlist):
                    c.state = State.AWAITING_BOOK  # finish() decides the final state
                    action["finish"] = True
                return
            slots = max(1, min(3, self.settings.quotes_max_concurrent_calls)) - inflight
            if due and slots > 0 and self._window_ok(now) and not is_paused(self.settings):
                for i in due[:slots]:
                    v = c.shortlist[i]
                    v.status, v.attempts = VStatus.CALLING, v.attempts + 1
                    v.task_id, v.claimed_at, v.next_try_at = new_id(), now, None
                    claims.append((i, v.task_id))
                c.state = State.CALLING
                return
            if inflight:
                c.state = State.CALLING
                return
            c.state = State.QUEUED
            if due or first_pass:  # waiting for the calling window / kill switch
                c.queued_until = (
                    now + timedelta(minutes=5)
                    if is_paused(self.settings)
                    else self._next_window(now)
                )
            elif waiting:
                c.queued_until = min(c.shortlist[i].next_try_at for i in waiting)  # type: ignore[type-var]

        conv = await self.store.mutate(conv_id, fn)
        if conv is None:
            return
        if action["finish"]:
            await self._finish(conv_id)
            return
        for i, task_id in list(claims):
            await self._place(conv_id, i, task_id)
        if not claims:
            return
        return

    async def _place(self, conv_id: str, idx: int, task_id: str) -> None:
        got = await self.store.get(conv_id)
        if got is None:
            return
        conv = got[0]
        v = conv.shortlist[idx]
        try:
            await self._calls().place(conv, v, now=self.clock.now(), task_id=task_id)
        except PlaybookError:
            await self._record(conv_id, task_id, Outcome.FAILED, None, [])
        except Exception as e:  # noqa: BLE001 - never leave a vendor stuck as "calling"
            log.warning("quotes: placing a call failed: %s", type(e).__name__)
            await self._record(conv_id, task_id, Outcome.FAILED, None, [])

    # ------------------------------------------------------------------ call results
    async def on_task_status(self, event: TaskStatusChanged) -> None:
        if not self.enabled:
            return
        if event.new not in TERMINAL and event.new != TaskStatus.SCHEDULED:
            return
        for conv, _ in await self.store.list_active():
            if conv.user_id != event.user_id:
                continue
            if conv.vendor_by_task(event.task_id) or conv.book_task_id == event.task_id:
                async with self._hold(conv.user_id):
                    await self._settle(conv.id, event.task_id)
                return

    async def _settle(self, conv_id: str, task_id: str) -> None:
        rep = await self._calls().report(task_id)
        if not rep.finished:
            if rep.deferred:  # the vendor is closed right now: do not wait for them
                await self._calls().cancel(task_id)
                await self._record(conv_id, task_id, Outcome.CLOSED, None, [])
            return
        await self._record(conv_id, task_id, rep.outcome or Outcome.FAILED, rep.price_inr, rep.slots)

    async def _record(
        self, conv_id: str, task_id: str, outcome: Outcome, price: int | None, slots: list[str]
    ) -> None:
        booking = {"hit": False}

        def fn(c: Conv) -> None:
            booking["hit"] = False
            if c.book_task_id == task_id and c.state == State.BOOKING:
                booking["hit"] = True
                c.extra["book_outcome"] = outcome.value
                if price is not None:
                    c.extra["book_price"] = price
                return
            v = c.vendor_by_task(task_id)
            if v is None or v.status == VStatus.DONE:
                return  # unknown or already recorded (duplicate event): idempotent
            v.outcome, v.price_inr, v.slots = outcome, price, slots
            v.status = VStatus.PENDING if (outcome.retryable and v.attempts < 2) else VStatus.DONE
            if v.status == VStatus.DONE:
                v.claimed_at = None

        conv = await self.store.mutate(conv_id, fn)
        if conv is None:
            return
        if booking["hit"]:
            await self._booking_done(conv_id)
        else:
            await self._pump(conv_id)

    # ------------------------------------------------------------------ result message
    def _quotes(self, conv: Conv) -> list[tuple[int, Vendor]]:
        q = [(i, v) for i, v in enumerate(conv.shortlist) if v.outcome == Outcome.QUOTE]
        return sorted(q, key=lambda x: (x[1].price_inr is None, x[1].price_inr or 0))

    async def _finish(self, conv_id: str) -> None:
        got = await self.store.get(conv_id)
        if got is None:
            return
        conv = got[0]
        if conv.delivery and conv.delivery.kind == "comparison":
            return  # already built (duplicate finish)
        lang = conv.lang
        vendors = conv.shortlist
        booked = next((v for v in vendors if v.outcome == Outcome.BOOKED), None)
        now = self.clock.now()
        if booked is not None:
            text = M.msg(
                "booked", lang, name=booked.name, when=self._book_when(conv, lang, now),
                price=booked.price_inr or conv.slots.budget_inr or "-",
            )
            await self._deliver(conv, text, [], "booking", final_state=State.DONE)
            return
        quotes = self._quotes(conv)
        no_ans = sum(1 for v in vendors if v.outcome in (Outcome.NO_ANSWER, Outcome.FAILED, Outcome.CLOSED))
        refused = sum(
            1 for v in vendors
            if v.outcome in (Outcome.DECLINED, Outcome.WRONG_NUMBER, Outcome.DNC, Outcome.NO_SLOT)
        )
        if not quotes:
            if all(v.outcome == Outcome.BLOCKED for v in vendors):
                text = M.msg("test_mode_blocked", lang)
                await self._deliver(conv, text, [], "note", final_state=State.FAILED)
                return
            why_key = (
                "why_no_answer" if no_ans and not refused
                else "why_declined" if refused and not no_ans else "why_mixed"
            )
            text = M.msg("none_worked", lang, why=M.msg(why_key, lang))
            buttons = []
            if conv.redo_count < 1 and no_ans:
                buttons.append((f"{BTN}:{conv.id}:retry", M.msg("btn_retry", lang)))
            buttons.append((f"{BTN}:{conv.id}:others", M.msg("btn_others", lang)))
            await self._deliver(conv, text, buttons, "comparison", final_state=State.AWAITING_BOOK)
            return
        lines = [
            M.msg("comparison_head", lang,
                  services=M.services_text(conv.slots.services, lang),
                  when=_when_words(conv, lang) or "-")
        ]
        for _, v in quotes:
            if v.price_inr is not None:
                lines.append(M.msg("quote_line", lang, name=v.name, price=v.price_inr))
            else:
                lines.append(M.msg("unpriced_line", lang, name=v.name))
        if no_ans:
            lines.append(M.msg("no_answer_tail", lang, n=no_ans))
        if refused:
            lines.append(M.msg("declined_tail", lang, n=refused))
        buttons = self._book_buttons(conv)
        if buttons:
            lines.append(M.msg("book_prompt", lang))
        await self._deliver(
            conv, "\n".join(lines), buttons, "comparison",
            final_state=State.AWAITING_BOOK if buttons else State.DONE,
        )

    def _book_buttons(self, conv: Conv, exclude: set[int] | None = None) -> list[tuple[str, str]]:
        out = []
        label = ""
        if conv.slots.exact_time and conv.slots.when_start:
            label = _time_label(conv.slots.when_start, conv.lang, self.clock.now())
            label = label.split(" ", 1)[1]  # "6 PM" (the day is in the header)
        for i, v in self._quotes(conv):
            if v.price_inr is None or (exclude and i in exclude):
                continue
            prefix = M.msg("book_btn", conv.lang, name="{n}", time=label).strip()
            room = 20 - len(prefix.replace("{n}", ""))
            title = prefix.replace("{n}", short_name(v.name, max(room, 4)))
            out.append((f"{BTN}:{conv.id}:book:{i}", title[:20]))
            if len(out) == 3:
                break
        return out

    def _book_when(self, conv: Conv, lang: str, now: datetime) -> str:
        if conv.book_when_text:
            return conv.book_when_text
        if conv.slots.exact_time and conv.slots.when_start:
            return _time_label(conv.slots.when_start, lang, now)
        return _when_words(conv, lang)

    async def _deliver(
        self, conv: Conv, text: str, buttons: list[tuple[str, str]], kind: str, *,
        final_state: State,
    ) -> None:
        """Send the result over WhatsApp and record how it went; the SMS fallback is decided
        here (send failed) and in ``tick`` (no delivery receipt after N minutes)."""
        now = self.clock.now()
        d = Delivery(text=text, buttons=buttons, kind=kind)

        def fn(c: Conv) -> None:
            c.state, c.delivery, c.final_text = final_state, d, text
            c.asking = None

        conv = await self.store.mutate(conv.id, fn) or conv
        user = await self._user(conv.user_id)
        if user is None:
            return
        receipt = await self._wa_send(user, text, buttons)

        def mark(c: Conv) -> None:
            if c.delivery is None:
                return
            c.delivery.sent_at = now
            if receipt is not None and receipt.ok:
                c.delivery.provider_id = receipt.provider_message_id
            else:
                c.delivery.failed = True

        conv = await self.store.mutate(conv.id, mark) or conv
        if conv.delivery and conv.delivery.failed:
            await self._sms_fallback(conv.id)

    async def _wa_send(self, user: User, text: str, buttons: list[tuple[str, str]]) -> Any:
        notifier = self._opt("notifier")
        if notifier is None:
            return None
        msg = OutboundMessage(
            channel=Channel.WHATSAPP,
            to_phone=user.phone,
            user_id=user.id,
            text=text,
            buttons=[ReplyButton(id=i, title=t[:20]) for i, t in buttons][:3],
        )
        try:
            return await notifier.send(msg, sms_fallback=False)
        except Exception as e:  # noqa: BLE001
            log.warning("quotes: result send raised %s", type(e).__name__)
            return None

    # ------------------------------------------------------------------ delivery fallbacks
    async def _sms_fallback(self, conv_id: str) -> None:
        if not self.settings.quotes_sms_fallback:
            return
        got = await self.store.get(conv_id)
        if got is None or got[0].delivery is None or got[0].delivery.sms_sent:
            return
        conv = got[0]
        notifier = self._opt("notifier")
        user = await self._user(conv.user_id)
        if notifier is None or user is None:
            return
        line = self._sms_line(conv)
        try:
            receipt = await notifier.send_sms(
                user.phone, TemplateRef(key="user_task_update", params=[line]), user_id=user.id
            )
        except Exception as e:  # noqa: BLE001
            log.warning("quotes: sms fallback raised %s", type(e).__name__)
            return
        if receipt is not None and receipt.ok:
            def fn(c: Conv) -> None:
                if c.delivery:
                    c.delivery.sms_sent = True

            await self.store.mutate(conv.id, fn)
        else:
            log.error("quotes: undeliverable result for user %s (sms failed)", conv.user_id)

    def _sms_line(self, conv: Conv) -> str:
        """DLT variable: 30 characters, so only the headline."""
        q = [x for x in self._quotes(conv) if x[1].price_inr is not None]
        if conv.delivery and conv.delivery.kind == "booking":
            b = next((v for v in conv.shortlist if v.outcome == Outcome.BOOKED), None)
            line = f"Booked {b.name}" if b else "Booking done"
        elif q:
            v = q[0][1]
            line = f"{short_name(v.name, 14)} Rs {v.price_inr} +{len(q) - 1}" if len(q) > 1 else (
                f"{short_name(v.name, 16)} Rs {v.price_inr}"
            )
        else:
            line = "No quotes. Open WhatsApp"
        return line[:30]

    async def on_delivery_status(
        self, provider_id: str, status: str, error: str | None = None
    ) -> None:
        if not self.enabled or not provider_id:
            return
        for conv, _ in await self.store.list_awaiting_delivery():
            d = conv.delivery
            if d is None or d.provider_id != provider_id:
                continue
            if status in ("delivered", "read"):
                def fn(c: Conv) -> None:
                    if c.delivery:
                        c.delivery.delivered = True

                await self.store.mutate(conv.id, fn)
            elif status == "failed":
                def fn2(c: Conv) -> None:
                    if c.delivery:
                        c.delivery.failed = True

                await self.store.mutate(conv.id, fn2)
                await self._sms_fallback(conv.id)
            return

    # ------------------------------------------------------------------ booking
    async def _book(self, user: User, conv: Conv, idx: int) -> None:
        if idx >= len(conv.shortlist) or conv.shortlist[idx].price_inr is None:
            await self._say(conv, "stale")
            return
        sl = conv.slots
        if not (sl.exact_time and sl.when_start):
            def ask(c: Conv) -> None:
                c.asking, c.book_vendor = "book_time", idx

            await self.store.mutate(conv.id, ask)
            await self._say(conv, "ask_book_time")
            return
        await self._start_booking(user, conv, idx, sl.when_text or "")

    async def _book_text(self, user: User, conv: Conv, text: str) -> bool:
        if conv.asking == "book_time" and conv.book_vendor is not None:
            phrase, start, end, exact, _day = P.canonical_when(text, self.clock.now())
            if not exact or not phrase:
                await self._say(conv, "ask_book_time")
                return True
            day = (conv.slots.when_text or "kal").split(" ")[0]
            if day not in ("aaj", "kal", "parso"):
                day = "kal"
            if not re.match(r"(aaj|kal|parso)", phrase):
                phrase = f"{day} {phrase}"
            await self._start_booking(user, conv, conv.book_vendor, phrase, start)
            return True
        m = re.match(r"^\s*(?:book\s*)?(\d)\s*$", text, re.I)
        if m:
            quotes = [i for i, v in self._quotes(conv) if v.price_inr is not None]
            n = int(m.group(1)) - 1
            if 0 <= n < len(quotes):
                await self._book(user, conv, quotes[n])
                return True
        if P.YES_RE.match(text) or P.CHANGE_RE.match(text):
            await self._say(conv, "tap_choice", buttons=self._book_buttons(conv))
            return True
        return False

    async def _start_booking(
        self, user: User, conv: Conv, idx: int, when_text: str, when_start: datetime | None = None
    ) -> None:
        v = conv.shortlist[idx]
        ceiling = v.price_inr
        try:
            self._calls().check_booking(when_text, ceiling, self.clock.now())
        except PlaybookError:
            await self._say(conv, "ask_book_time")
            def ask(c: Conv) -> None:
                c.asking, c.book_vendor = "book_time", idx

            await self.store.mutate(conv.id, ask)
            return
        task_id = new_id()

        def fn(c: Conv) -> None:
            c.state, c.asking = State.BOOKING, None
            c.book_vendor, c.book_task_id = idx, task_id
            c.book_when_text, c.book_ceiling = when_text, ceiling
            c.extra.pop("book_outcome", None)
            c.extra["book_placed"] = False
            c.extra["book_claimed_at"] = None
            if when_start is not None:
                c.extra["book_start"] = when_start.isoformat()

        conv = await self.store.mutate(conv.id, fn) or conv
        await self._say(
            conv, "book_calling", name=v.name, when=self._book_when(conv, conv.lang, self.clock.now())
        )
        await self._pump_booking(conv)

    async def _pump_booking(self, conv: Conv) -> None:
        if conv.extra.get("book_placed") or conv.state != State.BOOKING:
            return
        now = self.clock.now()
        if not self._window_ok(now) or is_paused(self.settings):
            return  # tick() places it when the calling window opens / the pause ends
        claimed = {"ok": False}

        def fn(c: Conv) -> None:
            claimed["ok"] = False
            if c.state == State.BOOKING and not c.extra.get("book_placed"):
                c.extra["book_placed"] = True
                c.extra["book_claimed_at"] = now.isoformat()
                claimed["ok"] = True

        conv = await self.store.mutate(conv.id, fn) or conv
        if not claimed["ok"] or conv.book_vendor is None or conv.book_task_id is None:
            return
        v = conv.shortlist[conv.book_vendor]
        try:
            await self._calls().place_booking(
                conv, v, when_text=conv.book_when_text or "", ceiling=conv.book_ceiling or 0,
                now=now, task_id=conv.book_task_id,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("quotes: booking call failed to start: %s", type(e).__name__)
            await self._record(conv.id, conv.book_task_id, Outcome.FAILED, None, [])

    async def _booking_done(self, conv_id: str) -> None:
        got = await self.store.get(conv_id)
        if got is None or got[0].state != State.BOOKING:
            return
        conv = got[0]
        v = conv.shortlist[conv.book_vendor or 0]
        outcome = Outcome(conv.extra.get("book_outcome", Outcome.FAILED.value))
        lang = conv.lang
        now = self.clock.now()
        if outcome == Outcome.BOOKED:
            price = conv.extra.get("book_price") or conv.book_ceiling or "-"
            text = M.msg("booked", lang, name=v.name, when=self._book_when(conv, lang, now), price=price)
            await self._deliver(conv, text, [], "booking", final_state=State.DONE)
            return
        why = {
            Outcome.NO_SLOT: "bwhy_no_slot", Outcome.PRICE_TOO_HIGH: "bwhy_price",
            Outcome.NO_ANSWER: "bwhy_no_answer", Outcome.CLOSED: "bwhy_no_answer",
        }.get(outcome, "bwhy_other")
        text = M.msg("book_failed", lang, name=v.name, why=M.msg(why, lang))
        others = self._book_buttons(conv, exclude={conv.book_vendor or 0})
        await self._deliver(conv, text, others, "booking",
                            final_state=State.AWAITING_BOOK if others else State.DONE)

    # ------------------------------------------------------------------ status / cancel / stop
    async def _status(
        self, user: User, latest: tuple[Conv, int] | None, pid: str | None
    ) -> bool:
        if latest is None:
            stub = Conv(user_id=user.id, lang=await self._profile_lang(user))
            await self._say(stub, "status_none")
            return True
        conv = latest[0]
        await self._remember(conv.id, pid)
        if conv.delivery and conv.delivery.text:
            btns = conv.delivery.buttons if conv.state == State.AWAITING_BOOK else []
            await self._send_text(conv, conv.delivery.text, btns)
            return True
        if conv.state.active:
            await self._say(conv, "status_working")
            return True
        await self._say(conv, "status_none")
        return True

    async def _cancel_tasks(self, conv: Conv) -> None:
        for v in conv.shortlist:
            if v.task_id and v.status == VStatus.CALLING:
                await self._calls().cancel(v.task_id)
        if conv.book_task_id and conv.state == State.BOOKING:
            await self._calls().cancel(conv.book_task_id)

    async def _cancel(self, conv: Conv, key: str | None, *, state: State = State.CANCELLED) -> None:
        await self._cancel_tasks(conv)

        def fn(c: Conv) -> None:
            c.state = state
            for v in c.shortlist:
                if v.status != VStatus.DONE:
                    v.status = VStatus.DONE

        await self.store.mutate(conv.id, fn)
        if key:
            await self._say(conv, key)

    async def _stop_all(self, user: User, conv: Conv) -> None:
        """'stop' stops everything: this request and any other open one of the user."""
        for other, _ in await self.store.list_active():
            if other.user_id == user.id:
                await self._cancel(other, None)
        await self._say(conv, "stopped")
        with contextlib.suppress(Exception):
            await self.c.repos.audit.log("quotes.stop", user_id=user.id, actor="user")

    # ------------------------------------------------------------------ periodic work
    async def tick(self) -> None:
        """Resume interrupted work (restart safe) and run the timers: queued calls, retries,
        stale conversations, the delivery fallbacks."""
        if not self.enabled:
            return
        now = self.clock.now()
        for conv, _ in await self.store.list_active():
            try:
                async with self._hold(conv.user_id):
                    await self._tick_one(conv.id, now)
            except Exception:  # noqa: BLE001 - one bad conversation never stops the others
                log.exception("quotes tick failed for conversation %s", conv.id)
        try:
            await self._tick_delivery(now)
        except Exception:  # noqa: BLE001
            log.exception("quotes delivery tick failed")

    async def _tick_one(self, conv_id: str, now: datetime) -> None:
        got = await self.store.get(conv_id)
        if got is None:
            return
        conv = got[0]
        stale = timedelta(hours=self.settings.quotes_stale_hours)
        if conv.state in (State.COLLECTING, State.CONFIRMING) and now - conv.last_user_at > stale:
            await self._cancel(conv, None)
            return
        if conv.state in (State.QUEUED, State.CALLING):
            for v in conv.shortlist:
                if v.status != VStatus.CALLING or not v.task_id:
                    continue
                await self._settle(conv_id, v.task_id)
                got2 = await self.store.get(conv_id)
                if got2 is None:
                    return
                v2 = got2[0].vendor_by_task(v.task_id)
                if v2 and v2.status == VStatus.CALLING and v2.claimed_at is not None:
                    age = now - v2.claimed_at
                    if age > timedelta(minutes=VENDOR_TIMEOUT_MIN):
                        await self._calls().cancel(v.task_id)
                        await self._record(conv_id, v.task_id, Outcome.FAILED, None, [])
            await self._pump(conv_id)
        elif conv.state == State.BOOKING:
            if conv.book_task_id and conv.extra.get("book_placed"):
                await self._settle(conv_id, conv.book_task_id)
            await self._pump_booking(conv)

    async def _tick_delivery(self, now: datetime) -> None:
        wait = timedelta(minutes=self.settings.quotes_delivery_receipt_wait_min)
        for conv, _ in await self.store.list_awaiting_delivery():
            d = conv.delivery
            if d is None or d.sent_at is None or d.delivered or d.sms_sent:
                continue
            if d.failed or now - d.sent_at >= wait:
                await self._sms_fallback(conv.id)
        for conv, _ in await self.store.list_awaiting_delivery():
            d = conv.delivery
            if (
                d and d.sent_at and d.sms_sent and not d.delivered and not d.voice_requested
                and self.settings.quotes_voice_fallback and now - d.sent_at >= 2 * wait
            ):
                def fn(c: Conv) -> None:
                    if c.delivery:
                        c.delivery.voice_requested = True

                await self.store.mutate(conv.id, fn)
                with contextlib.suppress(Exception):
                    await self.c.repos.audit.log(
                        "quotes.voice_callback_requested", user_id=conv.user_id, actor="friday"
                    )
