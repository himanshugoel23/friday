# ruff: noqa: E501
"""Storage port of the desk and the in-memory implementation (tests, and a process with no database).
The DB implementation is ``friday.concierge.dbmodel.DbConciergeStore`` (migration 0021_concierge)."""

from __future__ import annotations

import copy
from typing import Any, Protocol

from friday.concierge.audit import AuditEntry
from friday.concierge.models import OPEN, ConciergeRequest


class Conflict(RuntimeError):
    """Optimistic-lock miss: someone else changed the request first."""


class ConciergeStore(Protocol):
    async def request_save(self, req: ConciergeRequest, *, expect_version: int | None) -> None: ...
    async def request_get(self, request_id: str) -> ConciergeRequest | None: ...
    async def requests_open(self) -> list[ConciergeRequest]: ...
    async def requests_for_parent(self, parent_id: str) -> list[ConciergeRequest]: ...
    async def erase_parent(self, parent_id: str) -> dict[str, int]: ...
    async def audit_last(self) -> AuditEntry | None: ...
    async def audit_append(self, entry: AuditEntry) -> None: ...
    async def audit_all(self) -> list[AuditEntry]: ...
    async def doc_save(self, kind: str, target_id: str, data: dict[str, Any], *, parent_id: str = "", status: str = "") -> None: ...
    async def doc_get(self, kind: str, target_id: str) -> dict[str, Any] | None: ...
    async def doc_list(self, kind: str) -> list[dict[str, Any]]: ...


class InMemoryConciergeStore:
    def __init__(self) -> None:
        self._req: dict[str, dict[str, Any]] = {}
        self._audit: list[AuditEntry] = []
        self._docs: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}  # (kind, id) -> (parent_id, data)

    async def request_save(self, req: ConciergeRequest, *, expect_version: int | None) -> None:
        cur = self._req.get(req.id)
        if expect_version is not None and (cur is None or cur["version"] != expect_version):
            raise Conflict(req.id)
        self._req[req.id] = copy.deepcopy(req.to_dict())

    async def request_get(self, request_id: str) -> ConciergeRequest | None:
        d = self._req.get(request_id)
        return ConciergeRequest.from_dict(copy.deepcopy(d)) if d else None

    async def requests_open(self) -> list[ConciergeRequest]:
        return [ConciergeRequest.from_dict(copy.deepcopy(d)) for d in self._req.values() if d["status"] in {s.value for s in OPEN}]

    async def requests_for_parent(self, parent_id: str) -> list[ConciergeRequest]:
        return [ConciergeRequest.from_dict(copy.deepcopy(d)) for d in self._req.values() if d["parent_id"] == parent_id]

    async def erase_parent(self, parent_id: str) -> dict[str, int]:
        ids = [k for k, d in self._req.items() if d["parent_id"] == parent_id]
        for k in ids:
            del self._req[k]
        docs = [k for k, (pid, _d) in self._docs.items() if pid == parent_id]
        for k in docs:
            del self._docs[k]
        return {"requests": len(ids), "docs": len(docs)}

    async def audit_last(self) -> AuditEntry | None:
        return self._audit[-1] if self._audit else None

    async def audit_append(self, entry: AuditEntry) -> None:
        if self._audit and entry.seq != self._audit[-1].seq + 1:
            raise Conflict("audit seq")
        self._audit.append(entry)

    async def audit_all(self) -> list[AuditEntry]:
        return list(self._audit)

    async def doc_save(self, kind: str, target_id: str, data: dict[str, Any], *, parent_id: str = "", status: str = "") -> None:  # noqa: ARG002
        self._docs[(kind, target_id)] = (parent_id, copy.deepcopy(data))

    async def doc_get(self, kind: str, target_id: str) -> dict[str, Any] | None:
        v = self._docs.get((kind, target_id))
        return copy.deepcopy(v[1]) if v else None

    async def doc_list(self, kind: str) -> list[dict[str, Any]]:
        return [copy.deepcopy(d) for (k, _i), (_p, d) in self._docs.items() if k == kind]
