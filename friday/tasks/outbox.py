"""Outbox: the engines' single way to message users, circle members and businesses.

Builds core ``OutboundMessage``s and hands them to the backend notifier (B-4), which
owns channel choice, the 24h window (we always attach a template fallback) and
logging. Circle-member consent is ALSO checked here (defence in depth). Business
touches fall back to the DLT ``SMSProvider`` when no notifier is wired.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any

from friday.core.logging import get_logger, mask_phone, truncate
from friday.core.models import (
    Channel,
    OutboundMessage,
    Person,
    PersonConsent,
    ReplyButton,
    SendReceipt,
    TemplateRef,
    Urgency,
)
from friday.tasks.ports import call_opt

log = get_logger(__name__)

TEMPLATE_PARAM_MAX = 900  # WhatsApp body params must stay short


class Outbox:
    def __init__(self, *, notifier: Any, users: Any, sms: Any = None) -> None:
        self.notifier = notifier
        self.users = users
        self.sms = sms
        self._accepts_urgency: bool | None = None

    async def _send(self, msg: OutboundMessage, urgency: Urgency) -> SendReceipt | None:
        if self.notifier is None:
            log.warning("no notifier wired; dropping message %s", msg.id)
            return None
        send = self.notifier.send
        if self._accepts_urgency is None:
            try:
                self._accepts_urgency = "urgency" in inspect.signature(send).parameters
            except (TypeError, ValueError):
                self._accepts_urgency = False
        try:
            if self._accepts_urgency:
                return await send(msg, urgency=urgency)
            return await send(msg)
        except Exception as e:  # noqa: BLE001 - a failed send never breaks a task
            log.error("notifier failed for %s: %r", msg.id, e)
            return None

    async def to_user(
        self,
        user_id: str,
        text: str,
        *,
        buttons: Sequence[ReplyButton] = (),
        task_id: str | None = None,
        question_id: str | None = None,
        nudge_id: str | None = None,
        media_url: str | None = None,
        urgency: Urgency = Urgency.NORMAL,
        template: TemplateRef | None = None,
        template_key: str = "task_update",
    ) -> SendReceipt | None:
        user = await call_opt(self.users, "get", user_id)
        phone = user.phone if user else ""
        msg = OutboundMessage(
            channel=Channel.WHATSAPP,
            to_phone=phone,
            user_id=user_id,
            text=text,
            buttons=list(buttons)[:3],
            template=template or TemplateRef(key=template_key, params=[truncate(text, TEMPLATE_PARAM_MAX)]),
            media_url=media_url,
            task_id=task_id,
            question_id=question_id,
            nudge_id=nudge_id,
        )
        return await self._send(msg, urgency)

    async def to_person(
        self,
        person: Person,
        text: str,
        *,
        task_id: str | None = None,
        urgency: Urgency = Urgency.NORMAL,
    ) -> SendReceipt | None:
        """Circle member: only after their one-time opt-in (US-22.1)."""
        if person.contact_consent != PersonConsent.OPTED_IN or not person.phone:
            log.info("not messaging person %s: no contact consent", person.id)
            return None
        msg = OutboundMessage(
            channel=Channel.WHATSAPP,
            to_phone=person.phone,
            user_id=person.owner_user_id,
            person_id=person.id,
            text=text,
            template=TemplateRef(key="task_update", params=[truncate(text, TEMPLATE_PARAM_MAX)]),
            task_id=task_id,
        )
        return await self._send(msg, urgency)

    async def to_business(
        self,
        phone: str,
        template: TemplateRef,
        *,
        business_id: str | None = None,
        task_id: str | None = None,
    ) -> SendReceipt | None:
        """Templated business touch (BRIEF #8, DLT SMS)."""
        if self.notifier is not None:
            msg = OutboundMessage(
                channel=Channel.SMS,
                to_phone=phone,
                template=template,
                business_id=business_id,
                task_id=task_id,
            )
            return await self._send(msg, Urgency.NORMAL)
        if self.sms is not None:
            try:
                return await self.sms.send_template(phone, template)
            except Exception as e:  # noqa: BLE001
                log.error("business touch to %s failed: %r", mask_phone(phone), e)
        return None
