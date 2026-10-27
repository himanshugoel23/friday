"""Who to call about a refund. The one rule: **a number is never invented.**

The resolver only returns numbers that a ``NumberSource`` handed it (the user's own message, a
confirmed document, a task record, proof the user supplied, a person-verified vendor record), after
checking each one is dialable (``calls.numbers.canonical``: not an emergency code, a plausible
Indian or international number). For the payment issuer it returns the bank NAME the user gave and
a pointer to the card or the bank app, never a number. With nothing held it returns nothing and the
service asks the user.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from friday.calls.numbers import canonical
from friday.docunderstand.models import DocType, Document
from friday.refunds.models import RefundCase
from friday.refunds.ports import KnownNumber, NumberSource, name_match

ORDER = {"user": 0, "document": 1, "task": 2, "evidence": 3, "vendor_record": 4}


@dataclass(frozen=True)
class Contact:
    number: str  # E.164
    source: str
    label: str
    contact_id: str  # stable id of (source, number) so an approval is bound to one contact


@dataclass
class Resolved:
    contacts: list[Contact] = field(default_factory=list)
    issuer_bank: str | None = None  # a name only; there is no number field on purpose

    @property
    def empty(self) -> bool:
        return not self.contacts


def contact_id(source: str, number: str) -> str:
    return hashlib.sha256(f"{source}:{number}".encode()).hexdigest()[:12]


async def resolve(
    user_id: str, case: RefundCase, sources: list[NumberSource] | tuple[NumberSource, ...] = ()
) -> Resolved:
    held: list[KnownNumber] = []
    if case.user_number:
        held.append(KnownNumber(case.user_number, "user", case.vendor_name))
    for src in sources:
        held.extend(await src.numbers_for(user_id, case.vendor_name))
    seen: set[str] = set()
    contacts: list[Contact] = []
    for k in sorted(held, key=lambda k: ORDER.get(k.source, 9)):
        if k.source not in ORDER:
            continue  # an unknown provenance is not trusted
        num = canonical(k.number)
        if num is None or num in seen:
            continue
        seen.add(num)
        contacts.append(Contact(num, k.source, k.label, contact_id(k.source, num)))
    return Resolved(contacts, case.paid_with_bank or None)


# ------------------------------------------------------------------------ adapters (read-only)
class StaticNumberSource:
    """Fixed rows per user (the founder-entered vendor record table in tests and the simulator)."""

    def __init__(self, rows: dict[str, list[tuple[str, KnownNumber]]] | None = None) -> None:
        self.rows = rows or {}

    def add(self, user_id: str, owner: str, number: KnownNumber) -> None:
        self.rows.setdefault(user_id, []).append((owner, number))

    async def numbers_for(self, user_id: str, vendor_name: str) -> list[KnownNumber]:
        return [n for owner, n in self.rows.get(user_id, []) if name_match(vendor_name, owner)]


class DocumentNumberSource:
    """Phone fields of the user's CONFIRMED documents (hotel confirmation) whose property or
    biller name matches the vendor. Reads ``docs.list_confirmed(user_id)``; nothing else."""

    NAME_FIELDS = ("property_name", "airline", "platform", "biller", "train_name", "title")

    def __init__(self, docs) -> None:  # noqa: ANN001
        self.docs = docs

    async def numbers_for(self, user_id: str, vendor_name: str) -> list[KnownNumber]:
        out: list[KnownNumber] = []
        for d in await self.docs.list_confirmed(user_id):
            if d.user_id != user_id or d.doc_type != DocType.HOTEL:
                continue
            out += self._from_doc(d, vendor_name)
        return out

    def _from_doc(self, d: Document, vendor_name: str) -> list[KnownNumber]:
        vals = d.values()
        phone = vals.get("phone")
        name = next((vals[k] for k in self.NAME_FIELDS if vals.get(k)), "")
        if phone and name_match(vendor_name, name):
            return [KnownNumber(phone, "document", name)]
        return []


class TaskNumberSource:
    """The number on the user's own earlier tasks (the number Friday dialled for that vendor)."""

    def __init__(self, tasks) -> None:  # noqa: ANN001
        self.tasks = tasks  # anything with ``async list_for_user(user_id)``

    async def numbers_for(self, user_id: str, vendor_name: str) -> list[KnownNumber]:
        out: list[KnownNumber] = []
        for task in await self.tasks.list_for_user(user_id):
            if task.requester_user_id != user_id:
                continue
            phone = task.spec.business_phone if task.spec else None
            name = task.spec.business_name if task.spec else None
            if phone and name and name_match(vendor_name, name):
                out.append(KnownNumber(phone, "task", name))
        return out
