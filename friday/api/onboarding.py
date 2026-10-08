"""Conversational onboarding state machine (US-1).

The brain (``onboarding_turn``) writes the copy and extracts values; the backend
validates and persists, and owns the steps that must be deterministic:

* INVITE_CODE - fixed copy; ``FRI-XXXXXX`` codes redeemed atomically; no code
  twice -> waitlist (one ack, then silence). Admin phones / invite_only=False skip it.
* CONSENT     - recorded only when the brain says ``consent_given`` AND the
  user's own words/button are an explicit agreement; evidence text stored.
* PIN         - never sent to the brain, never echoed or logged: extracted by
  regex, weak PINs rejected, confirmed by re-entry, argon2id-hashed.
* Consent and PIN can never be skipped (``next_step`` is clamped).
* Only language/name/city/tone are stored before consent.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from friday.api.security import extract_pin, pin_problem
from friday.core.models import (
    Consent,
    ConsentKind,
    InboundMessage,
    MessageKind,
    OnboardingStep,
    OnboardingTurn,
    ReplyButton,
    User,
    UserStatus,
)

if TYPE_CHECKING:
    from friday.api.inbound import InboundPipeline

ORDER = list(OnboardingStep)
INVITE_RE = re.compile(r"\bFRI[\s\-_]*([A-Z0-9]{6})\b", re.I)
AGREE_RE = re.compile(r"\b(i\s*agree|agree|agreed|haan,?\s*agree)\b|सहमत", re.I)
CONSENT_BUTTON = "consent:agree"
PRE_CONSENT_FIELDS = {"name", "city", "language", "tone"}

INVITE_ASK = "Friday is invite-only right now. Have an invite code? (It looks like FRI-XXXXXX.)"
INVITE_BAD = "That code doesn't work. Check with whoever gave it to you?"
WAITLIST_ACK = (
    "No problem, you're on the waitlist. I'll message you here as soon as a spot opens up."
)
PIN_ASK = "Please send a 4-digit Friday PIN. I'll ask for it before sensitive things."
PIN_WEAK = "That PIN is too easy to guess. Please pick a different 4-digit PIN."
PIN_CONFIRM = "Got it. Please type the same PIN once more to confirm."
PIN_MISMATCH = "Those didn't match. Let's start again: send a 4-digit PIN."
PIN_SAVED = "PIN saved. Please delete your PIN messages from this chat."


def normalize_invite(text: str | None) -> str | None:
    if not text:
        return None
    m = INVITE_RE.search(text)
    return f"FRI-{m.group(1).upper()}" if m else None


def step_index(step: OnboardingStep) -> int:
    return ORDER.index(step)


class OnboardingFlow:
    def __init__(self, pipeline: InboundPipeline) -> None:
        self.p = pipeline

    def awaiting_pin(self, user: User) -> bool:
        return user.status == UserStatus.ONBOARDING and user.onboarding_step == OnboardingStep.PIN

    def first_step(self, user: User) -> OnboardingStep:
        s = self.p.settings
        admin = user.phone in {p for p in s.admin_phones}
        return OnboardingStep.INVITE_CODE if (s.invite_only and not admin) else OnboardingStep.NAME

    # ------------------------------------------------------------------ entry points
    async def start(self, user: User, msg: InboundMessage) -> None:
        """First message from a brand-new number."""
        if user.onboarding_step == OnboardingStep.INVITE_CODE:
            code = normalize_invite(msg.text)
            if code is None:
                await self.p.reply(user, INVITE_ASK)
                return
            await self._redeem(user, code, msg)
            return
        await self._open_step(user, user.onboarding_step)

    async def waitlisted(self, user: User, msg: InboundMessage) -> None:
        code = normalize_invite(msg.text)
        if code is None:
            return  # replied once already; silence until a code arrives
        await self._redeem(user, code, msg)

    async def handle(self, user: User, msg: InboundMessage) -> None:
        step = user.onboarding_step
        if step == OnboardingStep.INVITE_CODE:
            code = normalize_invite(msg.text)
            if code is None:
                user.status = UserStatus.WAITLISTED
                await self.p.repos.users.save(user)
                await self.p.audit("user.waitlisted", user)
                await self.p.reply(user, WAITLIST_ACK)
                return
            await self._redeem(user, code, msg)
            return
        if step == OnboardingStep.PIN:
            await self._pin(user, msg)
            return
        if step == OnboardingStep.DONE:
            await self._finish(user)
            return
        brain = self.p.brain()
        if brain is None:
            await self.p.reply(user, self.p.NO_BRAIN)
            return
        ctx = await self.p.context(user)
        turn = await brain.onboarding_turn(ctx, step, msg)
        await self._apply(user, step, turn, msg)

    # ------------------------------------------------------------------ steps
    async def _redeem(self, user: User, code: str, msg: InboundMessage) -> None:
        invite = await self.p.repos.invites.redeem(code, user.id)
        if invite is None:
            await self.p.reply(user, INVITE_BAD)
            return
        user.invited_by_user_id = invite.created_by_user_id
        user.status = UserStatus.ONBOARDING
        user.onboarding_step = OnboardingStep.NAME
        await self.p.repos.users.save(user)
        await self.p.audit("invite.redeemed", user, subject_id=None)
        await self._open_step(user, OnboardingStep.NAME)

    async def _open_step(self, user: User, step: OnboardingStep, prefix: str | None = None) -> None:
        if step == OnboardingStep.PIN:
            await self.p.reply(user, "\n\n".join(x for x in (prefix, PIN_ASK) if x))
            return
        brain = self.p.brain()
        if brain is None:
            await self.p.reply(user, self.p.NO_BRAIN)
            return
        ctx = await self.p.context(user)
        turn = await brain.onboarding_turn(ctx, step, None)
        reply = "\n\n".join(x for x in (prefix, turn.reply) if x)
        await self.p.reply(user, reply, turn.buttons)

    async def _apply(
        self, user: User, step: OnboardingStep, turn: OnboardingTurn, msg: InboundMessage
    ) -> None:
        consented = await self.p.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY)
        updates = dict(turn.profile_updates)
        if not consented:
            updates = {k: v for k, v in updates.items() if k in PRE_CONSENT_FIELDS}
        if updates:
            await self.p.apply_profile_updates(user, updates)

        if step == OnboardingStep.CONSENT and turn.consent_given and self._explicit_agree(msg):
            await self.p.repos.consents.add(
                Consent(
                    user_id=user.id,
                    kind=ConsentKind.TERMS_PRIVACY,
                    granted=True,
                    evidence_text=(msg.text or msg.button_id or "")[:500],
                    message_id=msg.id,
                    recorded_at=self.p.clock.now(),
                )
            )
            await self.p.audit("consent.granted", user, kind=ConsentKind.TERMS_PRIVACY.value)
            consented = True
        if consented and step in (
            OnboardingStep.CIRCLE,
            OnboardingStep.PLACES,
            OnboardingStep.FIRST_TASK,
        ):
            for person in turn.people:
                await self.p.upsert_person(user, person)
            for place in turn.places:
                await self.p.save_place(user, place, msg)
            if (
                step == OnboardingStep.PLACES
                and not turn.places
                and msg.kind == MessageKind.LOCATION
            ):
                from friday.core.models import Place

                await self.p.save_place(user, Place(owner_user_id=user.id, label="Home"), msg)

        next_step = self._clamp(user, turn.next_step, consented)
        reply = turn.reply
        buttons: list[ReplyButton] = list(turn.buttons)
        if turn.first_task is not None and consented and user.pin_hash:
            await self.p.create_task(user, turn.first_task, msg)
            next_step = OnboardingStep.DONE
        user.onboarding_step = next_step
        await self.p.repos.users.save(user)
        if next_step == OnboardingStep.DONE:
            await self._finish(user, reply=reply, buttons=buttons)
            return
        if next_step == OnboardingStep.PIN and step != OnboardingStep.PIN:
            await self.p.reply(user, "\n\n".join(x for x in (reply, PIN_ASK) if x))
            return
        await self.p.reply(user, reply, buttons)

    def _clamp(self, user: User, proposed: OnboardingStep, consented: bool) -> OnboardingStep:
        if step_index(proposed) > step_index(OnboardingStep.CONSENT) and not consented:
            return OnboardingStep.CONSENT
        if step_index(proposed) > step_index(OnboardingStep.PIN) and not user.pin_hash:
            return OnboardingStep.PIN
        if proposed == OnboardingStep.INVITE_CODE:
            return user.onboarding_step
        return proposed

    @staticmethod
    def _explicit_agree(msg: InboundMessage) -> bool:
        if msg.button_id == CONSENT_BUTTON:
            return True
        return bool(msg.text and AGREE_RE.search(msg.text))

    async def _pin(self, user: User, msg: InboundMessage) -> None:
        pin = extract_pin(msg.text)
        if pin is None:
            await self.p.reply(user, PIN_ASK)
            return
        first = await self.p.state.get_first_pin_hash(user.id)
        if first is None:
            if pin_problem(pin):
                await self.p.reply(user, PIN_WEAK)
                return
            await self.p.state.set_first_pin_hash(user.id, self.p.pins.hasher.hash(pin))
            await self.p.reply(user, PIN_CONFIRM)
            return
        await self.p.state.clear_first_pin_hash(user.id)
        if not self.p.pins.hasher.verify(first, pin):
            await self.p.reply(user, PIN_MISMATCH)
            return
        await self.p.pins.set_pin(user, pin)
        await self.p.audit("pin.set", user)
        user.onboarding_step = OnboardingStep.CIRCLE
        await self.p.repos.users.save(user)
        await self._open_step(user, OnboardingStep.CIRCLE, prefix=PIN_SAVED)

    async def _finish(
        self, user: User, *, reply: str | None = None, buttons: list[ReplyButton] | None = None
    ) -> None:
        user.status = UserStatus.ACTIVE
        user.onboarding_step = OnboardingStep.DONE
        user.invites_remaining = self.p.settings.invites_per_user
        await self.p.repos.users.save(user)
        await self.p.audit("onboarding_completed", user)
        if reply:
            await self.p.reply(user, reply, buttons or [])
