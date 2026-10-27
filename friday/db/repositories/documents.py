"""Document storage (tables in friday/docunderstand/dbmodel.py). Every read takes the ``user_id``
and filters by it: one user's documents are never reachable through another user's id."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from friday.db.repositories._base import Repo
from friday.docunderstand.dbmodel import DocumentFieldRow, DocumentRow
from friday.docunderstand.models import OPEN_STATUSES, DocField, DocStatus, DocType, Document


def _doc(r: DocumentRow, fields: list[DocumentFieldRow]) -> Document:
    return Document(
        id=r.id,
        user_id=r.user_id,
        doc_type=DocType(r.doc_type),
        status=DocStatus(r.status),
        mime=r.mime,
        size_bytes=r.size_bytes,
        sha256=r.sha256,
        language=r.language,
        confidence=r.confidence,
        injection_flag=r.injection_flag,
        pointer_kind=r.pointer_kind,
        pointer_ref=r.pointer_ref,
        fields={
            f.name: DocField(
                value=f.value,
                confidence=f.confidence,
                needs_confirm=f.needs_confirm,
                confirmed=f.confirmed,
                source=f.source,
                masked=f.masked,
            )
            for f in fields
        },
        created_at=r.created_at,
        expires_at=r.expires_at,
        confirmed_at=r.confirmed_at,
    )


class DocumentRepo(Repo):
    async def _load(self, s, rows: list[DocumentRow]) -> list[Document]:  # noqa: ANN001
        out: list[Document] = []
        for r in rows:
            fs = (
                await s.execute(
                    select(DocumentFieldRow)
                    .where(DocumentFieldRow.document_id == r.id)
                    .order_by(DocumentFieldRow.created_at, DocumentFieldRow.name)
                )
            ).scalars()
            out.append(_doc(r, list(fs)))
        return out

    async def save(self, doc: Document) -> None:
        """Insert or replace the document and ALL its fields (a fix rewrites them)."""
        async with self.db.session() as s:
            row = await s.get(DocumentRow, doc.id)
            if row is not None and row.user_id != doc.user_id:
                raise PermissionError("document belongs to another user")
            if row is None:
                row = DocumentRow(id=doc.id, user_id=doc.user_id, created_at=doc.created_at)
                s.add(row)
            row.doc_type, row.status = doc.doc_type.value, doc.status.value
            row.mime, row.size_bytes, row.sha256 = doc.mime, doc.size_bytes, doc.sha256
            row.language, row.confidence = doc.language, doc.confidence
            row.injection_flag = doc.injection_flag
            row.pointer_kind, row.pointer_ref = doc.pointer_kind, doc.pointer_ref
            row.expires_at, row.confirmed_at = doc.expires_at, doc.confirmed_at
            row.updated_at = self.now()
            await s.flush()
            await s.execute(delete(DocumentFieldRow).where(DocumentFieldRow.document_id == doc.id))
            for name, f in doc.fields.items():
                s.add(
                    DocumentFieldRow(
                        document_id=doc.id,
                        user_id=doc.user_id,
                        name=name,
                        value=f.value,
                        confidence=f.confidence,
                        needs_confirm=f.needs_confirm,
                        confirmed=f.confirmed,
                        source=f.source,
                        masked=f.masked,
                    )
                )

    async def get(self, user_id: str, doc_id: str) -> Document | None:
        async with self.db.session() as s:
            r = await s.get(DocumentRow, doc_id)
            if r is None or r.user_id != user_id:
                return None
            return (await self._load(s, [r]))[0]

    async def latest_open(self, user_id: str) -> Document | None:
        """The newest document still waiting for the user's answer."""
        async with self.db.session() as s:
            r = (
                await s.execute(
                    select(DocumentRow)
                    .where(
                        DocumentRow.user_id == user_id,
                        DocumentRow.status.in_([x.value for x in OPEN_STATUSES]),
                    )
                    .order_by(DocumentRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return (await self._load(s, [r]))[0] if r else None

    async def list_confirmed(self, user_id: str, doc_type: DocType | None = None) -> list[Document]:
        async with self.db.session() as s:
            q = select(DocumentRow).where(
                DocumentRow.user_id == user_id, DocumentRow.status == DocStatus.CONFIRMED.value
            )
            if doc_type is not None:
                q = q.where(DocumentRow.doc_type == doc_type.value)
            rows = (await s.execute(q.order_by(DocumentRow.created_at))).scalars().all()
            return await self._load(s, list(rows))

    async def delete(self, user_id: str, doc_id: str) -> bool:
        async with self.db.session() as s:
            r = await s.get(DocumentRow, doc_id)
            if r is None or r.user_id != user_id:
                return False
            await s.execute(delete(DocumentFieldRow).where(DocumentFieldRow.document_id == doc_id))
            await s.execute(delete(DocumentRow).where(DocumentRow.id == doc_id))
            return True

    async def expire(self, now: datetime) -> int:
        """Delete documents (and fields) past ``expires_at``. A Drive pointer goes with its row;
        the user's Drive file is never touched."""
        async with self.db.session() as s:
            ids = list(
                (
                    await s.execute(
                        select(DocumentRow.id).where(
                            DocumentRow.expires_at.is_not(None), DocumentRow.expires_at < now
                        )
                    )
                ).scalars()
            )
            if ids:
                await s.execute(
                    delete(DocumentFieldRow).where(DocumentFieldRow.document_id.in_(ids))
                )
                await s.execute(delete(DocumentRow).where(DocumentRow.id.in_(ids)))
            return len(ids)
