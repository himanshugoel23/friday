"""Notifier - the ONE way the backend sends messages (users, circle members,
businesses). ``c.notifier`` (FACTORIES["notifier"]).

Rules enforced here (callers just say what to send):

* **Channel**: chat goes via ``c.messaging`` (WhatsApp Cloud in live mode, the
  simulator channel otherwise); DLT SMS (``c.sms``) for business touches to
  non-WhatsApp numbers and as the user fallback when chat delivery fails.
* **24h window**: free-form text/buttons only within ``whatsapp_session_window_h``
  of the recipient's last inbound message; outside it, a pre-approved template is
  used (the caller's ``template`` or, for the user, a generic ``task_update`` /
  ``question`` / ``nudge`` template carrying the text).
* **Consent gate**: messages to a circle member (``person_id``) are refused unless
  ``Person.contact_consent == OPTED_IN`` - except the one-time opt-in request,
  which must be a template (``request_person_opt_in``).
* **Log**: every send is written to ``messages`` and published as ``MessageSent``.
  Logs never contain bodies or full numbers.

Refusals never raise: they return ``SendReceipt(ok=False, error=<reason>)``.

Owner: Backend Engineer A.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.events import EventBus, MessageSent
from friday.core.interfaces import MessagingChannel, SMSProvider
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    Business,
    Channel,
    Language,
    MidCallQuestion,
    OutboundMessage,
    Person,
    PersonConsent,
    ReplyButton,
    SendReceipt,
    TemplateRef,
    Urgency,
    new_id,
    question_button_id,
)

if TYPE_CHECKING:
    from friday.core.container import Container
    from friday.db.repositories import Repositories

log = get_logger(__name__)

# Refusal / error codes in SendReceipt.error
CONSENT_REQUIRED = "consent_required"
TEMPLATE_REQUIRED = "template_required"
UNKNOWN_RECIPIENT = "unknown_recipient"
NO_CHANNEL = "no_channel"

OPT_IN_REMINDER_AFTER = timedelta(days=7)

# DLT SMS template keys (Settings.sms_dlt_templates)
SMS_USER_UPDATE = "user_task_update"
SMS_BUSINESS_BOOKING = "business_booking_confirmed"


def button_title(text: str) -> str:
    """WhatsApp reply-button titles are max 20 chars."""
    text = " ".join(text.split())
    return text if len(text) <= 20 else text[:19] + "…"


def _template_language(lang: Language | None) -> str:
    return "hi" if lang == Language.HI else "en"


def _sms_param(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 30 else text[:29] + "…"


class Notifier:  # implements core.interfaces.Notifier
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Clock,
        bus: EventBus,
        repos: Repositories,
        messaging: MessagingChannel | None,
        sms: SMSProvider | None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.bus = bus
        self.repos = repos
        self.messaging = messaging
        self.sms = sms

    # ------------------------------------------------------------------ window
    def window(self) -> timedelta:
        return timedelta(hours=self.settings.whatsapp_session_window_h)

    def _open(self, last_inbound: datetime | None) -> bool:
        return last_inbound is not None and self.clock.now() - last_inbound < self.window()

    async def _last_inbound(self, msg: OutboundMessage) -> datetime | None:
        if msg.person_id is None and msg.business_id is None and msg.user_id:
            user = await self.repos.users.get(msg.user_id)
            if user is not None and user.phone == msg.to_phone:
                return user.last_inbound_at
        last = await self.repos.messages.last_inbound_from(msg.to_phone)
        return last.at if last else None

    async def in_window(self, msg: OutboundMessage) -> bool:
        return self._open(await self._last_inbound(msg))

    async def user_in_window(self, user_id: str) -> bool:
        user = await self.repos.users.get(user_id)
        return bool(user and self._open(user.last_inbound_at))

    # ------------------------------------------------------------------ core send
    async def send(
        self,
        msg: OutboundMessage,
        *,
        opt_in_request: bool = False,
        sms_fallback: bool = True,
        urgency: Urgency | None = None,
    ) -> SendReceipt:
        """Send ``msg`` applying consent, 24h window/template fallback and logging.
        ``urgency`` is accepted for the proactive engine's call shape; quiet hours and
        daily caps are the proactive guardrails' job, not the notifier's."""
        if self.messaging is None:
            return await self._refuse(msg, NO_CHANNEL)
        msg.channel = self.messaging.channel

        # --- consent gate for circle members
        if msg.person_id is not None:
            person = await self.repos.people.get(msg.person_id)
            if person is None:
                return await self._refuse(msg, UNKNOWN_RECIPIENT)
            allowed = person.contact_consent == PersonConsent.OPTED_IN or (
                opt_in_request
                and msg.template is not None
                and person.contact_consent != PersonConsent.OPTED_OUT
            )
            if not allowed:
                return await self._refuse(msg, CONSENT_REQUIRED)

        # --- SECURITY-15: a circle member's phone is gated even without person_id
        elif msg.business_id is None and not await self._phone_may_receive(msg, opt_in_request):
            return await self._refuse(msg, CONSENT_REQUIRED)

        # --- 24h window
        if msg.template is None and not await self.in_window(msg):
            if msg.person_id is None and msg.business_id is None and msg.user_id:
                msg = await self._as_user_template(msg)
            else:
                return await self._refuse(msg, TEMPLATE_REQUIRED)

        receipt = await self._deliver(msg)
        if (
            not receipt.ok
            and sms_fallback
            and msg.person_id is None
            and msg.business_id is None
            and msg.user_id
        ):
            await self._sms_fallback(msg)
        return receipt

    async def _phone_may_receive(self, msg: OutboundMessage, opt_in_request: bool) -> bool:
        """True unless ``msg.to_phone`` belongs to a circle member who hasn't opted in
        (and isn't the requesting user themself)."""
        people = await self.repos.people.find_by_phone(msg.to_phone)
        if not people:
            return True
        if msg.user_id:
            user = await self.repos.users.get(msg.user_id)
            if user is not None and user.phone == msg.to_phone:
                return True
        if opt_in_request and msg.template is not None:
            return all(p.contact_consent != PersonConsent.OPTED_OUT for p in people)
        return all(p.contact_consent == PersonConsent.OPTED_IN for p in people)

    async def _deliver(self, msg: OutboundMessage) -> SendReceipt:
        assert self.messaging is not None
        try:
            receipt = await self.messaging.send(msg)
        except Exception as e:  # noqa: BLE001 - provider bug must not kill callers
            log.warning("send to %s raised %s", mask_phone(msg.to_phone), type(e).__name__)
            receipt = SendReceipt(message_id=msg.id, ok=False, error=type(e).__name__)
        await self._log(msg, receipt)
        return receipt

    async def _as_user_template(self, msg: OutboundMessage) -> OutboundMessage:
        key = "question" if msg.question_id else "nudge" if msg.nudge_id else "task_update"
        profile = await self.repos.profiles.get(msg.user_id) if msg.user_id else None
        lang = _template_language(profile.language if profile else None)
        params = [msg.text or ""]
        return msg.model_copy(
            update={
                "template": TemplateRef(key=key, params=params, language=lang),
                "text": None,
                "buttons": [],
            }
        )

    async def _sms_fallback(self, msg: OutboundMessage) -> SendReceipt | None:
        if self.sms is None:
            return None
        text = msg.text or (msg.template.params[0] if msg.template and msg.template.params else "")
        tpl = TemplateRef(key=SMS_USER_UPDATE, params=[_sms_param(text or "update")])
        return await self.send_sms(msg.to_phone, tpl, user_id=msg.user_id, task_id=msg.task_id)

    async def send_sms(
        self,
        to_phone: str,
        template: TemplateRef,
        *,
        user_id: str | None = None,
        task_id: str | None = None,
        business_id: str | None = None,
        person_id: str | None = None,
        opt_in_request: bool = False,
    ) -> SendReceipt:
        """DLT template SMS. SECURITY-15: circle members (by ``person_id`` or by phone)
        only when OPTED_IN, except an explicit one-time ``opt_in_request``."""
        record = OutboundMessage(
            channel=Channel.SMS,
            to_phone=to_phone,
            user_id=user_id,
            template=template,
            task_id=task_id,
            business_id=business_id,
            person_id=person_id,
        )
        if person_id is not None:
            person = await self.repos.people.get(person_id)
            ok = person is not None and (
                person.contact_consent == PersonConsent.OPTED_IN
                or (opt_in_request and person.contact_consent != PersonConsent.OPTED_OUT)
            )
            if not ok:
                return await self._refuse(record, CONSENT_REQUIRED)
        if business_id is None and not await self._phone_may_receive(record, opt_in_request):
            return await self._refuse(record, CONSENT_REQUIRED)
        if self.sms is None:
            return await self._refuse(record, NO_CHANNEL)
        try:
            receipt = await self.sms.send_template(to_phone, template)
        except Exception as e:  # noqa: BLE001
            receipt = SendReceipt(message_id=record.id, ok=False, error=type(e).__name__)
        receipt = receipt.model_copy(update={"message_id": record.id})
        await self._log(record, receipt)
        return receipt

    async def _refuse(self, msg: OutboundMessage, reason: str) -> SendReceipt:
        log.info("refused message %s to %s: %s", msg.id, mask_phone(msg.to_phone), reason)
        return SendReceipt(message_id=msg.id, ok=False, error=reason, sent_at=self.clock.now())

    async def _log(self, msg: OutboundMessage, receipt: SendReceipt) -> None:
        try:
            await self.repos.messages.log_outbound(msg, receipt)
        except Exception:  # pragma: no cover - logging must not break sending
            log.exception("could not log outbound message %s", msg.id)
        await self.bus.publish(MessageSent(message=msg, ok=receipt.ok))

    # ------------------------------------------------------------------ users
    async def notify_user(
        self,
        user_id: str,
        text: str | None = None,
        *,
        buttons: Sequence[ReplyButton] = (),
        template: TemplateRef | None = None,
        task_id: str | None = None,
        nudge_id: str | None = None,
        question_id: str | None = None,
        media_url: str | None = None,
        media_mime: str | None = None,
    ) -> SendReceipt:
        user = await self.repos.users.get(user_id)
        if user is None:
            return SendReceipt(message_id=new_id(), ok=False, error=UNKNOWN_RECIPIENT)
        msg = OutboundMessage(
            channel=self.messaging.channel if self.messaging else Channel.SIMULATOR,
            to_phone=user.phone,
            user_id=user_id,
            text=text,
            buttons=list(buttons)[:3],
            template=template,
            task_id=task_id,
            nudge_id=nudge_id,
            question_id=question_id,
            media_url=media_url,
            media_mime=media_mime,
        )
        return await self.send(msg)

    async def ask_user(self, user_id: str, question: MidCallQuestion) -> SendReceipt:
        """Record a mid-call / approval question and send it with ``q:<id>:<i>``
        reply buttons (template ``question`` outside the 24h window)."""
        await self.repos.tasks.add_question(question)
        buttons = [
            ReplyButton(id=question_button_id(question.id, i), title=button_title(opt))
            for i, opt in enumerate(question.options[:3])
        ]
        return await self.notify_user(
            user_id,
            question.text,
            buttons=buttons,
            task_id=question.task_id,
            question_id=question.id,
        )

    # ------------------------------------------------------------------ circle members
    async def message_person(
        self,
        person_id: str,
        text: str | None = None,
        *,
        template: TemplateRef | None = None,
        buttons: Sequence[ReplyButton] = (),
        task_id: str | None = None,
    ) -> SendReceipt:
        """Message a circle member. Refused (CONSENT_REQUIRED) unless they opted in."""
        person = await self.repos.people.get(person_id)
        if person is None or not person.phone:
            return SendReceipt(message_id=new_id(), ok=False, error=UNKNOWN_RECIPIENT)
        msg = OutboundMessage(
            channel=self.messaging.channel if self.messaging else Channel.SIMULATOR,
            to_phone=person.phone,
            user_id=person.owner_user_id,
            person_id=person.id,
            text=text,
            template=template,
            buttons=list(buttons)[:3],
            task_id=task_id,
        )
        return await self.send(msg, sms_fallback=False)

    async def request_person_opt_in(
        self,
        person: Person,
        *,
        requester_name: str,
        what: str,
        template_key: str = "beneficiary_optin",
        reminder: bool = False,
    ) -> SendReceipt:
        """One-time opt-in request (template) to a circle member; marks consent PENDING.
        Template params: name, requester, relation, what (PRD §8.1).

        SECURITY-16: at most one request per person; ``reminder=True`` allows ONE more,
        no sooner than 7 days after the first. Suppressed phones (anyone who said STOP
        to any owner) never get a request."""
        person = await self.repos.people.get(person.id) or person
        if not person.phone:
            return SendReceipt(message_id=new_id(), ok=False, error=UNKNOWN_RECIPIENT)
        if person.contact_consent in (PersonConsent.OPTED_IN, PersonConsent.OPTED_OUT):
            return SendReceipt(
                message_id=new_id(), ok=False, error=f"already {person.contact_consent.value}"
            )
        if await self.repos.suppressions.is_suppressed(person.phone):
            return SendReceipt(message_id=new_id(), ok=False, error="suppressed")
        if person.contact_consent == PersonConsent.PENDING:
            sent = [
                e
                for e in await self.repos.audit.list_for_user(person.owner_user_id, limit=500)
                if e.action == "consent.optin_requested" and e.subject_id == person.id
            ]
            too_soon = bool(sent) and self.clock.now() - min(e.at for e in sent) < OPT_IN_REMINDER_AFTER
            if not reminder or len(sent) >= 2 or too_soon:
                return SendReceipt(message_id=new_id(), ok=False, error="already pending")
        tpl = TemplateRef(
            key=template_key,
            params=[person.name, requester_name, person.relation or "family", what],
            language=_template_language(person.language),
        )
        msg = OutboundMessage(
            channel=self.messaging.channel if self.messaging else Channel.SIMULATOR,
            to_phone=person.phone,
            user_id=person.owner_user_id,
            person_id=person.id,
            template=tpl,
        )
        receipt = await self.send(msg, opt_in_request=True, sms_fallback=False)
        if receipt.ok:
            person.contact_consent = PersonConsent.PENDING
            await self.repos.people.upsert(person)
            await self.repos.audit.log(
                "consent.optin_requested", user_id=person.owner_user_id, subject_id=person.id
            )
        return receipt

    # ------------------------------------------------------------------ businesses (B15, US-12)
    async def message_business(
        self,
        business: Business,
        text: str | None = None,
        *,
        template: TemplateRef | None = None,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> SendReceipt:
        """WhatsApp-to-business (B15). Needs ``business.whatsapp_phone``; outside the
        business's 24h window only ``template`` (e.g. ``biz_request``) is allowed."""
        if not business.whatsapp_phone:
            return SendReceipt(message_id=new_id(), ok=False, error=UNKNOWN_RECIPIENT)
        msg = OutboundMessage(
            channel=self.messaging.channel if self.messaging else Channel.SIMULATOR,
            to_phone=business.whatsapp_phone,
            user_id=user_id,
            business_id=business.id,
            text=text,
            template=template,
            task_id=task_id,
        )
        return await self.send(msg, sms_fallback=False)

    async def business_touch(
        self,
        business: Business,
        template: TemplateRef,
        *,
        user_id: str | None = None,
        task_id: str | None = None,
        sms_template: TemplateRef | None = None,
    ) -> SendReceipt:
        """End-of-call touch (US-12): WA template if the business is on WhatsApp,
        else DLT SMS to an Indian mobile; landlines get nothing."""
        if business.whatsapp_phone:
            receipt = await self.message_business(
                business, template=template, user_id=user_id, task_id=task_id
            )
            if receipt.ok:
                await self._touch_audit(business, user_id, "whatsapp")
                return receipt
        if not _is_indian_mobile(business.phone):
            return SendReceipt(message_id=new_id(), ok=False, error="not_a_mobile")
        sms_tpl = sms_template or TemplateRef(
            key=SMS_BUSINESS_BOOKING, params=[_sms_param(p) for p in template.params]
        )
        receipt = await self.send_sms(
            business.phone, sms_tpl, user_id=user_id, task_id=task_id, business_id=business.id
        )
        if receipt.ok:
            await self._touch_audit(business, user_id, "sms")
        return receipt

    async def _touch_audit(self, business: Business, user_id: str | None, channel: str) -> None:
        await self.repos.audit.log(
            "business_touch_sent", user_id=user_id, subject_id=business.id, channel=channel
        )


def _is_indian_mobile(phone: str) -> bool:
    digits = phone.lstrip("+")
    return digits.startswith("91") and len(digits) == 12 and digits[2] in "6789"


def build_notifier(c: Container) -> Notifier:
    def _maybe(name: str) -> Any:
        from friday.core.container import ComponentNotAvailable

        try:
            return c.get(name)
        except ComponentNotAvailable:
            log.warning("notifier: %s not available", name)
            return None

    return Notifier(
        settings=c.settings,
        clock=c.clock,
        bus=c.bus,
        repos=c.repos,
        messaging=_maybe("messaging"),
        sms=_maybe("sms"),
    )
