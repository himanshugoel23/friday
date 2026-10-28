# ruff: noqa: E501
"""Live wiring of the trip timeline, refund tracking and family Drive (web-test audit, 2026-10-28).

Those three were complete as modules but nothing in the live message path called them. This file is
the whole connection, small on purpose:

    chat text / button tap  --InboundPipeline._active--> LiveFeatures.handle  (trip:*, refund:* ids, commands)
    document confirmed      --DocumentService doc_sink--> LiveFeatures.on_document_confirmed (build the trip)
    task finished           --bus TaskStatusChanged-----> trips.mark_engine_task_finished / refunds.on_followup_finished
    scheduler               --Runtime loop--------------> LiveFeatures.tick  (trip nudges, refund reminders)
    outbound                --notifier.notify_user------> whatever channel is live (WhatsApp, or the web chat)

Nothing is built unless one of FRIDAY_TRIPS_ENABLED / FRIDAY_REFUNDS_ENABLED / FRIDAY_FAMILY_DRIVE_ENABLED
is on. No provider is chosen for flight status (``status=None``: the watch simply does not run).
Every handler is best-effort: a failure here is logged and the message carries on to the normal chat.
"""

from __future__ import annotations

import re
from typing import Any

from friday.core.events import TaskStatusChanged
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, ReplyButton, User

log = get_logger(__name__)

TICK_S = 60.0
_DRIVE_STATUS = re.compile(r"^\W*(my\s+)?(family\s+)?drive(\s+status)?\W*$|\bdrive\s+(juda|connected|status)\b", re.I)
_DRIVE_WHERE = re.compile(
    r"\bwhere\s+is\s+my\s+(?P<q1>[\w .'-]{2,60})$|^\W*(?:mera|meri|mere)\s+(?P<q2>[\w .'-]{2,60}?)\s+kahan\s+(?:hai|rakha)\b", re.I
)


_ADD_FLIGHT = re.compile(
    r"^\s*add\s+flight\s+(?P<no>[A-Za-z0-9]{2,8})\s+(?P<o>[A-Za-z]{3})\s+(?P<d>[A-Za-z]{3})\s+"
    r"(?P<dep>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(?:\s+arr\s+(?P<arr>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}))?\s*$",
    re.I,
)  # typed fallback while no document reader (vision provider) is chosen: "add flight EX101 DEL BOM 2026-11-14 18:30"


class _EnginePort:
    """Starts a Friday task for a trip / refund proposal the user approved. The engine is looked up
    on use, so build order does not matter; ``approved=False`` makes the engine ask again before it
    dials and the CallGate still applies."""

    def __init__(self, pipeline: Any, *, lines_gate: bool) -> None:
        self.p, self._gate = pipeline, lines_gate

    async def create_task(self, user_id: str, spec: Any, *, approved: bool = False) -> str:
        if self._gate:
            from friday.refunds import copy as refund_copy
            from friday.refunds.ports import LinesPending

            if refund_copy.CALL_LINE_STATUS != "APPROVED":
                raise LinesPending("refund follow-up call lines are PENDING_FOUNDER_APPROVAL")
        engine = self.p.engine()
        if engine is None:
            raise RuntimeError("task engine not available")
        task = await engine.create_task(user_id, spec, approved=approved)
        return str(task.id)


class _Sender:
    """TripSender / RefundSender over the live notifier (so the web chat gets them too)."""

    def __init__(self, pipeline: Any) -> None:
        self.p = pipeline

    async def send(self, user_id: str, message: Any) -> bool:
        buttons = [ReplyButton(id=b.id, title=b.label[:20]) for b in list(message.buttons)[:3]]
        receipt = await self.p.notifier.notify_user(user_id, message.text, buttons=buttons)
        return bool(getattr(receipt, "ok", False))


class LiveFeatures:
    def __init__(self, pipeline: Any) -> None:
        self.p = pipeline
        self.c = pipeline.c
        s = self.c.settings
        repos = self.c.repos
        self.trips: Any = None
        self.refunds: Any = None
        self.drive: Any = None
        self.trip_cmds: Any = None
        self.refund_cmds: Any = None
        if s.refunds_enabled and repos.refunds is not None:
            from friday.refunds.commands import RefundCommands
            from friday.refunds.service import RefundService

            self.refunds = RefundService(
                s, repos.refunds, self.c.clock, sender=_Sender(pipeline),
                tasks=_EnginePort(pipeline, lines_gate=True),
            )  # fmt: skip
            self.refund_cmds = RefundCommands(self.refunds)
        if s.trips_enabled and repos.trips is not None:
            from friday.trips.commands import TripCommands
            from friday.trips.service import TripService

            self.trips = TripService(
                s, repos.trips, self.c.clock, docs=repos.documents, sender=_Sender(pipeline),
                tasks=_EnginePort(pipeline, lines_gate=False), status=None, refunds=self.refunds,
            )  # fmt: skip
            self.trip_cmds = TripCommands(self.trips)
        if s.family_drive_enabled and repos.family_drive is not None:
            try:
                from friday.familydrive.factory import build_family_drive

                self.drive = build_family_drive(s, repos, clock=self.c.clock)
            except Exception:  # noqa: BLE001 - Drive must never stop the app from booting
                log.exception("family drive failed to build; continuing without it")

    @property
    def any(self) -> bool:
        return any(x is not None for x in (self.trips, self.refunds, self.drive))

    # ------------------------------------------------------------------ bus
    def subscribe(self) -> None:
        if self.trips is not None or self.refunds is not None:
            self.c.bus.subscribe(TaskStatusChanged, self.on_task_status)

    def unsubscribe(self) -> None:
        self.c.bus.unsubscribe(TaskStatusChanged, self.on_task_status)

    async def on_task_status(self, event: TaskStatusChanged) -> None:
        """A task Friday ran for a trip / refund follow-up has finished: link it back."""
        if not event.new.is_terminal:
            return
        try:
            items: list[Any] = []
            store = getattr(self.c.repos, "evidence", None)
            if store is not None:
                items = await store.list_for_task(event.user_id, event.task_id)
            if self.trips is not None:
                await self.trips.mark_engine_task_finished(
                    event.user_id, event.task_id, evidence_ids=[i.id for i in items]
                )
            if self.refunds is not None:
                await self.refunds.on_followup_finished(event.user_id, event.task_id, items)
        except Exception:  # noqa: BLE001
            log.warning("trip/refund task link failed: %s", event.task_id, exc_info=True)

    # ------------------------------------------------------------------ documents -> trips
    async def on_document_confirmed(self, user_id: str, doc: Any) -> str | None:
        """A flight / train / hotel document was just confirmed: build or extend the trip. Returns
        the message to add to the confirmation, or None."""
        from friday.docunderstand.models import DocType

        if self.trips is None or not self.trips.enabled_for(user_id):
            return None
        if doc.doc_type not in (DocType.FLIGHT, DocType.TRAIN, DocType.HOTEL):
            return None
        try:
            res = await self.trips.create_from_documents(user_id, [doc.id])
        except Exception:  # noqa: BLE001
            log.warning("trip build from a confirmed document failed", exc_info=True)
            return None
        if not res.new_trip_ids and not res.legs_added:
            return None
        from friday.trips.copy import fmt_date, t

        trip = next((x for x in res.trips if x.id in res.new_trip_ids), res.trips[0] if res.trips else None)
        if trip is None:
            return None
        return t(
            "created", self.trips.lang, title=trip.title, start=fmt_date(trip.start_date),
            end=fmt_date(trip.end_date), n=res.legs_added,
        )  # fmt: skip

    # ------------------------------------------------------------------ chat
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        """True when the message was a trip / refund / Drive command or button (answered here)."""
        try:
            return await self._handle(user, msg)
        except Exception:  # noqa: BLE001 - never block the normal chat
            log.warning("live feature handler failed", exc_info=True)
            return False

    async def _handle(self, user: User, msg: InboundMessage) -> bool:
        reply: Any = None
        if msg.kind == MessageKind.BUTTON_REPLY and msg.button_id:
            bid = msg.button_id
            if bid.startswith("trip:") and self.trip_cmds is not None:
                reply = await self.trip_cmds.handle_button(user.id, bid)
            elif bid.startswith("refund:") and self.refund_cmds is not None:
                reply = await self.refund_cmds.handle_button(user.id, bid)
        elif msg.kind in (MessageKind.TEXT, MessageKind.VOICE_NOTE) and (msg.text or "").strip():
            text = msg.text.strip()  # type: ignore[union-attr]
            if self.trips is not None and (m := _ADD_FLIGHT.match(text)):
                return await self._add_flight(user, m)
            if self.refund_cmds is not None:
                reply = await self.refund_cmds.handle_text(user.id, text)
            if reply is None and self.trip_cmds is not None:
                reply = await self.trip_cmds.handle_text(user.id, text)
            if reply is None and self.drive is not None:
                return await self._drive(user, text)
        if reply is None:
            return False
        buttons = [ReplyButton(id=b.id, title=b.label[:20]) for b in list(reply.buttons)[:3]]
        await self.p.reply(user, reply.text, buttons)
        return True

    async def _add_flight(self, user: User, m: re.Match[str]) -> bool:
        from friday.docunderstand.models import DocType
        from friday.trips.copy import fmt_date, t

        if not self.trips.enabled_for(user.id):
            return False
        vals = {
            "flight_no": m["no"].upper(), "from_iata": m["o"].upper(), "to_iata": m["d"].upper(),
            "dep_local": m["dep"].replace(" ", "T"),
        }  # fmt: skip
        if m["arr"]:
            vals["arr_local"] = m["arr"].replace(" ", "T")
        res = await self.trips.create_from_user(user.id, DocType.FLIGHT, vals)
        trip = res.trips[0] if res.trips else None
        if trip is None:
            await self.p.reply(user, t("created.none", self.trips.lang), [])
        else:
            await self.p.reply(
                user,
                t("created", self.trips.lang, title=trip.title, start=fmt_date(trip.start_date),
                  end=fmt_date(trip.end_date), n=res.legs_added),
                [],
            )  # fmt: skip
        return True

    async def _drive(self, user: User, text: str) -> bool:
        from friday.familydrive import copy as dc
        from friday.familydrive.ports import DriveError, DriveNeedsReconnect, DriveNotLinked

        where = _DRIVE_WHERE.search(text)
        if not where and not _DRIVE_STATUS.search(text):
            return False
        lang = "hinglish"
        try:
            if where:
                hits = await self.drive.where_is(user.id, where.group("q1") or where.group("q2") or "")
                if not hits:
                    out = dc.t("where.none", lang)
                else:
                    out = "\n".join(dc.t("where.found", lang, name=h.name, link=h.link) for h in hits[:3])
            else:
                info = await self.drive.status(user.id)
                out = {
                    "not_linked": dc.t("not_linked", lang),
                    "needs_reconnect": dc.t("needs_reconnect", lang),
                }.get(info.state, f"Google Drive connected. {info.root_link or ''}".strip())
        except DriveNotLinked:
            out = dc.t("not_linked", lang)
        except DriveNeedsReconnect:
            out = dc.t("needs_reconnect", lang)
        except DriveError:
            out = dc.t("unreachable", lang)
        await self.p.reply(user, out, [])
        return True

    # ------------------------------------------------------------------ scheduler
    async def tick(self) -> None:
        for name, svc in (("trips", self.trips), ("refunds", self.refunds)):
            if svc is None:
                continue
            try:
                await svc.tick()
            except Exception:  # noqa: BLE001
                log.exception("%s tick failed", name)


def build_live_features(pipeline: Any) -> LiveFeatures | None:
    s = pipeline.c.settings
    if not (s.trips_enabled or s.refunds_enabled or s.family_drive_enabled):
        return None
    feats = LiveFeatures(pipeline)
    return feats if feats.any else None


__all__ = ["LiveFeatures", "build_live_features"]
