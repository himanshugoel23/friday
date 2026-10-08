"""Inbound pipeline: every message from any channel ends up in ``handle()``.

    InboundMessage
      -> de-dupe (provider id) -> voice note? fetch_media + STT
      -> who is it?  user | circle member (opt-in replies, relayed) | business (B15) | new
      -> log (PIN-looking text redacted) + last_inbound_at (24h window) + MessageReceived
      -> waitlist / onboarding / pending PIN action / button payloads / brain.interpret
      -> dispatch on Interpretation -> reply through the notifier

Task-engine calls are duck-typed (``submit``, ``handle_answer``, ``approve``,
``choose``, ``cancel``, ``update_spec``) - see docs/CORE_CHANGES.md (TaskEngine
Protocol). If the engine (or a method) is missing, the task stays persisted in
CREATED / the answer stays recorded + ``UserAnswerReceived`` is published.

Owner: Backend Engineer A.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from friday.api.callbacks import CallbackService
from friday.api.context import build_context
from friday.api.costs import AbuseLimiter, CostTracker
from friday.api.onboarding import OnboardingFlow
from friday.api.security import PinCheck, PinHasher, PinService, extract_pin
from friday.api.state import SLOW_DOWN, InboundThrottle, PendingAction, UserState
from friday.core.clock import format_ist
from friday.core.container import ComponentNotAvailable
from friday.core.events import MessageReceived, TaskStatusChanged, UserAnswerReceived
from friday.core.interfaces import Brain, TaskEngine
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    AudioClip,
    AutonomyLevel,
    Beneficiary,
    Consent,
    ConsentKind,
    ConversationContext,
    FeedbackType,
    InboundMessage,
    Intent,
    Interpretation,
    Invite,
    MessageKind,
    NudgeFeedback,
    NudgeStatus,
    OutboundMessage,
    Person,
    PersonConsent,
    Place,
    PlaceSource,
    Profile,
    QuestionPurpose,
    ReplyButton,
    Task,
    TaskSpec,
    TaskStatus,
    TemplateRef,
    User,
    UserAnswer,
    UserStatus,
    normalize_phone,
    parse_button_id,
)
from friday.db.repositories import MatchStatus
from friday.db.repositories._base import phone_index

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

REDACTED = "[redacted]"
# WhatsApp "system" events that signal a possible account takeover (SECURITY-23).
FREEZE_SIGNALS = frozenset({"user_changed_number", "customer_identity_changed", "sim_swap"})
STEP_UP_DELEGATION_INR = 5000
PIN_TOKEN = "[PIN]"
FOUR_DIGITS_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")
PIN_TOKEN_STRIP_RE = re.compile(r"\[PIN\]|[\s.,!?;:]+", re.I)
# Task states in which a mid-call / approval question may be answered (SECURITY-9).
ANSWERABLE_STATUSES = frozenset(
    {
        TaskStatus.AWAITING_USER,
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.AWAITING_CHOICE,  # QA BUG-3: comparison choice taps were swallowed
        TaskStatus.CALLING,
    }
)
PROFILE_FIELDS = {
    "name",
    "city",
    "language",
    "tone",
    "morning_briefing",
    "briefing_hour_ist",
    "preferred_channel",
}
YES_RE = re.compile(r"^\s*(yes|y|haan|ha|han|haa|1|ok|okay|हाँ|हां|ji|haan ji)\s*[.!]*\s*$", re.I)
STOP_RE = re.compile(r"^\s*(stop|no|nahi|nahin|n|2|unsubscribe|band karo|नहीं)\s*[.!]*\s*$", re.I)
CANCEL_RE = re.compile(r"^\s*(cancel|no|nahi|stop|chhodo|rehne do)\b", re.I)
NEGATIVE_OPTION_RE = re.compile(r"\b(no|don'?t|neither|cancel|nahi|mat|none|skip|reject)\b", re.I)
CARD_RE = re.compile(r"^\d{13,19}$")
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PIN_NEEDED = "This needs your Friday PIN. Please type it (I'll never show it back)."
PIN_NOT_SET = "You haven't set a Friday PIN yet, so I can't do that. Say 'set PIN' to create one."
PIN_WRONG = "That PIN didn't match. {left} tries left."
PIN_LOCKED = "PIN-protected actions are locked for 30 minutes. Please try again later."
PIN_LOOKALIKE = (
    "Looks like your PIN. Please delete that message. "
    "I only ask for it when you start a sensitive action."
)
DELETE_CONFIRM = (
    "This will permanently delete your profile, memory, people, places, recordings, "
    "transcripts and messages, and cancel pending tasks. Type DELETE to confirm."
)
DELETE_DONE = "Done. Everything's deleted. If you ever come back, just say hi."
CANCELLED = "Okay, cancelled. Nothing changed."
RATE_LIMITED = "I'm handling a lot right now. I'll pick this up at {when}."


class InboundPipeline:
    NO_BRAIN = "I'm still waking up (my brain module isn't connected yet). Try again soon."
    PENDING_TTL = timedelta(minutes=10)

    def __init__(self, c: Container, *, fast_pin_hash: bool = False) -> None:
        self.c = c
        self.settings = c.settings
        self.clock = c.clock
        self.bus = c.bus
        self.repos = c.repos
        self.notifier = c.notifier
        self.pins = PinService(
            PinHasher(
                self.settings.key_material("pin_pepper"),
                fast=fast_pin_hash,
                legacy=(self.settings.secret_key.get_secret_value(),),
            ),
            self.repos.users,
            self.clock,
            self.settings.pin_max_attempts,
            self.repos.pin_locks,
        )
        self.costs = CostTracker(self.settings, self.clock, self.bus, self.repos)
        self.limiter = AbuseLimiter(self.settings, self.clock, self.repos)
        self.onboarding = OnboardingFlow(self)
        self.callbacks = CallbackService(c)
        cache = self._opt("cache")
        self.state = UserState(cache)
        self.throttle = InboundThrottle(cache)

    # ------------------------------------------------------------------ optional components
    def _opt(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except ComponentNotAvailable:
            return None

    def brain(self) -> Brain | None:
        return self._opt("brain")

    def engine(self) -> TaskEngine | None:
        """``core.interfaces.TaskEngine`` (Backend B). Methods are called by their
        Protocol names; a partial engine (tests, staged rollout) is tolerated."""
        return self._opt("task_engine")

    async def _engine_call(self, names: tuple[str, ...], *args: Any, **kw: Any) -> bool:
        engine: Any = self.engine()
        if engine is None:
            return False
        for name in names:
            fn = getattr(engine, name, None)
            if callable(fn):
                res = fn(*args, **kw)
                if hasattr(res, "__await__"):
                    await res
                return True
        return False

    # ------------------------------------------------------------------ helpers
    async def reply(
        self,
        user: User,
        text: str | None,
        buttons: list[ReplyButton] | tuple[ReplyButton, ...] = (),
        *,
        task_id: str | None = None,
    ) -> None:
        if not text and not buttons:
            return
        await self.notifier.notify_user(user.id, text, buttons=list(buttons), task_id=task_id)

    async def audit(
        self, action: str, user: User | None, *, actor: str = "friday", **detail: Any
    ) -> None:
        subject = detail.pop("subject_id", None)
        await self.repos.audit.log(
            action, user_id=user.id if user else None, actor=actor, subject_id=subject, **detail
        )

    async def context(self, user: User) -> ConversationContext:
        return await build_context(self.repos, self.clock, user)

    async def apply_profile_updates(self, user: User, updates: dict[str, Any]) -> Profile:
        profile = await self.repos.profiles.get_or_default(user.id)
        clean = {k: v for k, v in updates.items() if k in PROFILE_FIELDS and v is not None}
        try:
            profile = Profile.model_validate({**profile.model_dump(), **clean})
        except ValidationError:
            log.info("ignored invalid profile update for user %s", user.id)
            profile = await self.repos.profiles.get_or_default(user.id)
            for k, v in clean.items():  # apply the valid ones individually
                try:
                    profile = Profile.model_validate({**profile.model_dump(), k: v})
                except ValidationError:
                    continue
        return await self.repos.profiles.save(profile)

    async def upsert_person(self, user: User, person: Person) -> Person:
        existing = await self.repos.people.get(person.id)
        if existing is not None and existing.owner_user_id != user.id:
            existing = None
            person = person.model_copy(update={"id": _new_id()})
        data = person.model_dump()
        data["owner_user_id"] = user.id
        if data.get("phone"):
            try:
                data["phone"] = normalize_phone(data["phone"], self.settings.default_country_code)
            except ValueError:
                data["phone"] = None
        if data.get("relation"):
            data["relation"] = str(data["relation"]).strip().lower()
        # Consent can only come from the person themself, never from the brain/user.
        keep = existing or Person(owner_user_id=user.id, name=person.name)
        data["contact_consent"] = keep.contact_consent
        data["consent_at"] = keep.consent_at
        data["checkin_consent"] = keep.checkin_consent
        data["linked_user_id"] = keep.linked_user_id
        if existing is not None:
            data["created_at"] = existing.created_at
            data["aliases"] = sorted(set(existing.aliases) | set(data.get("aliases") or []))
            if not data.get("notes"):
                data["notes"] = existing.notes
        saved = await self.repos.people.upsert(Person.model_validate(data))
        await self.audit("person.upserted", user, subject_id=saved.id)
        return saved

    async def save_place(
        self, user: User, place: Place, msg: InboundMessage | None = None
    ) -> Place:
        existing = await self.repos.places.get(place.id)
        data = place.model_dump()
        data["owner_user_id"] = user.id
        if existing is not None and existing.owner_user_id != user.id:
            data["id"] = _new_id()
            existing = None
        if data.get("person_id"):
            person = await self.repos.people.get(data["person_id"])
            if person is None or person.owner_user_id != user.id:
                data["person_id"] = None
        geocoder = self._opt("geocoder")
        result = None
        try:
            if msg is not None and msg.location is not None and place.location is None:
                from friday.core.models import GeoPoint

                data["location"] = GeoPoint(lat=msg.location.lat, lng=msg.location.lng)
                data["source"] = PlaceSource.WA_LOCATION
                if msg.location.address and not data.get("address_text"):
                    data["address_text"] = msg.location.address
                if geocoder is not None:
                    result = await geocoder.reverse(data["location"])
            elif geocoder is not None and data.get("location") is None and data.get("address_text"):
                text = data["address_text"]
                if "maps.app.goo.gl" in text or "google.com/maps" in text or "goo.gl/maps" in text:
                    result = await geocoder.resolve_maps_link(text.strip())
                    data["source"] = PlaceSource.MAPS_LINK
                else:
                    result = await geocoder.geocode(text)
        except Exception as e:  # noqa: BLE001 - geocoding is best effort
            log.info("geocoding failed for a place of user %s: %s", user.id, type(e).__name__)
        if result is not None:
            data["location"] = data.get("location") or result.location
            data["formatted_address"] = result.formatted_address
            data["city"] = data.get("city") or result.city
        if existing is not None:
            data["created_at"] = existing.created_at
            data["aliases"] = sorted(set(existing.aliases) | set(data.get("aliases") or []))
        saved = await self.repos.places.upsert(Place.model_validate(data))
        await self.audit("place.upserted", user, subject_id=saved.id)
        return saved

    # ------------------------------------------------------------------ main entry
    async def handle(self, msg: InboundMessage) -> None:
        try:
            msg.from_phone = normalize_phone(msg.from_phone, self.settings.default_country_code)
        except ValueError:
            log.info("dropping inbound message with invalid sender")
            return
        if msg.provider_message_id and await self.repos.messages.seen_provider_id(
            msg.provider_message_id
        ):
            return  # provider retry
        if msg.kind == MessageKind.VOICE_NOTE and not msg.text:
            msg.text = await self._transcribe(msg)

        user = await self.repos.users.get_by_phone(msg.from_phone)
        if user is None:
            people = await self.repos.people.find_by_phone(msg.from_phone)
            if people:
                await self._from_circle_member(msg, people)
                return
            if await self._from_business(msg):
                return
            await self._new_user(msg)
            return

        if user.status in (UserStatus.SUSPENDED, UserStatus.DELETED):
            return
        msg.user_id = user.id
        if msg.kind == MessageKind.SYSTEM:
            if (msg.text or "").lower() in FREEZE_SIGNALS:
                await self.freeze_sensitive_actions(user, reason=(msg.text or "").lower())
            return
        sender = phone_index(msg.from_phone)
        if not await self.throttle.allow(sender, self.clock.now()):
            # SECURITY-21: logged (redacted), answered at most once, never sent to the LLM.
            await self.repos.messages.log_inbound(msg.model_copy(update={"text": REDACTED}))
            if await self.throttle.first_notice(sender, self.clock.now()):
                await self.reply(user, SLOW_DOWN)
            return
        redact = await self._looks_sensitive(user, msg)
        pin_in_text = False
        if not redact and user.pin_hash and msg.text:
            msg.text, pin_in_text = self._redact_pin_groups(user, msg.text)
        await self._log_inbound(user, msg, redact=redact)
        if pin_in_text:
            # SECURITY-11 / E18: the PIN never reaches the log or the LLM; a PIN typed
            # outside a PIN prompt is never used as verification.
            await self.reply(user, PIN_LOOKALIKE)
            if not PIN_TOKEN_STRIP_RE.sub("", msg.text or ""):
                return

        if user.status == UserStatus.WAITLISTED:
            await self.onboarding.waitlisted(user, msg)
            return
        if user.status == UserStatus.ONBOARDING:
            await self.onboarding.handle(user, msg)
            return
        await self._active(user, msg)

    async def _transcribe(self, msg: InboundMessage) -> str | None:
        if not msg.media_url:
            return None
        messaging = self._opt("messaging")
        if messaging is None:
            return None
        try:
            blob = await messaging.fetch_media(msg.media_url)
        except Exception as e:  # noqa: BLE001
            log.info("voice note download failed: %s", type(e).__name__)
            return None
        stt = self._opt("stt")
        if stt is not None:
            try:
                tr = await stt.transcribe(AudioClip(data=blob.data, mime=blob.mime))
                return tr.text
            except Exception as e:  # noqa: BLE001
                log.info("voice note STT failed: %s", type(e).__name__)
        if msg.media_url.startswith("sim-media:"):  # simulator: media carries the words
            return blob.data.decode("utf-8", "replace")
        return None

    def _redact_pin_groups(self, user: User, text: str) -> tuple[str, bool]:
        """Replace every 4-digit group (max 3 checked) that matches the user's PIN."""
        hit = False
        for group in FOUR_DIGITS_RE.findall(text)[:3]:
            if self.pins.matches(user, group):
                text = re.sub(rf"(?<!\d){group}(?!\d)", PIN_TOKEN, text)
                hit = True
        return text, hit

    async def _looks_sensitive(self, user: User, msg: InboundMessage) -> bool:
        if self.onboarding.awaiting_pin(user):
            return True
        pending = await self.state.get_pending(user.id, self.clock.now())
        return pending is not None and pending.kind == "pin"

    async def _log_inbound(self, user: User, msg: InboundMessage, *, redact: bool) -> None:
        logged = msg.model_copy(update={"text": REDACTED}) if redact and msg.text else msg
        await self.repos.messages.log_inbound(logged)
        user.last_inbound_at = msg.received_at
        await self.repos.users.save(user)
        await self.bus.publish(MessageReceived(message=logged))

    # ------------------------------------------------------------------ non-users
    async def _new_user(self, msg: InboundMessage) -> None:
        user = User(
            phone=msg.from_phone,
            status=UserStatus.ONBOARDING,
            invites_remaining=0,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        user.onboarding_step = self.onboarding.first_step(user)
        await self.repos.users.add(user)
        msg.user_id = user.id
        await self.audit("user.created", user)
        await self._log_inbound(user, msg, redact=False)
        log.info("new user %s from %s", user.id, mask_phone(user.phone))
        await self.onboarding.start(user, msg)

    async def _from_circle_member(self, msg: InboundMessage, people: list[Person]) -> None:
        """Circle members can only opt in/out; anything else is relayed to the owner
        verbatim and never treated as a command (US-22)."""
        text = (msg.text or "").strip()
        is_yes = bool(YES_RE.match(text)) or (msg.button_id or "").endswith(":yes")
        is_stop = bool(STOP_RE.match(text)) or (msg.button_id or "").endswith(":no")
        for person in people:
            logged = msg.model_copy(
                update={"id": _new_id(), "user_id": person.owner_user_id, "person_id": person.id}
            )
            await self.repos.messages.log_inbound(logged)
            owner = await self.repos.users.get(person.owner_user_id)
            if owner is None:
                continue
            if person.contact_consent == PersonConsent.PENDING and (is_yes or is_stop):
                granted = is_yes
                person.contact_consent = (
                    PersonConsent.OPTED_IN if granted else PersonConsent.OPTED_OUT
                )
                person.consent_at = self.clock.now()
                await self.repos.people.upsert(person)
                await self.repos.consents.add(
                    Consent(
                        user_id=owner.id,
                        person_id=person.id,
                        kind=ConsentKind.BENEFICIARY_CONTACT,
                        granted=granted,
                        evidence_text=text[:200] or msg.button_id,
                        message_id=msg.id,
                        recorded_at=self.clock.now(),
                    )
                )
                await self.audit(
                    "consent.beneficiary_" + ("granted" if granted else "declined"),
                    owner,
                    subject_id=person.id,
                )
                note = (
                    f"{person.name} said yes. I can now send them confirmations and reminders."
                    if granted
                    else f"{person.name} said no, so I won't message them."
                )
                await self.reply(owner, note)
                continue
            if (
                person.contact_consent == PersonConsent.OPTED_IN
                and is_stop
                and text.lower() == "stop"
            ):
                person.contact_consent = PersonConsent.OPTED_OUT
                person.consent_at = self.clock.now()
                await self.repos.people.upsert(person)
                await self.repos.consents.add(
                    Consent(
                        user_id=owner.id,
                        person_id=person.id,
                        kind=ConsentKind.BENEFICIARY_CONTACT,
                        granted=False,
                        evidence_text="STOP",
                        message_id=msg.id,
                        recorded_at=self.clock.now(),
                    )
                )
                await self.audit("consent.beneficiary_revoked", owner, subject_id=person.id)
                await self.reply(owner, f"{person.name} asked me to stop messaging them. Done.")
                continue
            if person.contact_consent in (PersonConsent.OPTED_IN, PersonConsent.PENDING) and text:
                await self.reply(owner, f'{person.name} replied: "{text[:500]}"')

    async def _from_business(self, msg: InboundMessage) -> bool:
        """WhatsApp/SMS from a business number (known business or a number Friday
        called): hand to the engine's business-reply matching, never the user flow.
        Nothing is ever sent back from here (no user details to unmatched senders)."""
        business = await self.repos.businesses.get_by_phone(msg.from_phone)
        match = await self.callbacks.match(msg.from_phone)
        if business is None and match.status == MatchStatus.UNMATCHED:
            return False
        msg.business_id = business.id if business else match.business_id
        if msg.business_id and await self.repos.businesses.get(msg.business_id) is None:
            msg.business_id = None
        msg.user_id = match.user_id  # only for a unique match (purge cascades)
        if msg.kind in (MessageKind.VOICE_NOTE,) and not msg.text:
            msg.text = await self._transcribe(msg)
        await self.repos.messages.log_inbound(msg)
        await self.bus.publish(MessageReceived(message=msg))
        await self.callbacks.on_business_message(msg, match)
        return True

    # ------------------------------------------------------------------ active users
    async def _active(self, user: User, msg: InboundMessage) -> None:
        pending = await self.state.get_pending(user.id, self.clock.now())
        if pending is not None:
            await self._continue_pending(user, msg, pending)
            return

        if msg.kind == MessageKind.BUTTON_REPLY and msg.button_id and await self._button(user, msg):
            return

        brain = self.brain()
        if brain is None:
            await self.reply(user, self.NO_BRAIN)
            return
        ctx = await self.context(user)
        interp: Interpretation = await brain.interpret(ctx, msg)
        if (
            interp.answer is None
            and interp.intent == Intent.ANSWER_QUESTION
            and ctx.pending_question
        ):
            interp.answer = UserAnswer(
                question_id=ctx.pending_question.id,
                text=msg.text or "",
                message_id=msg.id,
                answered_at=self.clock.now(),
            )
        await self.execute(user, msg, interp)

    async def _continue_pending(
        self, user: User, msg: InboundMessage, pending: PendingAction
    ) -> None:
        text = (msg.text or "").strip()
        if pending.kind == "pin":
            pin = extract_pin(text)
            if pin is None:
                if CANCEL_RE.match(text):
                    await self.state.clear_pending(user.id)
                    await self.reply(user, CANCELLED)
                else:
                    await self.reply(user, PIN_NEEDED)
                return
            result = await self.pins.verify(user, pin)
            if result.status == PinCheck.OK:
                await self.state.clear_pending(user.id)
                await self.audit("pin.verified", user)
                assert pending.interpretation is not None and pending.message is not None
                await self.state.mark_stepped_up(user.id)
                await self.execute(user, pending.message, pending.interpretation, pin_verified=True)
            elif result.status == PinCheck.WRONG:
                await self.audit("pin.failed", user)
                await self.reply(user, PIN_WRONG.format(left=result.attempts_left))
            elif result.status == PinCheck.LOCKED:
                await self.state.clear_pending(user.id)
                await self.reply(user, PIN_LOCKED)
            else:
                await self.state.clear_pending(user.id)
                await self.reply(user, PIN_NOT_SET)
            return
        if pending.kind == "delete_confirm":
            await self.state.clear_pending(user.id)
            if text.upper() == "DELETE":
                await self.delete_everything(user)
            else:
                await self.reply(user, CANCELLED)
            return
        await self.state.clear_pending(user.id)  # unknown kind: drop

    # ------------------------------------------------------------------ buttons
    async def _button(self, user: User, msg: InboundMessage) -> bool:
        """Handle our own payloads (q:/a:/n:). False -> let the brain interpret."""
        parsed = parse_button_id(msg.button_id or "")
        if parsed is None:
            q = await self.repos.tasks.open_question_for_user(user.id)
            if q is not None and msg.text and msg.text.lower().startswith("answer"):
                await self.notifier.ask_user(user.id, q)  # template tap -> resend freeform
                return True
            return False
        kind, ref, value = parsed
        if kind == "q":
            question = await self.repos.tasks.get_question(ref)
            if question is None or not await self._may_answer(user, question.task_id):
                return True  # SECURITY-9: foreign/stale question - swallow, never forward
            try:
                idx = int(value)
                option = question.options[idx]
            except (ValueError, IndexError):
                return False
            approves = question.purpose == QuestionPurpose.APPROVE_BOOKING and not bool(
                NEGATIVE_OPTION_RE.search(option)
            )
            answer = UserAnswer(
                question_id=question.id,
                text=option,
                option_index=idx,
                approves=approves,
                message_id=msg.id,
                answered_at=self.clock.now(),
            )
            await self._record_answer(user, answer)
            return True
        if kind == "a":
            task = await self.repos.tasks.get(ref)
            if task is None or task.requester_user_id != user.id:
                return False
            approve = value == "yes"
            await self.audit("task.approval", user, subject_id=task.id, approved=approve)
            if not await self._engine_call(("approve",), task.id, approve) and not approve:
                await self._cancel_task(user, task)
            return True
        if kind == "n":
            await self._nudge_action(user, ref, value, msg)
            return True
        return False

    async def _may_answer(self, user: User, task_id: str) -> bool:
        """SECURITY-9: only the task's requester, and only while the task is waiting."""
        task = await self.repos.tasks.get(task_id)
        return (
            task is not None
            and task.requester_user_id == user.id
            and task.status in ANSWERABLE_STATUSES
        )

    async def _record_answer(self, user: User, answer: UserAnswer) -> None:
        question = await self.repos.tasks.get_question(answer.question_id)
        if question is None or not await self._may_answer(user, question.task_id):
            log.info("ignored answer to a foreign or stale question from user %s", user.id)
            return
        stored = await self.repos.tasks.answer_question(answer)
        if not stored:
            return
        await self.audit("question.answered", user, subject_id=answer.question_id)
        await self.bus.publish(UserAnswerReceived(answer=answer))
        await self._engine_call(("handle_answer",), answer)

    async def _nudge_action(
        self, user: User, nudge_id: str, action: str, msg: InboundMessage
    ) -> None:
        nudge = await self.repos.nudges.get(nudge_id)
        if nudge is None or nudge.user_id != user.id:
            return
        proactive = self._opt("proactive")
        handler = getattr(proactive, "handle_nudge_action", None) if proactive else None
        if callable(handler):
            res = handler(nudge, action)
            if hasattr(res, "__await__"):
                await res
            return
        a = action.lower()
        fb = (
            FeedbackType.STOP
            if a in ("stop", "off")
            else FeedbackType.DISMISSED
            if a in ("no", "dismiss", "later", "not_now", "skip")
            else FeedbackType.SNOOZED
            if a == "snooze"
            else FeedbackType.ACTED
        )
        now = self.clock.now()
        await self.repos.nudges.add_feedback(
            NudgeFeedback(nudge_id=nudge.id, user_id=user.id, type=fb, at=now)
        )
        nudge.responded_at = now
        nudge.status = NudgeStatus.ACTED if fb == FeedbackType.ACTED else NudgeStatus.DISMISSED
        await self.repos.nudges.save(nudge)
        if fb == FeedbackType.ACTED and nudge.proposed_task is not None:
            await self.create_task(user, nudge.proposed_task, msg)
            await self.reply(user, "On it.")

    # ------------------------------------------------------------------ dispatch
    async def execute(
        self, user: User, msg: InboundMessage, interp: Interpretation, *, pin_verified: bool = False
    ) -> None:
        intent = interp.intent
        needs_pin = (
            interp.requires_pin
            or intent in (Intent.DELETE_DATA, Intent.SAVE_IDENTIFIER)
            or any(a.level == AutonomyLevel.ACT_AUTOMATICALLY for a in interp.autonomy_updates)
            or (
                await self._sensitive_read(user, interp)
                and not await self.state.stepped_up(user.id)
            )
        )
        if needs_pin and not pin_verified:
            if not user.pin_hash:
                await self.reply(user, PIN_NOT_SET)
                return
            if await self.pins.is_locked(user):
                await self.reply(user, PIN_LOCKED)
                return
            await self.state.set_pending(
                user.id,
                PendingAction(
                    kind="pin",
                    interpretation=interp,
                    message=msg,
                    expires_at=self.clock.now() + self.PENDING_TTL,
                ),
            )
            await self.reply(user, PIN_NEEDED)
            return

        reply, buttons = interp.reply, list(interp.buttons)
        await self._learn_aliases(user, interp)
        for fact in interp.facts:  # REMEMBER or incidental extraction
            await self._save_fact(user, fact, msg)

        if intent == Intent.NEW_TASK and interp.task_spec is not None:
            task, queued_until = await self.create_task(user, interp.task_spec, msg, interp=interp)
            if queued_until is not None:
                reply = RATE_LIMITED.format(when=format_ist(queued_until, "%I:%M %p"))
                buttons = []
        elif intent == Intent.TASK_UPDATE and interp.task_spec is not None and interp.task_id:
            await self._update_task(user, interp.task_id, interp.task_spec)
        elif intent == Intent.ANSWER_QUESTION and interp.answer is not None:
            interp.answer.message_id = interp.answer.message_id or msg.id
            await self._record_answer(user, interp.answer)
        elif intent in (Intent.APPROVE, Intent.REJECT):
            await self._approve(user, interp, approve=intent == Intent.APPROVE)
        elif intent == Intent.CHOOSE and interp.task_id is not None:
            task = await self.repos.tasks.get(interp.task_id)
            if task is not None and task.requester_user_id == user.id:
                await self.audit("task.choice", user, subject_id=task.id, index=interp.choice_index)
                await self._engine_call(("choose",), task.id, interp.choice_index)
        elif intent == Intent.CANCEL_TASK and interp.task_id is not None:
            task = await self.repos.tasks.get(interp.task_id)
            if task is not None and task.requester_user_id == user.id:
                await self._cancel_task(user, task)
        elif intent == Intent.RATE_VENDOR:
            for vi in interp.vendor_interactions:
                if await self.repos.businesses.get(vi.business_id) is None:
                    continue
                await self.repos.businesses.add_interaction(
                    vi.model_copy(update={"user_id": user.id, "at": self.clock.now()})
                )
        elif intent == Intent.ADD_PERSON and interp.person_upsert is not None:
            await self.upsert_person(user, interp.person_upsert)
        elif intent == Intent.ADD_PLACE:
            place = interp.place_upsert
            if place is None and msg.location is not None:
                place = Place(owner_user_id=user.id, label=msg.location.name or "Pinned location")
            if place is not None:
                await self.save_place(user, place, msg)
        elif intent == Intent.SAVE_IDENTIFIER and interp.identifier_upsert is not None:
            ident = interp.identifier_upsert
            if CARD_RE.match(re.sub(r"[\s-]", "", ident.value)):
                reply = "I can't store full card numbers. Please delete that message."
                buttons = []
            else:
                await self.repos.identifiers.upsert(ident.model_copy(update={"user_id": user.id}))
                await self.audit("identifier.saved", user, subject_id=ident.id)
                reply = reply or f"Saved {ident.label} ({ident.masked})."
        elif intent == Intent.SETTINGS:
            if interp.profile_updates:
                await self.apply_profile_updates(user, interp.profile_updates)
            for a in interp.autonomy_updates:
                await self.repos.autonomy.upsert(a.model_copy(update={"user_id": user.id}))
            await self.audit("settings.changed", user)
        elif intent == Intent.DELETE_DATA:
            await self.state.set_pending(
                user.id,
                PendingAction(
                    kind="delete_confirm",
                    interpretation=None,
                    message=None,
                    expires_at=self.clock.now() + self.PENDING_TTL,
                ),
            )
            reply, buttons = DELETE_CONFIRM, []
        elif intent == Intent.INVITE:
            reply, buttons = await self._invites(user), []

        await self.reply(user, reply, buttons)

    async def _sensitive_read(self, user: User, interp: Interpretation) -> bool:
        """SECURITY-23 step-up (enforced by intent, not only the brain's flag):
        memory queries (notes, addresses, identifiers, circle), changing a circle
        member's phone, and large delegations. A verified PIN covers 10 minutes."""
        if interp.intent == Intent.QUERY_MEMORY:
            return True
        if interp.intent == Intent.ADD_PERSON and interp.person_upsert is not None:
            existing = await self.repos.people.get(interp.person_upsert.id)
            new_phone = interp.person_upsert.phone
            if existing is not None and existing.owner_user_id == user.id and new_phone:
                try:
                    new_phone = normalize_phone(new_phone, self.settings.default_country_code)
                except ValueError:
                    return True
                return new_phone != existing.phone
        if interp.intent in (Intent.NEW_TASK, Intent.TASK_UPDATE) and interp.task_spec:
            d = interp.task_spec.delegation
            return d.granted and (
                d.max_price_inr is None or d.max_price_inr >= STEP_UP_DELEGATION_INR
            )
        return False

    async def freeze_sensitive_actions(self, user: User, *, reason: str) -> None:
        """Re-registration / SIM-swap signal: freeze PIN-gated actions for 24 h and
        tell the user by SMS (their WhatsApp may be the compromised channel)."""
        await self.pins.freeze(user, reason=reason)
        await self.state.clear_user(user.id)
        await self.audit("security.freeze", user, actor="system", reason=reason)
        await self.notifier.send_sms(
            user.phone,
            TemplateRef(key="user_task_update", params=["Security hold 24h"]),
            user_id=user.id,
        )

    async def _learn_aliases(self, user: User, interp: Interpretation) -> None:
        if interp.resolution is None:
            return
        for al in interp.resolution.new_aliases:
            alias = al.alias.strip()
            if not alias:
                continue
            if al.target == "person":
                person = await self.repos.people.get(al.target_id)
                if person and person.owner_user_id == user.id and alias not in person.aliases:
                    person.aliases = [*person.aliases, alias]
                    await self.repos.people.upsert(person)
            else:
                place = await self.repos.places.get(al.target_id)
                if place and place.owner_user_id == user.id and alias not in place.aliases:
                    place.aliases = [*place.aliases, alias]
                    await self.repos.places.upsert(place)

    async def _save_fact(self, user: User, fact: Any, msg: InboundMessage) -> None:
        data = fact.model_dump()
        data["user_id"] = user.id
        data["source_message_id"] = msg.id
        if data.get("person_id"):
            p = await self.repos.people.get(data["person_id"])
            if p is None or p.owner_user_id != user.id:
                data["person_id"] = None
        if data.get("business_id") and await self.repos.businesses.get(data["business_id"]) is None:
            data["business_id"] = None
        await self.repos.facts.upsert(type(fact).model_validate(data))

    # ------------------------------------------------------------------ tasks
    async def create_task(
        self,
        user: User,
        spec: TaskSpec,
        msg: InboundMessage | None,
        *,
        interp: Interpretation | None = None,
    ) -> tuple[Task, datetime | None]:
        profile = await self.repos.profiles.get_or_default(user.id)
        if not spec.on_behalf_of and profile.name:
            spec.on_behalf_of = profile.name
        res = interp.resolution if interp else None
        person_id = res.person_id if res else None
        place_id = res.place_id if res else None
        if person_id:
            p = await self.repos.people.get(person_id)
            if p is None or p.owner_user_id != user.id:
                person_id = None
        if place_id:
            pl = await self.repos.places.get(place_id)
            if pl is None or pl.owner_user_id != user.id:
                place_id = None
        now = self.clock.now()
        task = Task(
            requester_user_id=user.id,
            beneficiary=Beneficiary(person_id=person_id),
            place_id=place_id,
            type=spec.type,
            spec=spec,
            recurrence=spec.recurrence,
            delegation=spec.delegation,
            max_attempts=self.settings.call_max_attempts,
            source_message_id=msg.id if msg else None,
            created_at=now,
            updated_at=now,
        )
        queued_until = await self.limiter.limited_until(user)
        if queued_until is not None:
            task.status = TaskStatus.SCHEDULED
            task.next_attempt_at = queued_until
        await self.repos.tasks.add(task)
        await self.audit(
            "task.created", user, actor="user", subject_id=task.id, type=task.type.value
        )
        await self.bus.publish(
            TaskStatusChanged(task_id=task.id, user_id=user.id, old=None, new=task.status)
        )
        if queued_until is None:
            await self._engine_call(("submit",), task)
        await self.costs.check(user.id)
        return task, queued_until

    async def _update_task(self, user: User, task_id: str, spec: TaskSpec) -> None:
        task = await self.repos.tasks.get(task_id)
        if task is None or task.requester_user_id != user.id or task.status.is_terminal:
            return
        if await self._engine_call(("update_spec",), task.id, spec):
            return
        task.spec = spec
        await self.repos.tasks.save(task)

    async def _approve(self, user: User, interp: Interpretation, *, approve: bool) -> None:
        task_id = interp.task_id
        if task_id is None:
            q = await self.repos.tasks.open_question_for_user(user.id)
            if q is not None:
                await self._record_answer(
                    user,
                    UserAnswer(
                        question_id=q.id,
                        text="yes" if approve else "no",
                        approves=approve and q.purpose == QuestionPurpose.APPROVE_BOOKING,
                        answered_at=self.clock.now(),
                    ),
                )
            return
        task = await self.repos.tasks.get(task_id)
        if task is None or task.requester_user_id != user.id:
            return
        await self.audit("task.approval", user, subject_id=task.id, approved=approve)
        if not await self._engine_call(("approve",), task.id, approve) and not approve:
            await self._cancel_task(user, task)

    async def _cancel_task(self, user: User, task: Task) -> None:
        if task.status.is_terminal:
            return
        await self.audit("task.cancel_requested", user, actor="user", subject_id=task.id)
        if await self._engine_call(("cancel",), task.id):
            return
        old = task.status
        await self.repos.tasks.set_status(task.id, TaskStatus.CANCELLED)
        await self.bus.publish(
            TaskStatusChanged(task_id=task.id, user_id=user.id, old=old, new=TaskStatus.CANCELLED)
        )

    # ------------------------------------------------------------------ invites
    async def _invites(self, user: User) -> str:
        is_admin = user.phone in set(self.settings.admin_phones)
        to_make = 1 if is_admin else user.invites_remaining
        for _ in range(to_make):
            await self.repos.invites.add(
                Invite(
                    code=await self._fresh_code(),
                    created_by_user_id=user.id,
                    created_at=self.clock.now(),
                )
            )
        if not is_admin and to_make:
            user.invites_remaining = 0
            await self.repos.users.save(user)
        invites = await self.repos.invites.list_by_creator(user.id)
        if not invites:
            return "You don't have invite codes right now."
        lines = [f"{i.code} - {'used' if i.redeemed_by_user_id else 'available'}" for i in invites]
        return "Your invite codes (each works once):\n" + "\n".join(lines)

    async def _fresh_code(self) -> str:
        while True:
            code = "FRI-" + "".join(secrets.choice(INVITE_ALPHABET) for _ in range(6))
            if await self.repos.invites.get(code) is None:
                return code

    # ------------------------------------------------------------------ delete everything
    async def delete_everything(self, user: User) -> None:
        """PIN-verified + DELETE-confirmed purge. Ends in-flight tasks first."""
        for task in await self.repos.tasks.list_for_user(user.id, open_only=True):
            await self._engine_call(("cancel",), task.id)
        phone = user.phone
        recordings = await self.repos.purger.recording_urls(user.id)
        counts = await self.repos.purger.purge_user(user.id)
        # SECURITY-14: recordings live outside the DB (object store / provider).
        from friday.db.objectstore import build_object_store
        from friday.db.retention import erase_recordings

        try:
            store = build_object_store(self.settings)
        except Exception:  # noqa: BLE001 - misconfigured store: queue for retention
            store = None
        if store is not None:
            await erase_recordings(
                self.repos, recordings, store=store, telephony=self._opt("telephony")
            )
        else:
            from friday.db.retention import add_pending_deletion

            for url in recordings:
                await add_pending_deletion(self.repos, url, error="no object store")
        await self.state.clear_user(user.id)
        await self.repos.audit.log(
            "data.deleted", user_id=user.id, actor="user", tables=len(counts)
        )
        # Sent directly (not logged): the message log for this user must stay empty.
        messaging = self._opt("messaging")
        if messaging is not None:
            try:
                await messaging.send(
                    OutboundMessage(channel=messaging.channel, to_phone=phone, text=DELETE_DONE)
                )
            except Exception as e:  # noqa: BLE001
                log.info("delete confirmation not delivered: %s", type(e).__name__)


def _new_id() -> str:
    from friday.core.models import new_id

    return new_id()
