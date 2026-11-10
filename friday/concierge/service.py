# ruff: noqa: E501
"""C1: request model + queue for lane 1 (concierge errands). Every staff method checks the permission first (deny by default),
then the rule, then writes, then audits (C6). Intake (from the parent or the child) goes through the hard rules in ``rules.py``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from friday.concierge import rules
from friday.concierge.audit import AuditLog
from friday.concierge.auth import can
from friday.concierge.models import (
    ALLOWED,
    CATEGORY_PRIORITY,
    OPEN,
    PRIORITY_RANK,
    PROOF_KINDS,
    ConciergeRequest,
    Lane,
    Note,
    Priority,
    Proof,
    Status,
)
from friday.concierge.ports import (
    EmergencyReroute,
    FamilyLookup,
    MaskedBridge,
    MaskedLink,
    StaffAccount,
    StaffDirectory,
)
from friday.concierge.store import ConciergeStore, Conflict
from friday.db.base import new_id

ESCALATE_REASONS = ("cannot_reach", "needs_lead", "unsafe", "over_ceiling", "other")
MAX_NOTE = 500
MAX_REF = 300
MAX_SUMMARY = 600


class DeskError(RuntimeError):
    """Base: ``code`` is a fixed word that is safe to show and to audit."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Denied(DeskError):
    pass


class NotFound(DeskError):
    pass


class BadState(DeskError):
    pass


class ProofRequired(DeskError):
    pass


@dataclass(frozen=True)
class DeskSettings:
    """Settings of the desk (all invented working numbers; the founder confirms)."""

    ack_s: int = 900
    finish_s: dict[Priority, int] = field(default_factory=lambda: {Priority.SAFETY: 3600, Priority.HEALTH: 7200, Priority.CONVENIENCE: 14400})
    spend_ceiling_paise: int = 500_000
    idle_timeout_s: int = 600
    desk_ack_s: int = 180

    @classmethod
    def from_settings(cls, s: Any) -> DeskSettings:
        g = lambda name, d: getattr(s, name, d)  # noqa: E731
        return cls(
            ack_s=int(g("robin_concierge_ack_s", 900)),
            finish_s={Priority.SAFETY: int(g("robin_concierge_finish_safety_s", 3600)), Priority.HEALTH: int(g("robin_concierge_finish_health_s", 7200)), Priority.CONVENIENCE: int(g("robin_concierge_finish_convenience_s", 14400))},
            spend_ceiling_paise=int(g("robin_concierge_spend_ceiling_paise", 500_000)),
            idle_timeout_s=int(g("robin_concierge_idle_timeout_s", 600)),
            desk_ack_s=int(g("robin_concierge_desk_ack_s", 180)),
        )


@dataclass(frozen=True)
class IntakeResult:
    ok: bool
    code: str  # created | waiting_child_yes | rerouted_emergency | <refusal code>
    request_id: str | None = None
    incident_id: str | None = None


@dataclass(frozen=True)
class QueueRow:
    id: str
    category: str
    priority: Priority
    status: Status
    claimed_by: str | None
    age_min: int
    sla: str  # ok | ack_overdue | finish_overdue


@dataclass(frozen=True)
class RequestView:
    """The minimum a person needs to do the errand. No raw phone numbers, no ids of family members, no history of other requests."""

    id: str
    category: str
    priority: Priority
    status: Status
    summary: str
    parent_label: str
    parent_phone_masked: str
    language: str
    notes: list[tuple[str, str]]  # (staff id, text)
    proofs: list[tuple[str, str]]  # (id, kind)
    sla: str
    claimed_by: str | None
    has_pay_link: bool
    waiting_for_child: bool


class ConciergeService:
    def __init__(self, *, store: ConciergeStore, audit: AuditLog, clock, family: FamilyLookup, directory: StaffDirectory, emergency: EmergencyReroute, bridge: MaskedBridge | None = None, settings: DeskSettings | None = None) -> None:  # noqa: ANN001
        self.store, self.audit, self.clock, self.family = store, audit, clock, family
        self.directory, self.emergency, self.bridge = directory, emergency, bridge
        self.cfg = settings or DeskSettings()

    # ------------------------------------------------------------------ intake (the parent or a child admin asks)
    async def intake(self, member_id: str, payload: Mapping[str, Any]) -> IntakeResult:
        try:
            rules.check_fields(payload)
        except rules.RuleViolation as e:
            return IntakeResult(False, e.code)
        m = await self.family.member(member_id)
        if m is None or m.role not in ("parent", "child_admin"):
            return IntakeResult(False, "not_allowed")  # only the parent or a child admin may ask; nobody else, not even the second contact
        summary = str(payload.get("summary") or "").strip()
        if not summary or len(summary) > MAX_SUMMARY:
            return IntakeResult(False, "bad_summary")
        if rules.is_safety_text(summary):
            inc = await self.emergency.reroute(member_id=member_id, parent_id=m.parent_id, reason="concierge_distress")
            return IntakeResult(False, "rerouted_emergency", None, inc)  # not stored, not queued, no human errand
        refused = rules.secret_in(summary)
        if refused:
            return IntakeResult(False, refused)
        category = str(payload.get("category") or "other")
        if category not in CATEGORY_PRIORITY:
            return IntakeResult(False, "unknown_category")
        est = payload.get("estimated_paise")
        if est is not None and (not isinstance(est, int) or isinstance(est, bool) or est < 0):
            return IntakeResult(False, "bad_amount")
        needs_child = rules.spend_needs_child(est, self.cfg.spend_ceiling_paise)
        child_yes = bool(payload.get("child_approved")) and m.role == "child_admin"  # a parent cannot approve their own spend above the ceiling
        now = self.clock.now()
        pr = CATEGORY_PRIORITY[category]
        req = ConciergeRequest(
            id=new_id(), family_id=m.family_id, parent_id=m.parent_id, requester_id=member_id, requester_role=m.role, category=category, priority=pr, summary=summary,
            created_at=now, ack_due_at=now + timedelta(seconds=self.cfg.ack_s), finish_due_at=now + timedelta(seconds=self.cfg.finish_s[pr]),
            estimated_paise=est, child_approved=(needs_child and child_yes),
            status=Status.WAITING_USER if (needs_child and not child_yes) else Status.NEW,
        )
        await self.store.request_save(req, expect_version=None)
        await self.audit.record("system", "intake", req.id, priority_rank=PRIORITY_RANK[pr], needs_child_yes=int(req.status == Status.WAITING_USER))
        return IntakeResult(True, "waiting_child_yes" if req.status == Status.WAITING_USER else "created", req.id)

    async def child_yes(self, member_id: str, request_id: str) -> bool:
        """The child's yes for a spend above the ceiling. Only a child admin of the same family."""
        m, req = await self.family.member(member_id), await self.store.request_get(request_id)
        if m is None or req is None or m.role != "child_admin" or m.family_id != req.family_id or req.status != Status.WAITING_USER or req.claimed_by:
            return False
        req.child_approved, req.status = True, Status.NEW
        await self._save(req)
        await self.audit.record("system", "child_yes", req.id)
        return True

    async def user_confirm(self, member_id: str, request_id: str) -> bool:
        """The user (parent or child admin of the family) confirms the errand is done."""
        m, req = await self.family.member(member_id), await self.store.request_get(request_id)
        if m is None or req is None or m.family_id != req.family_id or m.role not in ("parent", "child_admin") or req.status != Status.DONE:
            return False
        req.user_confirmed = True
        await self._save(req)
        return True

    # ------------------------------------------------------------------ helpers
    async def _save(self, req: ConciergeRequest) -> None:
        cur = req.version
        req.version = cur + 1
        try:
            await self.store.request_save(req, expect_version=cur)
        except Conflict:
            raise BadState("changed_meanwhile") from None

    async def _need(self, staff: StaffAccount, perm: str, target: str = "") -> None:
        if not can(staff, perm):
            await self.audit.record(staff.id if staff else "unknown", "denied", target, perm_len=len(perm))
            raise Denied("denied")

    async def _get(self, request_id: str) -> ConciergeRequest:
        req = await self.store.request_get(request_id)
        if req is None:
            raise NotFound("not_found")
        return req

    def _lane_ok(self, staff: StaffAccount, req: ConciergeRequest) -> bool:
        return req.lane.value in staff.lanes or staff.role == "lead"

    async def _mine(self, staff: StaffAccount, request_id: str, perm: str) -> ConciergeRequest:
        await self._need(staff, perm, request_id)
        req = await self._get(request_id)
        if req.claimed_by != staff.id:
            await self.audit.record(staff.id, "denied", request_id, not_claimer=1)
            raise Denied("not_yours")
        return req

    def _to(self, req: ConciergeRequest, new: Status) -> None:
        if new != req.status and new not in ALLOWED[req.status]:
            raise BadState(f"cannot_go_{req.status.value}_to_{new.value}")
        req.status = new

    def sla_state(self, req: ConciergeRequest) -> str:
        now = self.clock.now()
        if req.status in OPEN and now > req.finish_due_at:
            return "finish_overdue"
        if req.status in (Status.NEW, Status.ESCALATED) and now > req.ack_due_at:
            return "ack_overdue"
        return "ok"

    # ------------------------------------------------------------------ queue and view
    async def queue(self, staff: StaffAccount) -> list[QueueRow]:
        await self._need(staff, "queue.view")
        now = self.clock.now()
        rows = [r for r in await self.store.requests_open() if r.lane.value in staff.lanes or staff.role in ("lead", "reviewer")]
        rows.sort(key=lambda r: (PRIORITY_RANK[r.priority], r.finish_due_at, r.created_at))
        await self.audit.record(staff.id, "queue_view", "", rows=len(rows))
        return [QueueRow(r.id, r.category, r.priority, r.status, r.claimed_by, int((now - r.created_at).total_seconds() // 60), self.sla_state(r)) for r in rows]

    async def view(self, staff: StaffAccount, request_id: str) -> RequestView:
        await self._need(staff, "request.view", request_id)
        req = await self._get(request_id)
        if not self._lane_ok(staff, req) and staff.role != "reviewer":
            await self.audit.record(staff.id, "denied", request_id, lane=1)
            raise Denied("denied")
        if req.claimed_by not in (None, staff.id) and staff.role not in ("lead", "reviewer"):
            await self.audit.record(staff.id, "denied", request_id, claimed_by_other=1)
            raise Denied("claimed_by_other")
        party = await self.family.party(req.parent_id, "parent")
        await self.audit.record(staff.id, "request_view", request_id)
        return RequestView(
            id=req.id, category=req.category, priority=req.priority, status=req.status, summary=req.summary,
            parent_label=party.label if party else "Parent", parent_phone_masked=party.masked_phone if party else "••••••", language=party.language if party else "hinglish",
            notes=[(n.staff_id, n.text) for n in req.notes], proofs=[(p.id, p.kind) for p in req.proofs], sla=self.sla_state(req),
            claimed_by=req.claimed_by, has_pay_link=bool(req.pay_link), waiting_for_child=req.status == Status.WAITING_USER and not req.child_approved,
        )

    # ------------------------------------------------------------------ actions
    async def claim(self, staff: StaffAccount, request_id: str) -> None:
        await self._need(staff, "request.claim", request_id)
        req = await self._get(request_id)
        if not self._lane_ok(staff, req):
            await self.audit.record(staff.id, "denied", request_id, lane=1)
            raise Denied("denied")
        if req.status == Status.ESCALATED and staff.role != "lead":
            raise Denied("escalated_to_lead")
        if req.status not in (Status.NEW, Status.ESCALATED):
            raise BadState("not_claimable")
        req.claimed_by, req.claimed_at = staff.id, self.clock.now()
        self._to(req, Status.CLAIMED)
        await self._save(req)
        await self.audit.record(staff.id, "claim", request_id, priority_rank=PRIORITY_RANK[req.priority])

    async def release(self, staff: StaffAccount, request_id: str) -> None:
        await self._need(staff, "request.release", request_id)
        req = await self._get(request_id)
        if req.claimed_by != staff.id and staff.role != "lead":
            raise Denied("not_yours")
        req.claimed_by, req.claimed_at = None, None
        self._to(req, Status.NEW)
        await self._save(req)
        await self.audit.record(staff.id, "release", request_id)

    async def assign(self, staff: StaffAccount, request_id: str, to_staff_id: str) -> None:
        await self._need(staff, "request.assign", request_id)
        req = await self._get(request_id)
        to = await self.directory.get(to_staff_id)
        if to is None or not to.active or req.lane.value not in to.lanes or not can(to, "request.claim"):
            raise BadState("cannot_assign_there")
        if req.status not in (Status.NEW, Status.ESCALATED, Status.CLAIMED):
            raise BadState("not_assignable")
        req.claimed_by, req.claimed_at = to.id, self.clock.now()
        if req.status != Status.CLAIMED:
            self._to(req, Status.CLAIMED)
        await self._save(req)
        await self.audit.record(staff.id, "assign", request_id)

    async def note(self, staff: StaffAccount, request_id: str, text: str) -> None:
        req = await self._mine(staff, request_id, "request.note")
        text = (text or "").strip()
        if not text or len(text) > MAX_NOTE:
            raise BadState("bad_note")
        if rules.secret_in(text):
            raise BadState("secret_refused")
        req.notes.append(Note(self.clock.now(), staff.id, text))
        await self._save(req)
        await self.audit.record(staff.id, "note", request_id, chars=len(text))

    async def proof(self, staff: StaffAccount, request_id: str, kind: str, ref: str) -> str:
        req = await self._mine(staff, request_id, "request.proof")
        ref = (ref or "").strip()
        if kind not in PROOF_KINDS or not ref or len(ref) > MAX_REF:
            raise BadState("bad_proof")
        if rules.secret_in(ref):
            raise BadState("secret_refused")
        p = Proof(new_id(), self.clock.now(), staff.id, kind, ref)
        req.proofs.append(p)
        await self._save(req)
        await self.audit.record(staff.id, "proof", request_id, proofs=len(req.proofs))
        return p.id

    async def done(self, staff: StaffAccount, request_id: str) -> None:
        req = await self._mine(staff, request_id, "request.done")
        if not req.proofs:
            await self.audit.record(staff.id, "denied", request_id, no_proof=1)
            raise ProofRequired("proof_required")
        self._to(req, Status.DONE)
        req.done_at = self.clock.now()
        await self._save(req)
        await self.audit.record(staff.id, "done", request_id, proofs=len(req.proofs), late=int(req.done_at > req.finish_due_at))

    async def waiting_user(self, staff: StaffAccount, request_id: str) -> None:
        req = await self._mine(staff, request_id, "request.waiting_user")
        self._to(req, Status.WAITING_USER)
        await self._save(req)
        await self.audit.record(staff.id, "waiting_user", request_id)

    async def resume(self, staff: StaffAccount, request_id: str) -> None:
        req = await self._mine(staff, request_id, "request.waiting_user")
        self._to(req, Status.CLAIMED)
        await self._save(req)
        await self.audit.record(staff.id, "claim", request_id, resumed=1)

    async def escalate(self, staff: StaffAccount, request_id: str, reason: str) -> None:
        req = await self._mine(staff, request_id, "request.escalate")
        if reason not in ESCALATE_REASONS:
            raise BadState("bad_reason")
        rank = max(0, PRIORITY_RANK[req.priority] - 1)  # staff can only raise a priority
        req.priority = next(p for p, r in PRIORITY_RANK.items() if r == rank)
        req.escalations += 1
        req.claimed_by, req.claimed_at = None, None
        self._to(req, Status.ESCALATED)
        await self._save(req)
        await self.audit.record(staff.id, "escalate", request_id, reason=ESCALATE_REASONS.index(reason), priority_rank=rank)

    async def pay_link(self, staff: StaffAccount, request_id: str, payee_vpa: str, payee_name: str, amount_paise: int) -> str:
        """Generate the UPI link the USER taps. The desk never pays. Above the ceiling the child's yes must already be on the request."""
        req = await self._mine(staff, request_id, "request.note")
        if rules.spend_needs_child(amount_paise, self.cfg.spend_ceiling_paise) and not req.child_approved:
            raise BadState("child_yes_needed")
        try:
            link = rules.make_upi_link(payee_vpa, payee_name, amount_paise, "Robin")
        except rules.RuleViolation as e:
            raise BadState(e.code) from None
        req.pay_link = link
        await self._save(req)
        await self.audit.record(staff.id, "pay_link", request_id, paise_hundreds=int(amount_paise) // 100)
        return link

    # ------------------------------------------------------------------ C7: masked contact
    async def contact(self, staff: StaffAccount, request_id: str, party: str) -> MaskedLink:
        perm = "contact.parent" if party == "parent" else "contact.child"
        req = await self._mine(staff, request_id, perm if party in ("parent", "child") else "contact.none")
        if self.bridge is None:
            await self.audit.record(staff.id, "contact_refused", request_id, no_bridge=1)
            raise BadState("no_bridge")
        link = await self.bridge.connect(staff_id=staff.id, request_id=request_id, parent_id=req.parent_id, party=party)
        if link is None:
            await self.audit.record(staff.id, "contact_refused", request_id)
            raise BadState("bridge_refused")
        await self.audit.record(staff.id, "contact_parent" if party == "parent" else "contact_child", request_id)
        return link

    async def end_contact(self, staff: StaffAccount, request_id: str, link_id: str) -> bool:
        await self._need(staff, "contact.parent", request_id)
        ok = bool(self.bridge and await self.bridge.end(link_id))
        await self.audit.record(staff.id, "contact_end", request_id, ended=int(ok))
        return ok

    # ------------------------------------------------------------------ erase hook ("delete everything")
    async def erase_parent(self, parent_id: str) -> dict[str, int]:
        return await self.store.erase_parent(parent_id)


__all__ = [
    "BadState", "ConciergeService", "Denied", "DeskError", "DeskSettings", "IntakeResult", "Lane", "NotFound", "ProofRequired",
    "QueueRow", "RequestView", "ESCALATE_REASONS",
]
