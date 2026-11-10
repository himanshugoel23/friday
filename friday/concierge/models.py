# ruff: noqa: E501
"""Vocabulary and records of the desk. Plain dataclasses with ``to_dict``/``from_dict`` (stored as EncryptedJSON)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Lane(StrEnum):
    CONCIERGE = "concierge"
    EMERGENCY = "emergency"


class Priority(StrEnum):
    SAFETY = "safety"
    HEALTH = "health"
    CONVENIENCE = "convenience"


PRIORITY_RANK = {Priority.SAFETY: 0, Priority.HEALTH: 1, Priority.CONVENIENCE: 2}


class Status(StrEnum):
    NEW = "new"
    CLAIMED = "claimed"
    WAITING_USER = "waiting_user"
    ESCALATED = "escalated"
    DONE = "done"
    CANCELLED = "cancelled"


ALLOWED: dict[Status, frozenset[Status]] = {
    Status.NEW: frozenset({Status.CLAIMED, Status.CANCELLED}),
    Status.CLAIMED: frozenset({Status.NEW, Status.WAITING_USER, Status.ESCALATED, Status.DONE, Status.CANCELLED}),
    Status.WAITING_USER: frozenset({Status.CLAIMED, Status.CANCELLED}),
    Status.ESCALATED: frozenset({Status.CLAIMED, Status.CANCELLED}),
    Status.DONE: frozenset(),
    Status.CANCELLED: frozenset(),
}
OPEN = (Status.NEW, Status.CLAIMED, Status.WAITING_USER, Status.ESCALATED)

# What an errand is. The category (not the words) fixes the priority; staff can only raise it (escalate).
CATEGORY_PRIORITY: dict[str, Priority] = {
    "scam_help": Priority.SAFETY, "locksmith": Priority.SAFETY, "block_lost_phone": Priority.SAFETY,
    "medicine": Priority.HEALTH, "doctor_booking": Priority.HEALTH, "lab_test": Priority.HEALTH, "hospital_call": Priority.HEALTH,
    "bill": Priority.CONVENIENCE, "grocery": Priority.CONVENIENCE, "cab": Priority.CONVENIENCE, "booking": Priority.CONVENIENCE,
    "call_shop": Priority.CONVENIENCE, "document_help": Priority.CONVENIENCE, "other": Priority.CONVENIENCE,
}
PROOF_KINDS = ("photo", "receipt", "call_note")


@dataclass
class Note:
    at: datetime
    staff_id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at.isoformat(), "staff_id": self.staff_id, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Note:
        return cls(datetime.fromisoformat(d["at"]), d["staff_id"], d["text"])


@dataclass
class Proof:
    id: str
    at: datetime
    staff_id: str
    kind: str  # photo | receipt | call_note
    ref: str  # object-store key for a photo/receipt, or the short call note text

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "at": self.at.isoformat(), "staff_id": self.staff_id, "kind": self.kind, "ref": self.ref}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Proof:
        return cls(d["id"], datetime.fromisoformat(d["at"]), d["staff_id"], d["kind"], d["ref"])


@dataclass
class ConciergeRequest:
    id: str
    family_id: str
    parent_id: str  # the parent the errand is for (erase key)
    requester_id: str  # member id of who asked: the parent or a child admin
    requester_role: str  # parent | child_admin
    category: str
    priority: Priority
    summary: str  # what is wanted; personal data, stored encrypted; shown only in the one-screen request view
    created_at: datetime
    ack_due_at: datetime
    finish_due_at: datetime
    status: Status = Status.NEW
    lane: Lane = Lane.CONCIERGE
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    estimated_paise: int | None = None  # for the ceiling check only; the desk never moves this money
    child_approved: bool = False  # the child's yes for a spend above the ceiling
    pay_link: str | None = None  # a UPI link the USER taps; generated, never paid by staff
    notes: list[Note] = field(default_factory=list)
    proofs: list[Proof] = field(default_factory=list)
    escalations: int = 0
    done_at: datetime | None = None
    user_confirmed: bool = False
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        def iso(v: datetime | None) -> str | None:
            return v.isoformat() if v else None

        return {
            "id": self.id, "family_id": self.family_id, "parent_id": self.parent_id, "requester_id": self.requester_id,
            "requester_role": self.requester_role, "category": self.category, "priority": self.priority.value, "summary": self.summary,
            "created_at": iso(self.created_at), "ack_due_at": iso(self.ack_due_at), "finish_due_at": iso(self.finish_due_at),
            "status": self.status.value, "lane": self.lane.value, "claimed_by": self.claimed_by, "claimed_at": iso(self.claimed_at),
            "estimated_paise": self.estimated_paise, "child_approved": self.child_approved, "pay_link": self.pay_link,
            "notes": [n.to_dict() for n in self.notes], "proofs": [p.to_dict() for p in self.proofs], "escalations": self.escalations,
            "done_at": iso(self.done_at), "user_confirmed": self.user_confirmed, "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConciergeRequest:
        def dt(v: str | None) -> datetime | None:
            return datetime.fromisoformat(v) if v else None

        return cls(
            id=d["id"], family_id=d["family_id"], parent_id=d["parent_id"], requester_id=d["requester_id"], requester_role=d["requester_role"],
            category=d["category"], priority=Priority(d["priority"]), summary=d["summary"], created_at=dt(d["created_at"]),  # type: ignore[arg-type]
            ack_due_at=dt(d["ack_due_at"]), finish_due_at=dt(d["finish_due_at"]), status=Status(d["status"]), lane=Lane(d["lane"]),  # type: ignore[arg-type]
            claimed_by=d.get("claimed_by"), claimed_at=dt(d.get("claimed_at")), estimated_paise=d.get("estimated_paise"),
            child_approved=bool(d.get("child_approved")), pay_link=d.get("pay_link"),
            notes=[Note.from_dict(n) for n in d.get("notes", [])], proofs=[Proof.from_dict(p) for p in d.get("proofs", [])],
            escalations=int(d.get("escalations", 0)), done_at=dt(d.get("done_at")), user_confirmed=bool(d.get("user_confirmed")), version=int(d.get("version", 1)),
        )
