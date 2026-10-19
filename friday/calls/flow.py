"""Intake: a user message -> (one question | a refusal | an approval message).

The WhatsApp layer keeps the returned ``IntakeState`` for the user and passes it back with the
next message. Nothing is dialled here: the last thing this module produces is the approval
message; the buttons are handled by ``CallOrchestrator.handle_button``.

Order of business: refuse unsafe requests first, then ask for what is missing (one question at a
time), then identify the callee (saved contact, ambiguity question, number confirmed back), then
build the brief, then ask for approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from friday.calls import copy
from friday.calls.approval import ApprovalService
from friday.calls.classify import classify
from friday.calls.contacts import Contact, ContactBook
from friday.calls.models import CalleeKind, CallStatus
from friday.calls.numbers import canonical, is_emergency
from friday.calls.orchestrator import CallOrchestrator, Member
from friday.calls.understand import Draft, RequestUnderstander, Understanding
from friday.core.models import ReplyButton, User

_YES = re.compile(
    r"^\s*(haan|han|ha|haa|yes|y|yep|sahi|bilkul|correct|ok|okay|theek|thik|right|👍)\b", re.I
)
_NO = re.compile(r"^\s*(nahi|nahin|no|n|galat|wrong|nope|na)\b", re.I)


class IntakeState(BaseModel):
    """What the next message answers. Serialisable; the caller stores it per user."""

    understanding: Understanding | None = None
    step: str = "understand"  # understand | ask | which | need_number | confirm_number | member
    candidate_ids: list[str] = Field(default_factory=list)
    pending_name: str | None = None
    pending_number: str | None = Field(default=None, repr=False)
    pending_contact_id: str | None = None
    members: list[dict[str, str]] = Field(default_factory=list)  # resolved: name, id|number
    member_queue: list[str] = Field(default_factory=list)  # names still to resolve


@dataclass
class IntakeReply:
    text: str
    buttons: list[ReplyButton] = field(default_factory=list)
    state: IntakeState | None = None
    request_id: str | None = None
    refused: bool = False


class MissedCalls(Protocol):
    async def last_missed(self, user_id: str) -> tuple[str, str] | None:
        """(name, number) of the most recent missed call to this user, if any."""
        ...


class CallIntake:
    def __init__(
        self,
        *,
        understander: RequestUnderstander,
        contacts: ContactBook,
        orchestrator: CallOrchestrator,
        approval: ApprovalService,
        missed: MissedCalls | None = None,
    ) -> None:
        self.understander, self.contacts = understander, contacts
        self.orch, self.approval, self.missed = orchestrator, approval, missed

    # ------------------------------------------------------------------ entry
    async def handle(
        self,
        user: User,
        text: str,
        *,
        message_id: str | None,
        state: IntakeState | None = None,
        user_display_name: str | None = None,
        language: str | None = None,
    ) -> IntakeReply:
        lang = language or copy.DEFAULT_LANGUAGE
        st = state or IntakeState()
        now = self.orch.clock.now()
        if st.step in ("understand", "ask"):
            u = await self.understander.understand(
                text,
                prior=st.understanding if st.step == "ask" else None,
                now=now,
                profile_language=language,
            )
            refusal = await self._refusal(user, u, lang)
            if refusal:
                return refusal
            if not u.ready:
                st = IntakeState(understanding=u, step="ask")
                return IntakeReply(copy.line(u.question_key or "ask_purpose", lang), state=st)
            st = IntakeState(understanding=u, step="understand")
            return await self._resolve(user, st, message_id, lang, user_display_name)
        if st.step == "which":
            return await self._answer_which(user, st, text, message_id, lang, user_display_name)
        if st.step == "need_number":
            return await self._answer_number(user, st, text, message_id, lang, user_display_name)
        if st.step == "confirm_number":
            return await self._answer_confirm(user, st, text, message_id, lang, user_display_name)
        return IntakeReply(copy.line("ask_callee", lang), state=IntakeState())

    # ------------------------------------------------------------------ refusal
    async def _refusal(self, user: User, u: Understanding, lang: str) -> IntakeReply | None:
        verdict = classify(u.draft.raw_text, u.draft.purpose, u.draft.details)
        if u.refusal_key is None:
            return None
        if verdict.strike:
            await self.orch.store.add_strike(
                user.id, verdict.category or "abuse", self.orch.clock.now()
            )
        return IntakeReply(copy.line(u.refusal_key, lang), refused=True)

    # ------------------------------------------------------------------ callee resolution
    async def _resolve(
        self, user: User, st: IntakeState, message_id: str | None, lang: str, name: str | None
    ) -> IntakeReply:
        assert st.understanding is not None
        d = st.understanding.draft
        if d.callee_kind == CalleeKind.GROUP:
            return await self._resolve_group(user, st, message_id, lang, name)
        if d.callback_of and not d.callee_ref and self.missed is not None:
            last = await self.missed.last_missed(user.id)
            if last:
                st.pending_name, st.pending_number = last
                return self._confirm_prompt(st, lang)
        if d.number:
            ref = d.callee_ref or ""
            named = None if (not ref or ref[0] in "+0123456789") else ref
            st.pending_name = d.company or named or "yeh number"
            st.pending_number = d.number
            known = await self.contacts.resolve(user.id, d.number)
            if known.status == "found" and known.contact and known.contact.confirmed:
                return await self._finish(user, st, known.contact, message_id, lang, name)
            return self._confirm_prompt(st, lang)
        ref = d.callee_ref or ""
        res = await self.contacts.resolve(user.id, ref)
        if res.status == "found" and res.contact:
            if res.contact.confirmed:
                return await self._finish(user, st, res.contact, message_id, lang, name)
            st.pending_contact_id, st.pending_name = res.contact.id, res.contact.name
            st.pending_number = res.contact.number
            return self._confirm_prompt(st, lang)
        if res.status == "ambiguous":
            st.step, st.candidate_ids = "which", [c.id for c in res.candidates]
            return IntakeReply(ContactBook.ask_which(ref, res.candidates, lang), state=st)
        st.step, st.pending_name = "need_number", d.company or ref
        return IntakeReply(copy.line("ask_number", lang, name=st.pending_name), state=st)

    def _confirm_prompt(self, st: IntakeState, lang: str) -> IntakeReply:
        st.step = "confirm_number"
        text = ContactBook.confirm_number_back(
            st.pending_name or "-", st.pending_number or "", lang
        )
        return IntakeReply(text, state=st)

    async def _answer_which(self, user, st, text, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        cands: list[Contact] = []
        for cid in st.candidate_ids:
            c = await self.contacts.store.get(user.id, cid)
            if c:
                cands.append(c)
        t = text.strip().lower()
        picked = [c for c in cands if c.name.lower() in t or t.endswith(c.last4())]
        if not picked and t.isdigit() and 1 <= int(t) <= len(cands):
            picked = [cands[int(t) - 1]]
        if len(picked) != 1:
            ref = (st.understanding.draft.callee_ref if st.understanding else "") or ""
            return IntakeReply(ContactBook.ask_which(ref, cands, lang), state=st)
        c = picked[0]
        if c.confirmed:
            return await self._finish(user, st, c, message_id, lang, name)
        st.pending_contact_id, st.pending_name, st.pending_number = c.id, c.name, c.number
        return self._confirm_prompt(st, lang)

    async def _answer_number(self, user, st, text, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        if is_emergency(text):
            return IntakeReply(copy.line("refuse_emergency_number", lang), refused=True)
        e164 = canonical(text)
        if e164 is None:
            return IntakeReply(copy.line("deny_invalid_number", lang), state=st)
        st.pending_number = e164
        return self._confirm_prompt(st, lang)

    async def _answer_confirm(self, user, st, text, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        if _NO.match(text):
            st.step, st.pending_number, st.pending_contact_id = "need_number", None, None
            return IntakeReply(copy.line("ask_number", lang, name=st.pending_name or "-"), state=st)
        if not _YES.match(text):
            return self._confirm_prompt(st, lang)
        d = st.understanding.draft if st.understanding else Draft()
        if st.pending_contact_id:
            contact = await self.contacts.confirm(user.id, st.pending_contact_id)
        else:
            contact = await self.contacts.add(
                user.id, st.pending_name or d.callee_ref or "Contact", st.pending_number or "",
                confirmed=True,
            )  # fmt: skip
        if contact is None:
            return IntakeReply(copy.line("ask_callee", lang), state=IntakeState())
        if st.understanding and st.understanding.draft.callee_kind == CalleeKind.GROUP:
            return await self._member_done(user, st, contact, message_id, lang, name)
        return await self._finish(user, st, contact, message_id, lang, name)

    # ------------------------------------------------------------------ group
    async def _resolve_group(self, user, st, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        assert st.understanding is not None
        names = st.understanding.draft.group_members
        st.member_queue = list(names)
        st.members = []
        return await self._next_member(user, st, message_id, lang, name)

    async def _next_member(self, user, st, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        while st.member_queue:
            ref = st.member_queue[0]
            res = await self.contacts.resolve(user.id, ref)
            if res.status == "found" and res.contact and res.contact.confirmed:
                st.members.append({"name": res.contact.name, "id": res.contact.id})
                st.member_queue.pop(0)
                continue
            if res.status == "found" and res.contact:
                st.pending_contact_id, st.pending_name = res.contact.id, res.contact.name
                st.pending_number = res.contact.number
                st.member_queue.pop(0)
                return self._confirm_prompt(st, lang)
            if res.status == "number" and res.number:
                st.pending_name, st.pending_number = ref, res.number
                st.pending_contact_id = None
                st.member_queue.pop(0)
                return self._confirm_prompt(st, lang)
            st.pending_name = ref
            st.member_queue.pop(0)
            st.step = "need_number"
            st.pending_contact_id = None
            return IntakeReply(copy.line("ask_number", lang, name=ref), state=st)
        return await self._finish_group(user, st, message_id, lang, name)

    async def _member_done(self, user, st, contact, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        st.members.append({"name": contact.name, "id": contact.id})
        st.pending_contact_id = st.pending_number = None
        return await self._next_member(user, st, message_id, lang, name)

    async def _finish_group(self, user, st, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        assert st.understanding is not None
        members: list[Member] = []
        for m in st.members:
            c = await self.contacts.store.get(user.id, m["id"])
            if c:
                members.append(Member(c.name, c.number, c.confirmed, _kind_for(c)))
        if not members:
            return IntakeReply(copy.line("ask_group_members", lang), state=IntakeState())
        parent, brief, _kids = await self.orch.create_group(
            st.understanding.draft, user=user, message_id=message_id, members=members,
            user_display_name=name,
        )  # fmt: skip
        parent.callee_name = ", ".join(m.name for m in members)
        return await self._ask_approval(parent, brief, lang)

    # ------------------------------------------------------------------ single call
    async def _finish(self, user, st, contact: Contact, message_id, lang, name) -> IntakeReply:  # noqa: ANN001
        assert st.understanding is not None
        d = st.understanding.draft
        kind = _kind_for(contact, d.callee_kind)
        req, brief, _created = await self.orch.create_from_draft(
            d, user=user, message_id=message_id, callee_name=contact.name,
            callee_number=contact.number, number_confirmed=contact.confirmed, kind=kind,
            relationship=contact.relationship, user_display_name=name,
        )  # fmt: skip
        return await self._ask_approval(req, brief, lang)

    async def _ask_approval(self, req, brief, lang: str) -> IntakeReply:  # noqa: ANN001
        store = self.orch.store
        if req.status.is_terminal or req.status in (
            CallStatus.SCHEDULED, CallStatus.CALLING, CallStatus.GROUP_WAITING,
        ):  # fmt: skip
            return IntakeReply("", request_id=req.id)  # a re-delivered message: say nothing twice
        fresh, prompt = await self.approval.prepare(req, brief)
        await store.save_brief(fresh)
        req.status = CallStatus.AWAITING_APPROVAL
        await store.save_request(req)
        return IntakeReply(prompt.text, prompt.buttons, state=None, request_id=req.id)


def _kind_for(contact: Contact, guess: CalleeKind | None = None) -> CalleeKind:
    """A saved relationship (mother, friend...) makes it a family/friend call; otherwise keep the
    understander's kind; otherwise the most careful kind, UNKNOWN."""
    if contact.relationship:
        rel = contact.relationship.lower()
        if rel in ("mother", "father", "brother", "sister", "wife", "husband", "friend", "family"):
            return CalleeKind.FAMILY_FRIEND
    return guess if guess not in (None, CalleeKind.GROUP) else CalleeKind.UNKNOWN
