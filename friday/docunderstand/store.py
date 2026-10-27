"""In-memory document store (tests, simulator). Same surface as ``db.repositories.documents``."""

from __future__ import annotations

from datetime import datetime

from friday.docunderstand.models import OPEN_STATUSES, DocStatus, DocType, Document


class MemoryDocStore:
    def __init__(self) -> None:
        self.docs: dict[str, Document] = {}

    async def save(self, doc: Document) -> None:
        self.docs[doc.id] = doc.model_copy(deep=True)

    async def get(self, user_id: str, doc_id: str) -> Document | None:
        d = self.docs.get(doc_id)
        return d.model_copy(deep=True) if d and d.user_id == user_id else None

    async def latest_open(self, user_id: str) -> Document | None:
        open_ = [
            d for d in self.docs.values() if d.user_id == user_id and d.status in OPEN_STATUSES
        ]
        return max(open_, key=lambda d: d.created_at).model_copy(deep=True) if open_ else None

    async def list_confirmed(self, user_id: str, doc_type: DocType | None = None) -> list[Document]:
        return [
            d.model_copy(deep=True)
            for d in self.docs.values()
            if d.user_id == user_id
            and d.status == DocStatus.CONFIRMED
            and (doc_type is None or d.doc_type == doc_type)
        ]

    async def delete(self, user_id: str, doc_id: str) -> bool:
        d = self.docs.get(doc_id)
        if d is None or d.user_id != user_id:
            return False
        del self.docs[doc_id]
        return True

    async def expire(self, now: datetime) -> int:
        gone = [i for i, d in self.docs.items() if d.expires_at and d.expires_at < now]
        for i in gone:
            del self.docs[i]
        return len(gone)
