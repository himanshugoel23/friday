"""WhatsApp gateway for the project manager: the front door for every non-salon category.

Salon requests keep going through the quotes flow (friday/quotes/flow.py, which runs first in the
inbound pipeline). Everything else that the classifier recognises as a vendor-calling request
comes here. Off by default (``FRIDAY_PM_ENABLED``). The webhook never waits for the PM: each turn
runs as a background task (vendor calls take minutes), and the PM's reply is sent when it is
ready, so nothing depends on the user's phone being online (HANDOFF 2b). The task record is saved
after every step (``JsonFileTaskStore``), so a restart can ``resume`` instead of losing the job.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from friday.core.clock import at_ist, to_ist
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User
from friday.pause import is_paused
from friday.pm.adapters import EnginePlacer, RealStepAgents
from friday.pm.classifier import Classifier, KeywordClassifier
from friday.pm.manager import ProjectManager
from friday.pm.state import TERMINAL, JsonFileTaskStore, Status, TaskStore
from friday.pm.steps import StepContext
from friday.pm.taxonomy import buckets

log = get_logger(__name__)


def call_window_ok(settings: Any, now: datetime) -> bool:
    local = to_ist(now)
    sh, sm = (int(x) for x in settings.quotes_call_window_start.split(":"))
    eh, em = (int(x) for x in settings.quotes_call_window_end.split(":"))
    return at_ist(local.date(), sh, sm) <= now < at_ist(local.date(), eh, em)


class PMGateway:
    def __init__(
        self,
        c: Any,
        *,
        pm: ProjectManager | None = None,
        store: TaskStore | None = None,
        spawn: Callable[[Any], Any] | None = None,
    ) -> None:
        self.c = c
        self.settings = c.settings
        self._store = store
        self._pm = pm
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        self._spawn = spawn  # tests run the turn inline

    # ------------------------------------------------------------------ build
    @property
    def enabled(self) -> bool:
        return bool(getattr(self.settings, "pm_enabled", False))

    def _opt(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except Exception:  # noqa: BLE001
            return None

    @property
    def store(self) -> TaskStore:
        if self._store is None:
            self._store = JsonFileTaskStore(self.settings.pm_store_dir)
        return self._store

    @property
    def pm(self) -> ProjectManager | None:
        if self._pm is None:
            directory, geocoder = self._opt("directory"), self._opt("geocoder")
            if directory is None or geocoder is None or not hasattr(directory, "_request"):
                return None  # only the real Google directory can feed the scouting agents
            self._pm = ProjectManager(
                classifier=self._classifier(),
                agents=self._agents(directory, geocoder),
                store=self.store,
                min_confidence=self.settings.pm_min_confidence,
            )
        return self._pm

    def _classifier(self) -> Classifier:
        try:
            from friday.pm.classifier import LLMClassifier

            llm = self.c.get("llm")
            if getattr(self.settings, "pm_use_llm_classifier", False) and llm is not None:
                return LLMClassifier(llm)
        except Exception:  # noqa: BLE001
            log.info("pm: LLM classifier unavailable, using the keyword baseline")
        return KeywordClassifier()

    def _agents(self, directory: Any, geocoder: Any) -> RealStepAgents:
        from friday.quotes.calls import EngineVendorCalls
        from friday.quotes.finder import VendorFinder
        from friday.scouting.pipeline import scout
        from friday.scouting.reviews import GoogleReviewFetcher
        from friday.scouting.searcher import GeocoderAreaResolver, GooglePlaceSearcher

        searcher = GooglePlaceSearcher(directory, GeocoderAreaResolver(geocoder))
        fetcher = GoogleReviewFetcher(directory)

        async def scout_fn(req):
            return await scout(req, searcher, fetcher, review_budget=6, max_queries=2)

        async def resolve(area: str):
            res = await geocoder.geocode(area)
            return res.location if res else None

        async def policy(ctx: StepContext) -> tuple[bool, str]:
            if is_paused(self.settings):
                return False, "calling is paused"
            if not call_window_ok(self.settings, self.c.clock.now()):
                return False, "outside calling hours"
            return True, ""

        finder = VendorFinder(directory)
        placer = EnginePlacer(EngineVendorCalls(self.c, finder), self.c.clock.now)
        return RealStepAgents(
            scout_fn=scout_fn, resolve_fn=resolve, placer=placer, policy=policy
        )

    # ------------------------------------------------------------------ inbound
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        """True when the gateway took the message."""
        if not self.enabled:
            return False
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        pm = self.pm
        if pm is None:
            return False
        active_for = getattr(self.store, "active_for_user", None)
        active = active_for(user.id) if active_for else None
        channel = "whatsapp_voice" if msg.kind == MessageKind.VOICE_NOTE else "whatsapp_text"
        if active is None:
            first = await pm.classifier.classify(text, channel)
            b = buckets().get(first.bucket)
            if (
                first.category is None
                or first.category == "salon"  # the quotes flow owns salon
                or first.bucket == "other"
                or first.confidence < self.settings.pm_min_confidence
                or b is None
            ):
                return False
        job = self._turn(pm, user, active.id if active else None, text, channel)
        if self._spawn is not None:
            await self._spawn(job)
        else:
            t = asyncio.create_task(job)
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)
        return True

    async def _turn(
        self, pm: ProjectManager, user: User, task_id: str | None, text: str, channel: str
    ) -> None:
        async with self._locks.setdefault(user.id, asyncio.Lock()):
            try:
                reply = await pm.handle_message(
                    text, task_id=task_id, user_id=user.id, channel=channel
                )
            except Exception as e:  # noqa: BLE001 - a crash must not strand the user silently
                log.exception("pm turn crashed: %s", type(e).__name__)
                await self._send(
                    user, "Sorry, kuch gadbad ho gayi. Thodi der mein dobara try kijiye."
                )
                return
            for m in [*reply.messages, *reply.whatsapp]:
                if m:
                    await self._send(user, m)

    async def _send(self, user: User, text: str) -> None:
        notifier = self._opt("notifier")
        if notifier is None:
            return
        try:
            await notifier.notify_user(user.id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("pm: send failed: %s", type(e).__name__)

    async def resume_all(self) -> int:
        """After a restart: continue tasks that were running when the server stopped."""
        pm = self.pm
        store = self.store
        d = getattr(store, "dir", None)
        if pm is None or d is None:
            return 0
        n = 0
        for f in d.glob("*.json"):
            t = store.load(f.stem)
            if t is not None and t.status == Status.RUNNING and t.status not in TERMINAL:
                task = asyncio.create_task(pm.resume(t.id))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                n += 1
        return n
