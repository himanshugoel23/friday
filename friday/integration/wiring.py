"""Builds the consumer stack from the Container, or returns None while every switch is off.

    c.get("consumer")  ->  ConsumerRouter | None

Switches (all default false, names only): ``FRIDAY_CONSUMER_CALLS_ENABLED``,
``FRIDAY_SAVINGS_ENABLED``, ``FRIDAY_LIFESTATE_ENABLED``, ``FRIDAY_GOOGLE_ENABLED``. A switch
that is
off leaves its package unbuilt and its handlers unregistered.

``build_stack`` takes every outside dependency as an argument so tests and the demo can build the
same stack over a SQLite container, a recording sender and a simulated line. In production
``build_consumer`` supplies: the repositories, the notifier, the durable job queue, the lock, the
task engine and the proactive engine of the container. The telephony factory defaults to the one
that REFUSES to open a line. ``build_consumer`` plugs in the production
``ConsumerTelephonyFactory`` (friday/integration/telephony.py) ONLY when the calls switch is on AND
the profile permits (live mode, pilot profile); in every other profile, and in tests and the
simulator, the refusing default (or an explicitly passed fake) stays.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from friday.calls.approval import ApprovalService, parse_button
from friday.calls.contacts import ContactBook
from friday.calls.dnc import DncRegistry
from friday.calls.flow import CallIntake
from friday.calls.gate import CallGate
from friday.calls.numbers import NumberHasher
from friday.calls.orchestrator import CallOrchestrator
from friday.calls.recordings import RecordingService
from friday.calls.settings import CallsSettings
from friday.calls.understand import RequestUnderstander
from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import ReplyButton
from friday.integration.bridge import (
    LiveEngineAdapter,
    LiveOpeningLineProvider,
    RefusingTelephonyFactory,
    TelephonyFactory,
)
from friday.integration.buttons import ButtonRegistry, Handled
from friday.integration.proactive import (
    BillReminderSource,
    LifeBriefingProvider,
    LifeFollowupSource,
    SavingsBillsPort,
)
from friday.integration.router import (
    CallsParts,
    ConsumerRouter,
    GoogleParts,
    LifeParts,
    calendar_port,
)
from friday.integration.taskport import JOB_CONSUMER_CALL, ConsumerJobs, QueueTaskPort, job_handler
from friday.lifestate.capture import undo_last
from friday.lifestate.conversation import LifeContextProvider
from friday.lifestate.followups import FollowupScheduler
from friday.lifestate.memory import MemoryControls
from friday.lifestate.store import LifeStore
from friday.savings.commands import SavingsCommands
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.savings_ledger import SavingsLedger
from friday.savings.store import SavingsRepos

log = get_logger(__name__)

Send = Callable[[str, str, Sequence[ReplyButton]], Awaitable[None]]


class _CallNotifier:
    """``friday.calls.interfaces.UserNotifier`` over the router's send function."""

    def __init__(self, send: Send) -> None:
        self._send = send

    async def send(
        self, user_id: str, text: str, buttons: Sequence[ReplyButton] = (), *, urgent: bool = False
    ) -> None:
        await self._send(user_id, text, buttons)


class _NoSender:
    """The follow-up scheduler is only used for its reply handling here; sending goes through the
    proactive engine, so this one refuses."""

    async def send(self, user_id: str, text: str, **kw: Any) -> bool:
        return False


@dataclass
class Switches:
    calls: bool
    savings: bool
    lifestate: bool
    google: bool

    @classmethod
    def of(cls, s: Settings) -> Switches:
        return cls(
            s.consumer_calls_enabled, s.savings_enabled, s.lifestate_enabled, s.google_enabled
        )

    @property
    def any(self) -> bool:
        return self.calls or self.savings or self.lifestate or self.google


def _profile(repos: Any) -> Callable[[str], Awaitable[tuple[str | None, str]]]:
    async def get(user_id: str) -> tuple[str | None, str]:
        p = await repos.profiles.get_or_default(user_id)
        return p.name, getattr(p.language, "value", str(p.language))

    return get


def build_stack(
    *,
    settings: Settings,
    clock: Clock,
    repos: Any,
    send: Send,
    queue: Any,
    locks: Any = None,
    telephony: TelephonyFactory | None = None,
    calls_settings: CallsSettings | None = None,
    savings_config: SavingsConfig | None = None,
    life_store: LifeStore | None = None,
    http_factory: Any = None,
    recording_deleter: Callable[[str], Awaitable[bool]] | None = None,
    switches: Switches | None = None,
    consumer_line: Callable[..., TelephonyFactory | None] | None = None,
) -> ConsumerRouter | None:
    sw = switches or Switches.of(settings)
    if not sw.any:
        return None
    buttons = ButtonRegistry()
    extras: dict[str, Any] = {}

    # ------------------------------------------------------------------ savings (W3)
    savings: SavingsCommands | None = None
    active_bills: Callable[[str], Awaitable[list[Any]]] | None = None
    if sw.savings:
        cfg = savings_config or DEFAULT_CONFIG
        sr = SavingsRepos(repos.db, clock, cfg)
        savings = SavingsCommands(
            wallet=sr.wallet, rules=sr.rules, bills=sr.bills,
            ledger=SavingsLedger(sr.ledger, clock), clock=clock, config=cfg,
        )  # fmt: skip
        active_bills = sr.bills.active_for_user
        extras["bill_source"] = BillReminderSource(active_bills, clock, cfg)

        async def savings_button(user_id: str, button_id: str) -> Handled | None:
            r = await savings.handle_button(user_id, button_id)  # type: ignore[union-attr]
            return Handled(r.text, r.buttons) if r else Handled()

        buttons.register("led", savings_button)
        buttons.register("bill", savings_button)

    # ------------------------------------------------------------------ life state (W4)
    life: LifeParts | None = None
    if sw.lifestate:
        store: LifeStore = life_store or repos.life
        bills_port = SavingsBillsPort(active_bills) if active_bills else None
        life = LifeParts(
            store=store,
            memory=MemoryControls(store, clock),
            provider=LifeContextProvider(store, settings, bills_port),
            scheduler=FollowupScheduler(store, _NoSender(), settings, clock, bills=bills_port),
            bills=bills_port,
        )
        source = LifeFollowupSource(store, settings, clock, active_bills=active_bills)
        extras["life_source"] = source
        extras["briefing"] = LifeBriefingProvider(store, clock, bills=bills_port)

        async def life_button(user_id: str, button_id: str) -> Handled | None:
            from friday.lifestate import copy as life_copy

            parts = button_id.split(":")
            if len(parts) >= 2 and parts[1] == "undo":
                ok = await undo_last(store, user_id, clock.now())
                return Handled(life_copy.undo_done() if ok else life_copy.undo_nothing())
            return Handled()

        buttons.register("life", life_button)

    # ------------------------------------------------------------------ Google
    google: GoogleParts | None = None
    if sw.google:
        from friday.google.calendar import CalendarClient
        from friday.google.oauth import GoogleOAuth

        def make_oauth() -> GoogleOAuth:
            return GoogleOAuth(settings, repos.google, clock=clock, http=http_factory)

        async def calendar_for(user_id: str) -> Any:
            oauth = make_oauth()
            if not (await oauth.status(user_id)).connected:
                return None
            return calendar_port(
                CalendarClient(oauth, user_id, settings=settings, http=http_factory)
            )

        async def all_users() -> list[str]:
            return [u.id for u in await repos.users.list_active()]

        google = GoogleParts(make_oauth, calendar_for, all_users)

    # ------------------------------------------------------------------ calls (W1 + W2)
    calls: CallsParts | None = None
    if sw.calls:
        cs = calls_settings or CallsSettings()
        hasher = NumberHasher()
        store_c = repos.consumer_calls
        dnc = DncRegistry(repos.call_dnc, hasher, clock)
        gate = CallGate(store=store_c, dnc=dnc, hasher=hasher, settings=cs, core_settings=settings)
        approval = ApprovalService(LiveOpeningLineProvider(), clock)
        if telephony is None and consumer_line is not None:
            # the production line needs the gate, the store and the hasher built just above
            telephony = consumer_line(
                gate=gate, store=store_c, users=repos.users, hasher=hasher, calls_settings=cs
            )
        engine = LiveEngineAdapter(telephony, core_settings=settings, clock=clock)
        tasks = QueueTaskPort(queue, clock)
        recordings = RecordingService(store_c, recording_deleter or _no_deleter, cs, clock)
        orch = CallOrchestrator(
            store=store_c, gate=gate, approval=approval, dnc=dnc, hasher=hasher, engine=engine,
            notifier=_CallNotifier(send), tasks=tasks, users=repos.users, clock=clock,
            settings=cs, recordings=recordings,
        )  # fmt: skip
        book = ContactBook(repos.consumer_contacts, hasher, clock)
        intake = CallIntake(
            understander=RequestUnderstander(), contacts=book, orchestrator=orch, approval=approval
        )
        calls = CallsParts(orch, intake, book, ConsumerJobs(orch, clock, recordings=recordings))
        extras.update(task_port=tasks, engine=engine, job_handler=job_handler(orch, locks))

    router = ConsumerRouter(
        settings=settings, clock=clock, send=send, profile=_profile(repos), buttons=buttons,
        calls=calls, savings=savings, life=life, google=google,
    )  # fmt: skip
    router.extras = extras
    router.line_available = telephony is not None and not isinstance(
        telephony, RefusingTelephonyFactory
    )
    if calls is not None:
        orch_ = calls.orchestrator

        async def call_button(user_id: str, button_id: str) -> Handled | None:
            await orch_.handle_button(user_id, button_id)  # replies go through the notifier
            press = parse_button(button_id)
            if press is not None and press.action == "edit":
                router.expect_edit(user_id, press.request_id)
            return Handled()

        buttons.register("callap", call_button)
        buttons.register("callact", call_button)
    return router


async def _no_deleter(ref: str) -> bool:
    return False  # no object store wired here: the recording stays and is retried by the sweep


def attach(router: ConsumerRouter, *, task_engine: Any = None, proactive: Any = None) -> None:
    """Register the router's pieces on the engines that run them (idempotent)."""
    ex = router.extras
    if task_engine is not None and "job_handler" in ex:
        task_engine.register_job_handler(JOB_CONSUMER_CALL, ex["job_handler"])
    if proactive is not None:
        if "bill_source" in ex:
            proactive.register_source(ex["bill_source"])
        if "life_source" in ex:
            proactive.register_source(ex["life_source"])
            proactive.register_sent_hook(ex["life_source"].on_sent)
        if "briefing" in ex:
            proactive.register_briefing_provider(ex["briefing"])


def build_consumer(c: Any) -> ConsumerRouter | None:
    """The ``consumer`` component: None unless a switch is on."""
    s: Settings = c.settings
    if not Switches.of(s).any:
        return None

    async def send(user_id: str, text: str, buttons: Sequence[ReplyButton]) -> None:
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    def _opt(name: str) -> Any:
        try:
            return c.get(name)
        except Exception:  # noqa: BLE001
            return None

    async def delete_recording(ref: str) -> bool:
        from friday.db.objectstore import delete_recording as _delete

        store = _opt("object_store")
        return bool(store) and await _delete(ref, store=store, telephony=_opt("telephony"))

    def consumer_line(**parts: Any) -> TelephonyFactory | None:
        """The real line, only when live + pilot profile + the calls switch (else the refusing
        default stays and the router says the calling line is not on)."""
        from friday.integration.telephony import (
            ConsumerTelephonyFactory,
            VobizLineOpener,
            line_permitted,
        )

        if not line_permitted(s):
            return None
        return ConsumerTelephonyFactory(
            settings=s, opener=VobizLineOpener(lambda: c.telephony, s), pool=_opt("number_pool"),
            clock=c.clock, **parts,
        )  # fmt: skip

    return build_stack(
        settings=s, clock=c.clock, repos=c.get("repos"), send=send, queue=c.get("job_queue"),
        locks=_opt("lock"), recording_deleter=delete_recording, consumer_line=consumer_line,
    )  # fmt: skip
