"""Message log: every inbound/outbound message on any channel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from friday.core.models import (
    Channel,
    ConversationTurn,
    Direction,
    InboundMessage,
    LocationPin,
    MessageKind,
    OutboundMessage,
    ReplyButton,
    SendReceipt,
    TemplateRef,
)
from friday.db.repositories._base import Repo, dump_json, dump_json_list, row_dict
from friday.db.tables import MessageRow


class StoredMessage(BaseModel):
    """A row of the message log as a domain object (local to the backend)."""

    id: str
    user_id: str | None = None
    person_id: str | None = None
    business_id: str | None = None
    direction: Direction
    channel: Channel
    kind: MessageKind = MessageKind.TEXT
    phone: str
    text: str | None = None
    buttons: list[ReplyButton] = Field(default_factory=list)
    button_id: str | None = None
    template: TemplateRef | None = None
    media_url: str | None = None
    location: LocationPin | None = None
    provider_message_id: str | None = None
    task_id: str | None = None
    nudge_id: str | None = None
    question_id: str | None = None
    ok: bool = True
    error: str | None = None
    at: datetime


def _stored(row: MessageRow) -> StoredMessage:
    d: dict[str, Any] = row_dict(row)
    return StoredMessage.model_validate(d)


class MessageRepo(Repo):
    async def log_inbound(self, msg: InboundMessage) -> StoredMessage:
        row = MessageRow(
            id=msg.id,
            user_id=msg.user_id,
            person_id=msg.person_id,
            business_id=msg.business_id,
            direction=Direction.INBOUND.value,
            channel=msg.channel.value,
            kind=msg.kind.value,
            phone=msg.from_phone,
            text=msg.text,
            buttons=[],
            button_id=msg.button_id,
            media_url=msg.media_url,
            location=dump_json(msg.location),
            provider_message_id=msg.provider_message_id,
            ok=True,
            at=msg.received_at,
        )
        async with self.db.session() as s:
            await s.merge(row)
        return _stored(row)

    async def log_outbound(
        self, msg: OutboundMessage, receipt: SendReceipt | None = None
    ) -> StoredMessage:
        kind = MessageKind.TEXT
        row = MessageRow(
            id=msg.id,
            user_id=msg.user_id,
            person_id=msg.person_id,
            business_id=msg.business_id,
            direction=Direction.OUTBOUND.value,
            channel=msg.channel.value,
            kind=kind.value,
            phone=msg.to_phone,
            text=msg.text,
            buttons=dump_json_list(list(msg.buttons)),
            template=dump_json(msg.template),
            media_url=msg.media_url,
            provider_message_id=receipt.provider_message_id if receipt else None,
            task_id=msg.task_id,
            nudge_id=msg.nudge_id,
            question_id=msg.question_id,
            ok=receipt.ok if receipt else True,
            error=receipt.error if receipt else None,
            at=receipt.sent_at if receipt else self.now(),
        )
        async with self.db.session() as s:
            await s.merge(row)
        return _stored(row)

    async def update_status(
        self, provider_message_id: str, *, ok: bool, error: str | None = None
    ) -> bool:
        """Provider delivery callback (e.g. WhatsApp 'failed')."""
        async with self.db.session() as s:
            row = (
                (
                    await s.execute(
                        select(MessageRow).where(
                            MessageRow.provider_message_id == provider_message_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return False
            row.ok = ok
            row.error = error
            return True

    async def get(self, message_id: str) -> StoredMessage | None:
        async with self.db.session() as s:
            row = await s.get(MessageRow, message_id)
            return _stored(row) if row else None

    async def seen_provider_id(self, provider_message_id: str) -> bool:
        """Webhook de-duplication (providers retry deliveries)."""
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(MessageRow.id).where(
                        MessageRow.provider_message_id == provider_message_id,
                        MessageRow.direction == Direction.INBOUND.value,
                    )
                )
            ).first()
            return row is not None

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[StoredMessage]:
        """Newest last."""
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(MessageRow)
                        .where(MessageRow.user_id == user_id, MessageRow.person_id.is_(None))
                        .where(MessageRow.business_id.is_(None))
                        .order_by(MessageRow.at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [_stored(r) for r in reversed(rows)]

    async def recent_turns(self, user_id: str, *, limit: int = 20) -> list[ConversationTurn]:
        """Conversation between the user and Friday, oldest first (for the brain)."""
        out: list[ConversationTurn] = []
        for m in await self.list_for_user(user_id, limit=limit):
            text = m.text or (m.template.key if m.template else None)
            if m.button_id and not text:
                text = f"[button {m.button_id}]"
            if not text:
                continue
            out.append(ConversationTurn(direction=m.direction, text=text, at=m.at))
        return out

    async def last_outbound_to(self, phone: str) -> StoredMessage | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(MessageRow)
                    .where(MessageRow.phone == phone, MessageRow.direction == "outbound")
                    .order_by(MessageRow.at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _stored(row) if row else None

    async def last_inbound_from(self, phone: str) -> StoredMessage | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(MessageRow)
                    .where(MessageRow.phone == phone, MessageRow.direction == "inbound")
                    .order_by(MessageRow.at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _stored(row) if row else None
