# ruff: noqa: E501
"""Lane 2 minimum (docs/ROBIN_CONCIERGE_DESK.md section 2): AI -> human handoff record, duty roster / on-call, "human joined".

Flow: Robin (AI) acts within the first minute and hands over a one-screen card (``HandoffCard``). The desk pages the on-call primary;
no ack within ``desk_ack_s`` pages the secondary; no ack from either logs "desk did not answer" and the family ladder simply continues.
When a person JOINS, ``human_joined`` is true for that incident, the AI stops re-ringing (friday/robin asks ``humanport.human_joined``),
and it stays true until the person hands back or closes. Authority calls (112, bank, police) are NOT made here: dry-run until legal review.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from friday.concierge.audit import AuditLog
from friday.concierge.auth import can
from friday.concierge.ports import Pager, StaffAccount, StaffDirectory
from friday.concierge.service import BadState, Denied, DeskSettings, NotFound

FALSE_ALARM_REASONS = ("accidental_press", "test", "misheard_word", "sensor")
OUTCOMES = ("resolved", "false_alarm", "referred_to_family")
REVIEW_WITHIN_S = 24 * 3600
KIND_HANDOFF, KIND_SHIFT = "handoff", "shift"


@dataclass(frozen=True)
class HandoffCard:
    """What Robin hands over. Text is one short line each; no numbers (the desk reaches people through the masked bridge)."""

    incident_id: str
    parent_id: str
    family_id: str
    language: str
    tier: str
    why: str
    signals: tuple[tuple[str, str], ...] = ()  # (signal code, ISO time)
    ai_actions: tuple[str, ...] = ()  # what Robin already said/did, as codes
    rung: tuple[tuple[str, str], ...] = ()  # (who, result code)
    consent_items: tuple[str, ...] = ()  # e.g. "desk_may_call_112", "desk_may_call_bank"


@dataclass
class Shift:
    id: str
    start: datetime
    end: datetime
    primary: str
    secondary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "start": self.start.isoformat(), "end": self.end.isoformat(), "primary": self.primary, "secondary": self.secondary}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shift:
        return cls(d["id"], datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"]), d["primary"], d.get("secondary"))


@dataclass
class Handoff:
    card: dict[str, Any]
    created_at: datetime
    status: str = "open"  # open | paged | acked | joined | handed_back | unanswered | no_desk | closed
    primary: str | None = None
    secondary: str | None = None
    paged_at: datetime | None = None
    secondary_paged_at: datetime | None = None
    acked_by: str | None = None
    joined_by: str | None = None
    joined_at: datetime | None = None
    outcome: str | None = None
    false_alarm_reason: str | None = None
    closed_by: str | None = None
    closed_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    log: list[tuple[str, str]] = field(default_factory=list)  # (ISO time, code) of what the desk did; no text

    def to_dict(self) -> dict[str, Any]:
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {
            "card": self.card, "created_at": iso(self.created_at), "status": self.status, "primary": self.primary, "secondary": self.secondary,
            "paged_at": iso(self.paged_at), "secondary_paged_at": iso(self.secondary_paged_at), "acked_by": self.acked_by, "joined_by": self.joined_by,
            "joined_at": iso(self.joined_at), "outcome": self.outcome, "false_alarm_reason": self.false_alarm_reason, "closed_by": self.closed_by,
            "closed_at": iso(self.closed_at), "reviewed_by": self.reviewed_by, "reviewed_at": iso(self.reviewed_at), "log": [list(x) for x in self.log],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Handoff:
        dt = lambda v: datetime.fromisoformat(v) if v else None  # noqa: E731
        return cls(
            card=d["card"], created_at=dt(d["created_at"]), status=d["status"], primary=d.get("primary"), secondary=d.get("secondary"),  # type: ignore[arg-type]
            paged_at=dt(d.get("paged_at")), secondary_paged_at=dt(d.get("secondary_paged_at")), acked_by=d.get("acked_by"), joined_by=d.get("joined_by"),
            joined_at=dt(d.get("joined_at")), outcome=d.get("outcome"), false_alarm_reason=d.get("false_alarm_reason"), closed_by=d.get("closed_by"),
            closed_at=dt(d.get("closed_at")), reviewed_by=d.get("reviewed_by"), reviewed_at=dt(d.get("reviewed_at")), log=[tuple(x) for x in d.get("log", [])],  # type: ignore[misc]
        )


class DeskService:
    def __init__(self, *, store, audit: AuditLog, clock, directory: StaffDirectory, pager: Pager, settings: DeskSettings | None = None) -> None:  # noqa: ANN001
        self.store, self.audit, self.clock, self.directory, self.pager = store, audit, clock, directory, pager
        self.cfg = settings or DeskSettings()
        self._joined: set[str] = set()  # incident ids with a person on the line (fast path for the AI ladder)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ roster
    async def set_shift(self, lead: StaffAccount, shift: Shift) -> None:
        if not can(lead, "roster.edit"):
            await self.audit.record(lead.id if lead else "unknown", "denied", shift.id, roster=1)
            raise Denied("denied")
        if shift.end <= shift.start or (shift.secondary and shift.secondary == shift.primary):
            raise BadState("bad_shift")
        for sid in filter(None, (shift.primary, shift.secondary)):
            a = await self.directory.get(sid)
            if a is None or not a.active or "emergency" not in a.lanes or not can(a, "desk.join"):
                raise BadState("not_on_lane_2")  # concierge-only staff cannot be rostered
            # a person on the lane 2 roster is never also the sole concierge cover: left to the lead; counted in the audit entry
        await self.store.doc_save(KIND_SHIFT, shift.id, shift.to_dict())
        await self.audit.record(lead.id, "roster_set", shift.id, people=2 if shift.secondary else 1)

    async def shifts(self) -> list[Shift]:
        return sorted((Shift.from_dict(d) for d in await self.store.doc_list(KIND_SHIFT)), key=lambda s: s.start)

    async def on_call(self, now: datetime | None = None) -> tuple[str, str | None] | None:
        now = now or self.clock.now()
        for s in await self.shifts():
            if s.start <= now < s.end:
                return s.primary, s.secondary
        return None

    # ------------------------------------------------------------------ handoff from the AI
    async def _put(self, h: Handoff) -> None:
        await self.store.doc_save(KIND_HANDOFF, h.card["incident_id"], h.to_dict(), parent_id=h.card["parent_id"], status=h.status)

    async def _get(self, incident_id: str) -> Handoff:
        d = await self.store.doc_get(KIND_HANDOFF, incident_id)
        if d is None:
            raise NotFound("not_found")
        return Handoff.from_dict(d)

    def _log(self, h: Handoff, code: str) -> None:
        h.log.append((self.clock.now().isoformat(), code))

    async def receive(self, card: HandoffCard) -> Handoff:
        """Called by the AI side (friday/robin) with the one-screen card. Idempotent per incident. Pages the on-call primary."""
        async with self._lock:
            existing = await self.store.doc_get(KIND_HANDOFF, card.incident_id)
            if existing:
                return Handoff.from_dict(existing)
            now = self.clock.now()
            h = Handoff(card={"incident_id": card.incident_id, "parent_id": card.parent_id, "family_id": card.family_id, "language": card.language, "tier": card.tier, "why": card.why,
                              "signals": [list(x) for x in card.signals], "ai_actions": list(card.ai_actions), "rung": [list(x) for x in card.rung], "consent_items": list(card.consent_items)},
                        created_at=now)
            await self.audit.record("system", "handoff_received", card.incident_id, signals=len(card.signals))
            roster = await self.on_call(now)
            if roster is None:
                h.status = "no_desk"
                self._log(h, "no_one_on_call")  # outside desk hours Robin works alone and says so
                await self.audit.record("system", "desk_no_answer", card.incident_id, no_roster=1)
            else:
                h.primary, h.secondary = roster
                h.status, h.paged_at = "paged", now
                await self.pager.page(h.primary, card.incident_id)
                self._log(h, "primary_paged")
                await self.audit.record("system", "desk_paged", card.incident_id, rank=1)
            await self._put(h)
            return h

    async def tick(self) -> int:
        """Escalate unacked pages: primary -> secondary -> 'desk did not answer'. Returns how many handoffs changed."""
        n, now = 0, self.clock.now()
        async with self._lock:
            for d in await self.store.doc_list(KIND_HANDOFF):
                h = Handoff.from_dict(d)
                if h.status != "paged" or h.paged_at is None:
                    continue
                iid = h.card["incident_id"]
                if h.secondary and h.secondary_paged_at is None and now - h.paged_at >= timedelta(seconds=self.cfg.desk_ack_s):
                    h.secondary_paged_at = now
                    await self.pager.page(h.secondary, iid)
                    self._log(h, "secondary_paged")
                    await self.audit.record("system", "desk_paged", iid, rank=2)
                    n += 1
                elif now - (h.secondary_paged_at or h.paged_at) >= timedelta(seconds=self.cfg.desk_ack_s) and (h.secondary_paged_at or not h.secondary):
                    h.status = "unanswered"
                    self._log(h, "desk_did_not_answer")  # the family ladder continues on its own
                    await self.audit.record("system", "desk_no_answer", iid)
                    n += 1
                else:
                    continue
                await self._put(h)
        return n

    # ------------------------------------------------------------------ the human side
    async def _need(self, staff: StaffAccount, perm: str, target: str) -> None:
        if not can(staff, perm):
            await self.audit.record(staff.id if staff else "unknown", "denied", target, lane2=1)
            raise Denied("denied")

    async def view(self, staff: StaffAccount, incident_id: str) -> Handoff:
        await self._need(staff, "desk.view", incident_id)
        return await self._get(incident_id)

    async def open_handoffs(self, staff: StaffAccount) -> list[Handoff]:
        await self._need(staff, "desk.view", "")
        hs = [Handoff.from_dict(d) for d in await self.store.doc_list(KIND_HANDOFF)]
        return sorted([h for h in hs if h.status not in ("closed",)], key=lambda h: h.created_at)

    async def ack(self, staff: StaffAccount, incident_id: str) -> None:
        await self._need(staff, "desk.join", incident_id)
        async with self._lock:
            h = await self._get(incident_id)
            if h.status not in ("paged", "unanswered", "no_desk"):
                raise BadState("not_ackable")
            h.status, h.acked_by = "acked", staff.id
            self._log(h, "acked")
            await self._put(h)
        await self.audit.record(staff.id, "desk_ack", incident_id, late=int(self.clock.now() - h.created_at > timedelta(seconds=self.cfg.desk_ack_s)))

    async def join(self, staff: StaffAccount, incident_id: str) -> None:
        """A person is now on the line. From here the AI does not re-ring this incident (until hand back / close)."""
        await self._need(staff, "desk.join", incident_id)
        async with self._lock:
            h = await self._get(incident_id)
            if h.status in ("closed", "joined"):
                raise BadState("not_joinable")
            h.status, h.joined_by, h.joined_at = "joined", staff.id, self.clock.now()
            h.acked_by = h.acked_by or staff.id
            self._log(h, "human_joined")
            await self._put(h)
            self._joined.add(incident_id)
        await self.audit.record(staff.id, "human_joined", incident_id, secs_since_alert=int((h.joined_at - h.created_at).total_seconds()))

    async def hand_back(self, staff: StaffAccount, incident_id: str) -> None:
        await self._need(staff, "desk.handback", incident_id)
        async with self._lock:
            h = await self._get(incident_id)
            if h.status != "joined" or h.joined_by != staff.id:
                raise Denied("not_yours")
            h.status = "handed_back"
            self._log(h, "handed_back_to_robin")
            await self._put(h)
            self._joined.discard(incident_id)
        await self.audit.record(staff.id, "hand_back", incident_id)

    async def close(self, staff: StaffAccount, incident_id: str, outcome: str, reason: str | None = None) -> None:
        await self._need(staff, "desk.close", incident_id)
        if outcome not in OUTCOMES or (outcome == "false_alarm" and reason not in FALSE_ALARM_REASONS):
            raise BadState("bad_outcome")
        async with self._lock:
            h = await self._get(incident_id)
            if h.status == "closed":
                raise BadState("already_closed")
            h.status, h.outcome, h.closed_by, h.closed_at = "closed", outcome, staff.id, self.clock.now()
            h.false_alarm_reason = reason if outcome == "false_alarm" else None
            self._log(h, "closed")
            await self._put(h)
            self._joined.discard(incident_id)
        await self.audit.record(staff.id, "false_alarm" if outcome == "false_alarm" else "incident_close", incident_id, reason=FALSE_ALARM_REASONS.index(reason) if reason in FALSE_ALARM_REASONS else 0)

    async def review(self, reviewer: StaffAccount, incident_id: str) -> None:
        """A SECOND person reviews every closed incident within 24 hours (the founder in the pilot)."""
        await self._need(reviewer, "desk.review", incident_id)
        async with self._lock:
            h = await self._get(incident_id)
            if h.status != "closed":
                raise BadState("not_closed")
            if reviewer.id in (h.closed_by, h.joined_by, h.acked_by):
                raise Denied("second_person_required")
            h.reviewed_by, h.reviewed_at = reviewer.id, self.clock.now()
            await self._put(h)
        await self.audit.record(reviewer.id, "review", incident_id)

    async def reviews_overdue(self) -> list[str]:
        now = self.clock.now()
        out = []
        for d in await self.store.doc_list(KIND_HANDOFF):
            h = Handoff.from_dict(d)
            if h.status == "closed" and h.reviewed_by is None and h.closed_at and now - h.closed_at > timedelta(seconds=REVIEW_WITHIN_S):
                out.append(h.card["incident_id"])
        return out

    async def false_alarms(self, parent_id: str, days: int = 7) -> dict[str, int]:
        """Per-family weekly count by reason (feeds threshold tuning; never lowers sensitivity by itself)."""
        since, out = self.clock.now() - timedelta(days=days), {}
        for d in await self.store.doc_list(KIND_HANDOFF):
            h = Handoff.from_dict(d)
            if h.card["parent_id"] == parent_id and h.outcome == "false_alarm" and h.closed_at and h.closed_at >= since and h.false_alarm_reason:
                out[h.false_alarm_reason] = out.get(h.false_alarm_reason, 0) + 1
        return out

    # ------------------------------------------------------------------ what the AI asks
    async def is_human_joined(self, incident_id: str) -> bool:
        if incident_id in self._joined:
            return True
        d = await self.store.doc_get(KIND_HANDOFF, incident_id)  # another replica / after a restart
        if d and d.get("status") == "joined":
            self._joined.add(incident_id)
            return True
        return False
