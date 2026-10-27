# ruff: noqa: E501
"""The refund service: open and track cases, remind the user, propose vendor follow-ups.

What this service never does: touch money, invent a number, contact a vendor without the user's
yes, close a real case by itself, or say money arrived on its own word. Every outbound message goes
through ``RefundSender``; a vendor follow-up goes through ``RefundTaskPort`` only after the user
approved the proposal, and the existing task engine then asks again before it dials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from friday.core.clock import Clock, is_quiet_hours, ist_date
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import CallMode, Language, TaskSpec, TaskType
from friday.docunderstand.safety import clean_text
from friday.evidence.models import EvidenceItem
from friday.refunds import copy
from friday.refunds import evidence as ev
from friday.refunds.config import RefundConfig
from friday.refunds.copy import age_text, fmt_date, money, t
from friday.refunds.machine import (
    GuardFailed,
    IllegalTransition,
    amount_check,
    can_move,
    transition,
)
from friday.refunds.models import (
    OPEN_STATES,
    Basis,
    CloseReason,
    Origin,
    Proposal,
    RefundCase,
    RefundEvent,
    RefundNudge,
    RefundState,
    Source,
)
from friday.refunds.ports import (
    Button,
    NumberSource,
    RefundMessage,
    RefundSender,
    RefundTaskPort,
    button_id,
    name_match,
)
from friday.refunds.reminders import Reminder, next_reminder
from friday.refunds.resolver import Contact, Resolved, resolve

log = get_logger(__name__)
S = RefundState


class RefundsDisabled(RuntimeError):
    """The refund switch is off (or this user is not on the allow-list)."""


@dataclass
class RefundReply:
    text: str
    buttons: list[Button] = field(default_factory=list)
    case_id: str | None = None


@dataclass
class Outcome:
    key: str
    stage: str
    action: str  # sent | held_quiet | held_cap | expired | muted | lapsed | failed
    case_id: str = ""
    text: str | None = None


@dataclass(frozen=True)
class MoneyRecovered:
    """Feeds the Wrapped card. Counts ONLY cases closed as received with proof or the user's word."""

    total_paise: int
    cases: int
    proof_backed: int


def _vendor_key(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _days(a: datetime, b: datetime) -> int:
    return max(0, (ist_date(b) - ist_date(a)).days)


class RefundService:
    def __init__(
        self,
        settings: Settings,
        store: Any,
        clock: Clock,
        *,
        sender: RefundSender | None = None,
        tasks: RefundTaskPort | None = None,
        sources: list[NumberSource] | None = None,
        config: RefundConfig | None = None,
        language: str = "hinglish",
    ) -> None:
        self.settings, self.store, self.clock = settings, store, clock
        self.sender, self.tasks = sender, tasks
        self.sources: list[NumberSource] = list(sources or [])
        self.cfg = config or RefundConfig.from_settings(settings)
        self.lang = language

    # ------------------------------------------------------------------ switch
    def enabled_for(self, user_id: str) -> bool:
        if not self.settings.refunds_enabled:
            return False
        allowed = {x.strip() for x in self.settings.refunds_enabled_users if x.strip()}
        return not allowed or user_id in allowed

    def _need(self, user_id: str) -> None:
        if not self.enabled_for(user_id):
            raise RefundsDisabled("refunds are off")

    # ------------------------------------------------------------------ helpers
    def _msg(self, case: RefundCase | None, body: str) -> str:
        return f"[Refund: {case.vendor_name}] {body}" if case and case.vendor_name else body

    def _reply(
        self, case: RefundCase | None, key: str, buttons: list[Button] | None = None, **kw: Any
    ) -> RefundReply:
        return RefundReply(
            self._msg(case, t(key, self.lang, **kw)), buttons or [], case.id if case else None
        )

    def _btn(self, case: RefundCase, action: str, label_key: str) -> Button:
        return Button(button_id(case.id, action), t(label_key, self.lang))

    def _state_text(self, state: RefundState) -> str:
        return t(f"state.{state.value}", self.lang)

    async def _move(
        self, case: RefundCase, to: RefundState, source: Source, note: str | None = None, **kw: Any
    ) -> RefundCase:
        now = self.clock.now()
        moved = transition(case, to, source=source, **kw)
        moved.state_changed_at = moved.updated_at = now
        await self.store.save_case(moved)
        await self.store.add_event(
            RefundEvent(
                user_id=case.user_id,
                case_id=case.id,
                from_state=case.state,
                to_state=to,
                source=source,
                note=note,
                at=now,
            )
        )
        return moved

    def _expected(self, case: RefundCase) -> int | None:
        return (
            case.amount_expected_paise
            if case.amount_expected_paise is not None
            else case.promised_amount_paise
        )

    # ------------------------------------------------------------------ proposals (Friday noticed)
    async def propose(
        self,
        user_id: str,
        origin: Origin,
        origin_ref: str,
        vendor_name: str,
        *,
        amount_paise: int | None = None,
        task_id: str | None = None,
        paid_with_bank: str | None = None,
    ) -> RefundCase | None:
        """Friday noticed a cancelled booking / order or a disputed bill: a SUSPECTED case, asked
        about at the next reminder tick. The user's yes opens it. Idempotent per origin."""
        if not self.enabled_for(user_id):
            return None
        existing = await self.store.find_by_origin(user_id, origin, origin_ref)
        if existing is not None:
            return existing
        now = self.clock.now()
        case = RefundCase(
            user_id=user_id,
            state=S.SUSPECTED,
            origin=origin,
            origin_ref=origin_ref,
            vendor_name=clean_text(vendor_name, 60),
            amount_expected_paise=amount_paise,
            task_id=task_id,
            paid_with_bank=clean_text(paid_with_bank, 40) if paid_with_bank else None,
            state_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_case(case)
        await self.store.add_event(
            RefundEvent(
                user_id=user_id,
                case_id=case.id,
                from_state=None,
                to_state=S.SUSPECTED,
                source=Source.SYSTEM,
                at=now,
            )
        )
        return case

    async def propose_from_trip_cancellation(
        self, user_id: str, leg_id: str, vendor_name: str, *, amount_paise: int | None = None
    ) -> RefundCase | None:
        return await self.propose(
            user_id, Origin.TRIP_LEG, leg_id, vendor_name, amount_paise=amount_paise
        )

    async def propose_from_order(
        self, user_id: str, task_id: str, vendor_name: str, *, amount_paise: int | None = None
    ) -> RefundCase | None:
        return await self.propose(
            user_id, Origin.ORDER, task_id, vendor_name, amount_paise=amount_paise, task_id=task_id
        )

    async def propose_from_bill_dispute(
        self, user_id: str, bill_ref: str, vendor_name: str, *, amount_paise: int | None = None
    ) -> RefundCase | None:
        return await self.propose(
            user_id, Origin.BILL_DISPUTE, bill_ref, vendor_name, amount_paise=amount_paise
        )

    async def confirm(self, user_id: str, case_id: str) -> RefundReply:
        """The user said yes to a proposal."""
        self._need(user_id)
        case = await self.store.get_case(user_id, case_id)
        if case is None or case.state != S.SUSPECTED:
            return RefundReply(t("case.unknown", self.lang))
        case = await self._move(case, S.OPENED, Source.USER, "confirmed")
        return self._reply(case, "suspect.yes", vendor=case.vendor_name)

    async def decline(self, user_id: str, case_id: str) -> RefundReply:
        self._need(user_id)
        case = await self.store.get_case(user_id, case_id)
        if case is None or case.state != S.SUSPECTED:
            return RefundReply(t("case.unknown", self.lang))
        case = await self._move(
            case, S.CLOSED, Source.USER, "declined", reason=CloseReason.DECLINED
        )
        return self._reply(case, "suspect.no", vendor=case.vendor_name)

    # ------------------------------------------------------------------ opened by the user
    async def open_by_user(
        self,
        user_id: str,
        vendor_name: str,
        *,
        amount_paise: int | None = None,
        paid_with_bank: str | None = None,
    ) -> RefundReply:
        self._need(user_id)
        vendor = clean_text(vendor_name, 60)
        if not _vendor_key(vendor):
            return RefundReply(t("open.need_vendor", self.lang))
        for c in await self.store.list_cases(user_id, OPEN_STATES):
            if _vendor_key(c.vendor_name) == _vendor_key(vendor):
                if c.state == S.SUSPECTED:  # the user's own words are the yes
                    c = await self._move(c, S.OPENED, Source.USER, "user asked")
                return self._reply(
                    c, "open.exists", vendor=c.vendor_name, state=self._state_text(c.state)
                )
        now = self.clock.now()
        case = RefundCase(
            user_id=user_id,
            state=S.OPENED,
            origin=Origin.USER,
            vendor_name=vendor,
            amount_expected_paise=amount_paise,
            paid_with_bank=clean_text(paid_with_bank, 40) if paid_with_bank else None,
            state_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_case(case)
        await self.store.add_event(
            RefundEvent(
                user_id=user_id,
                case_id=case.id,
                from_state=None,
                to_state=S.OPENED,
                source=Source.USER,
                at=now,
            )
        )
        part = t("amount.part", self.lang, amount=money(amount_paise)) if amount_paise else ""
        return self._reply(case, "open.ok", vendor=vendor, amount_part=part)

    # ------------------------------------------------------------------ finding a case
    async def find_case(
        self, user_id: str, hint: str | None = None
    ) -> tuple[RefundCase | None, bool]:
        """(case, ambiguous). Without a hint, the only open case; with one, the open case whose
        vendor matches it."""
        open_ = [
            c for c in await self.store.list_cases(user_id, OPEN_STATES) if c.state != S.SUSPECTED
        ] or await self.store.list_cases(user_id, OPEN_STATES)
        if hint and _vendor_key(hint):
            hit = [
                c
                for c in open_
                if name_match(hint, c.vendor_name) or name_match(c.vendor_name, hint)
            ]
            return (hit[0], False) if len(hit) == 1 else (None, len(hit) > 1)
        return (open_[0], False) if len(open_) == 1 else (None, len(open_) > 1)

    # ------------------------------------------------------------------ the user's updates
    async def _guard(self, user_id: str, case_id: str) -> RefundCase | None:
        self._need(user_id)
        return await self.store.get_case(user_id, case_id)

    async def _try(
        self, case: RefundCase, to: RefundState, source: Source, ok_key: str
    ) -> RefundReply:
        try:
            moved = await self._move(case, to, source)
        except (IllegalTransition, GuardFailed):
            return self._reply(case, "illegal", state=self._state_text(case.state))
        return self._reply(moved, ok_key, vendor=moved.vendor_name)

    async def mark_requested(self, user_id: str, case_id: str) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        return await self._try(case, S.REQUESTED, Source.USER, "requested.ok")

    async def mark_acknowledged(self, user_id: str, case_id: str) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        return await self._try(case, S.VENDOR_ACKNOWLEDGED, Source.USER, "ack.ok")

    async def mark_promised(
        self, user_id: str, case_id: str, on: date, amount_paise: int
    ) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        if amount_paise <= 0:
            return RefundReply(t("promised.need", self.lang))
        try:
            moved = await self._move(
                case,
                S.PROMISED,
                Source.USER,
                "vendor promise",
                promised_date=on,
                promised_amount_paise=amount_paise,
            )
        except (IllegalTransition, GuardFailed):
            return self._reply(case, "illegal", state=self._state_text(case.state))
        await self.store.add_evidence(
            ev.from_vendor_promise(moved, now=self.clock.now(), amount_paise=amount_paise)
        )
        return self._reply(
            moved,
            "promised.ok",
            vendor=moved.vendor_name,
            amount=money(amount_paise),
            date=fmt_date(on),
        )

    async def mark_rejected(self, user_id: str, case_id: str) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        reply = await self._try(case, S.REJECTED, Source.USER, "rejected.ok")
        if reply.case_id:
            c = await self.store.get_case(user_id, case_id)
            if c and c.state == S.REJECTED:
                reply.buttons = [
                    self._btn(c, "chase", "btn.chase"),
                    self._btn(c, "close", "btn.close"),
                ]
        return reply

    async def mark_escalated(self, user_id: str, case_id: str) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        return await self._try(case, S.ESCALATED, Source.USER, "escalated.ok")

    async def mark_received(
        self,
        user_id: str,
        case_id: str,
        amount_paise: int,
        *,
        proof_text: str | None = None,
        receipt: bytes | None = None,
    ) -> RefundReply:
        """The user says (and optionally shows) that money arrived. Friday cannot see the bank:
        the basis is the user's word, or proof that states the amount. An exact (or larger, or
        unknown-expected) amount closes the case; a short one stays open and asks what to do."""
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        if amount_paise <= 0:
            return self._reply(case, "received.need_amount")
        now = self.clock.now()
        if not can_move(case.state, S.RECEIVED):
            return self._reply(case, "illegal", state=self._state_text(case.state))
        new_ev = [ev.from_user_confirmation(case, now=now, amount_paise=amount_paise)]
        if proof_text:
            new_ev.append(ev.from_user_text(case, proof_text, now=now, amount_paise=amount_paise))
        if receipt:
            new_ev.append(ev.from_receipt(case, receipt, now=now, amount_paise=amount_paise))
        have = await self.store.list_evidence(user_id, case_id)
        total = (case.amount_received_paise or 0) + amount_paise
        basis = ev.basis_for_received(have + new_ev, total, self.cfg.amount_tolerance_paise)
        try:
            moved = await self._move(
                case, S.RECEIVED, Source.USER, "received", basis=basis, received_paise=amount_paise
            )
        except (IllegalTransition, GuardFailed):
            return self._reply(case, "illegal", state=self._state_text(case.state))
        for e in new_ev:
            await self.store.add_evidence(e)
        check = amount_check(
            self._expected(moved), moved.amount_received_paise or 0, self.cfg.amount_tolerance_paise
        )
        if check.status == "short":
            return self._reply(
                moved,
                "received.short",
                [self._btn(moved, "chase", "btn.chase"), self._btn(moved, "close", "btn.close")],
                vendor=moved.vendor_name,
                amount=money(check.received),
                expected=money(check.expected),
                diff=money(-check.diff),
            )
        closed = await self._move(
            moved,
            S.CLOSED,
            Source.USER,
            "received in full",
            reason=CloseReason.RECEIVED,
            basis=basis,
        )
        kw: dict[str, Any] = {
            "vendor": closed.vendor_name,
            "amount": money(check.received),
            "expected": money(check.expected),
        }
        if check.status == "exact":
            return self._reply(
                closed, "received.exact_proof" if basis == Basis.PROOF else "received.exact", **kw
            )
        if check.status == "over":
            return self._reply(closed, "received.over", diff=money(check.diff), **kw)
        return self._reply(closed, "received.unknown", **kw)

    async def close(self, user_id: str, case_id: str) -> RefundReply:
        """The user closes the case: accepting a short refund (needs the received amount), accepting
        a rejection, or dropping it."""
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        try:
            if case.state == S.RECEIVED:
                have = await self.store.list_evidence(user_id, case_id)
                basis = ev.basis_for_received(
                    have, case.amount_received_paise or 0, self.cfg.amount_tolerance_paise
                )
                closed = await self._move(
                    case,
                    S.CLOSED,
                    Source.USER,
                    "accepted",
                    reason=CloseReason.RECEIVED,
                    basis=basis,
                )
                return self._reply(closed, "closed.dropped", vendor=closed.vendor_name)
            if case.state == S.SUSPECTED:
                return await self.decline(user_id, case_id)
            reason = (
                CloseReason.ACCEPTED_REJECTION
                if case.state == S.REJECTED
                else CloseReason.USER_DROPPED
            )
            closed = await self._move(case, S.CLOSED, Source.USER, reason.value, reason=reason)
        except (IllegalTransition, GuardFailed):
            return self._reply(case, "illegal", state=self._state_text(case.state))
        key = "closed.accepted" if reason == CloseReason.ACCEPTED_REJECTION else "closed.dropped"
        return self._reply(closed, key, vendor=closed.vendor_name)

    # ------------------------------------------------------------------ evidence
    async def attach_text(
        self, user_id: str, case_id: str, text: str, *, amount_paise: int | None = None
    ) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        e = ev.from_user_text(case, text, now=self.clock.now(), amount_paise=amount_paise)
        await self.store.add_evidence(e)
        return self._reply(case, "evidence.saved", level=t(f"level.{e.level.value}", self.lang))

    async def attach_receipt(
        self, user_id: str, case_id: str, data: bytes, *, amount_paise: int | None = None
    ) -> RefundReply:
        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        e = ev.from_receipt(case, data, now=self.clock.now(), amount_paise=amount_paise)
        await self.store.add_evidence(e)
        return self._reply(case, "evidence.saved", level=t(f"level.{e.level.value}", self.lang))

    async def attach_proof_items(
        self, user_id: str, case_id: str, items: list[EvidenceItem]
    ) -> int:
        """Link evidence items of a Friday follow-up task (observed / vendor_stated keep their
        level). Another user's items are refused. Returns how many were linked."""
        case = await self._guard(user_id, case_id)
        if case is None:
            return 0
        now, n = self.clock.now(), 0
        known = {e.proof_item_id for e in await self.store.list_evidence(user_id, case_id)}
        for item in items:
            if item.id in known:
                continue
            e = ev.from_proof_item(case, item, now=now)
            if e is not None:
                await self.store.add_evidence(e)
                n += 1
        return n

    async def on_followup_finished(
        self, user_id: str, task_id: str, items: list[EvidenceItem]
    ) -> RefundCase | None:
        """The vendor follow-up task Friday ran finished: link its proof, and an OPENED case is
        now REQUESTED (the vendor was asked)."""
        for case in await self.store.list_cases(user_id, OPEN_STATES):
            if case.proposal and case.proposal.task_id == task_id:
                await self.attach_proof_items(user_id, case.id, items)
                if case.state == S.OPENED:
                    case = await self._move(
                        case, S.REQUESTED, Source.CALL, "follow-up call finished"
                    )
                return case
        return None

    async def evidence_for(self, user_id: str, case_id: str) -> list[Any]:
        return await self.store.list_evidence(user_id, case_id)

    # ------------------------------------------------------------------ who to call
    async def resolve_contacts(self, user_id: str, case_id: str) -> Resolved:
        case = await self.store.get_case(user_id, case_id)
        if case is None:
            return Resolved()
        return await resolve(user_id, case, self.sources)

    async def who_to_call(self, user_id: str, case_id: str) -> RefundReply:
        self._need(user_id)
        case = await self.store.get_case(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        r = await resolve(user_id, case, self.sources)
        lines: list[str] = []
        if r.contacts:
            lines.append(t("who.header", self.lang, vendor=case.vendor_name))
            for i, c in enumerate(r.contacts, 1):
                lines.append(
                    t(
                        "who.line",
                        self.lang,
                        n=i,
                        number=c.number,
                        source=t(f"source.{c.source}", self.lang),
                    )
                )
        else:
            lines.append(t("followup.no_number", self.lang, vendor=case.vendor_name))
        if r.issuer_bank:
            lines.append(t("who.issuer", self.lang, bank=r.issuer_bank))
        return RefundReply(self._msg(case, "\n".join(lines)), [], case.id)

    async def set_number(self, user_id: str, case_id: str, raw: str) -> RefundReply:
        """The user types a vendor number. It is stored as user-supplied; it is the only number
        Friday ever adds to a case on its own account of nothing."""
        from friday.calls.numbers import canonical

        case = await self._guard(user_id, case_id)
        if case is None:
            return RefundReply(t("case.unknown", self.lang))
        num = canonical(raw)
        if num is None:
            return self._reply(case, "number.bad")
        case.user_number, case.updated_at = num, self.clock.now()
        await self.store.save_case(case)
        return self._reply(case, "number.saved")

    # ------------------------------------------------------------------ vendor follow-up
    def followup_spec(self, case: RefundCase, contact: Contact) -> TaskSpec:
        """The task a follow-up call becomes. Hold-fighting (customer care) will swap this one
        function for a CUSTOMER_CARE spec; nothing else changes."""
        return TaskSpec(
            type=TaskType.STATUS_CHASE,
            goal=f"Ask {case.vendor_name} about the status of a refund the user is waiting for",
            business_name=case.vendor_name,
            business_phone=contact.number,
            questions=list(copy.VENDOR_CALL_QUESTIONS[copy.lang_of(self.lang)]),
            call_mode=CallMode.AGENT,
            call_language=Language.HINGLISH,
            notes=f"refund case {case.id}",
        )

    def _draft(self, case: RefundCase) -> str:
        part = f" ({money(self._expected(case))})" if self._expected(case) else ""
        what = t(f"what.{case.origin.value}", self.lang)
        return t(
            "followup.draft_body",
            self.lang,
            what=what,
            amount_part=part,
        )

    async def _followup_message(self, case: RefundCase) -> RefundMessage:
        stop = copy.stop_hint(self.lang)
        draft = t("followup.draft", self.lang, draft=self._draft(case))
        if case.chase_count >= self.cfg.max_chase_calls:
            return RefundMessage(
                self._msg(case, t("followup.cap", self.lang, n=case.chase_count) + " " + stop),
                [self._btn(case, "close", "btn.close")],
                case.id,
            )
        if not self.cfg.chase_calls_enabled:
            return RefundMessage(
                self._msg(case, t("followup.off", self.lang) + "\n" + draft), [], case.id
            )
        r = await resolve(case.user_id, case, self.sources)
        if r.empty:
            case.proposal = Proposal(kind="call", status="needs_number")
            await self.store.save_case(case)
            return RefundMessage(
                self._msg(
                    case, t("followup.no_number", self.lang, vendor=case.vendor_name) + "\n" + draft
                ),
                [],
                case.id,
            )
        c = r.contacts[0]
        case.proposal = Proposal(kind="call", status="offered", contact_id=c.contact_id)
        await self.store.save_case(case)
        text = t(
            "followup.call",
            self.lang,
            vendor=case.vendor_name,
            number=c.number,
            source=t(f"source.{c.source}", self.lang),
        )
        return RefundMessage(
            self._msg(case, text + "\n" + draft + "\n" + stop),
            [self._btn(case, "call", "btn.call_ok"), self._btn(case, "nocall", "btn.call_no")],
            case.id,
        )

    async def approve_followup(self, user_id: str, case_id: str) -> RefundReply:
        self._need(user_id)
        case = await self.store.get_case(user_id, case_id)
        p = case.proposal if case else None
        if (
            case is None
            or p is None
            or p.kind != "call"
            or p.status != "offered"
            or case.state == S.CLOSED
        ):
            return RefundReply(t("case.unknown", self.lang))
        if not self.cfg.chase_calls_enabled or self.tasks is None:
            return self._reply(case, "followup.off")
        if case.chase_count >= self.cfg.max_chase_calls:
            return self._reply(case, "followup.cap", n=case.chase_count)
        r = await resolve(user_id, case, self.sources)
        contact = next((c for c in r.contacts if c.contact_id == p.contact_id), None)
        if contact is None:  # the number is no longer held: never substitute another one
            return self._reply(case, "followup.no_number", vendor=case.vendor_name)
        task_id = await self.tasks.create_task(
            user_id, self.followup_spec(case, contact), approved=False
        )
        case.proposal = p.model_copy(update={"status": "approved", "task_id": task_id})
        case.chase_count += 1
        case.updated_at = self.clock.now()
        await self.store.save_case(case)
        return self._reply(case, "followup.approved")

    async def decline_followup(self, user_id: str, case_id: str) -> RefundReply:
        self._need(user_id)
        case = await self.store.get_case(user_id, case_id)
        if (
            case is None
            or case.proposal is None
            or case.proposal.status not in ("offered", "needs_number")
        ):
            return RefundReply(t("case.unknown", self.lang))
        case.proposal = case.proposal.model_copy(update={"status": "declined"})
        case.updated_at = self.clock.now()
        await self.store.save_case(case)
        return self._reply(case, "followup.declined")

    # ------------------------------------------------------------------ listing
    async def where_is_my_refund(self, user_id: str) -> RefundReply:
        self._need(user_id)
        now = self.clock.now()
        cases = await self.store.list_cases(user_id, OPEN_STATES)
        if not cases:
            return RefundReply(t("list.none", self.lang))
        lines = [t("list.header", self.lang)]
        for i, c in enumerate(cases, 1):
            age = age_text(_days(c.created_at, now), self.lang)
            exp = self._expected(c)
            if c.state == S.PROMISED and c.promised_date:
                lines.append(
                    t(
                        "list.item.promised",
                        self.lang,
                        n=i,
                        vendor=c.vendor_name,
                        promised_amount=money(c.promised_amount_paise),
                        date=fmt_date(c.promised_date),
                        age=age,
                    )
                )
            else:
                amount = f" ({money(exp)})" if exp else ""
                lines.append(
                    t(
                        "list.item",
                        self.lang,
                        n=i,
                        vendor=c.vendor_name,
                        amount=amount,
                        state=self._state_text(c.state),
                        age=age,
                    )
                )
        lines.append(t("list.footer", self.lang))
        return RefundReply("\n".join(lines))

    async def set_muted(self, user_id: str, muted: bool) -> RefundReply:
        self._need(user_id)
        for c in await self.store.list_cases(user_id, OPEN_STATES):
            c.muted = muted
            await self.store.save_case(c)
        return RefundReply(t("muted" if muted else "unmuted", self.lang))

    async def money_recovered(self, user_id: str, since: datetime | None = None) -> MoneyRecovered:
        """For the Wrapped card: ONLY cases closed as received, with proof or the user's word."""
        total = n = proof = 0
        for c in await self.store.list_cases(user_id, (S.CLOSED,)):
            if (
                c.closed_reason != CloseReason.RECEIVED
                or c.closed_basis is None
                or not c.amount_received_paise
            ):
                continue
            if since is not None and c.state_changed_at < since:
                continue
            total += c.amount_received_paise
            n += 1
            proof += 1 if c.closed_basis == Basis.PROOF else 0
        return MoneyRecovered(total, n, proof)

    # ------------------------------------------------------------------ the scheduler
    async def tick(self) -> dict[str, list[Outcome]]:
        out: dict[str, list[Outcome]] = {}
        for uid in await self.store.users_with_open_cases():
            if self.enabled_for(uid):
                out[uid] = await self.run_user(uid)
        return out

    async def run_user(self, user_id: str) -> list[Outcome]:
        """Send the reminders that are due: not in quiet hours, not over the weekly cap, never
        twice, never late (a reminder held past its expiry is dropped)."""
        self._need(user_id)
        now = self.clock.now()
        due: list[tuple[datetime, RefundCase, Reminder]] = []
        outcomes: list[Outcome] = []
        for case in await self.store.list_cases(user_id, OPEN_STATES):
            if case.state == S.SUSPECTED and now >= case.state_changed_at + timedelta(
                days=self.cfg.suspected_lapse_days
            ):
                await self._move(
                    case, S.CLOSED, Source.TIMER, "never confirmed", reason=CloseReason.UNCONFIRMED
                )
                outcomes.append(Outcome(f"refund:{case.id}:lapse", "lapse", "lapsed", case.id))
                continue
            if case.muted:
                continue
            nudges = await self.store.list_nudges(user_id, case.id)
            prefix = f"refund:{case.id}:{case.state_epoch}:"
            rem = next_reminder(
                case,
                sent_in_epoch=sum(1 for n in nudges if n.key.startswith(prefix)),
                sent_total=len(nudges),
                cfg=self.cfg,
            )
            if rem is not None and rem.due_at <= now:
                due.append((rem.due_at, case, rem))
        for _, case, rem in sorted(due, key=lambda x: x[0]):
            outcomes.append(await self._consider(user_id, case, rem, now))
        return outcomes

    async def _consider(
        self, user_id: str, case: RefundCase, rem: Reminder, now: datetime
    ) -> Outcome:
        def out(action: str, text: str | None = None) -> Outcome:
            return Outcome(rem.key, rem.stage, action, case.id, text)

        if now >= rem.expires_at:
            await self.store.add_nudge(
                RefundNudge(
                    user_id=user_id,
                    case_id=case.id,
                    key=rem.key,
                    stage=rem.stage,
                    status="expired",
                    sent_at=now,
                )
            )
            return out("expired")
        if is_quiet_hours(now, self.cfg.quiet_start, self.cfg.quiet_end):
            return out("held_quiet")
        if (
            await self.store.count_sent_since(user_id, now - timedelta(days=7))
            >= self.cfg.weekly_cap
        ):
            return out("held_cap")
        msg = await self._message_for(case, rem, now)
        msg.dedupe_key = rem.key
        if self.sender is None or not await self.sender.send(user_id, msg):
            return out("failed", msg.text)
        await self.store.add_nudge(
            RefundNudge(
                user_id=user_id,
                case_id=case.id,
                key=rem.key,
                stage=rem.stage,
                text=msg.text,
                sent_at=now,
            )
        )
        return out("sent", msg.text)

    async def _message_for(self, case: RefundCase, rem: Reminder, now: datetime) -> RefundMessage:
        stop, lang = copy.stop_hint(self.lang), self.lang
        age = age_text(_days(case.created_at, now), lang)
        exp = self._expected(case)
        amount_part = f" ({money(exp)})" if exp else ""
        recd = self._btn(case, "recd", "btn.received")
        notyet = self._btn(case, "notyet", "btn.notyet")
        stage = rem.stage
        if stage in ("suspect_ask", "suspect_again"):
            yes, no = self._btn(case, "yes", "btn.yes"), self._btn(case, "no", "btn.no")
            if stage == "suspect_again":
                return RefundMessage(
                    self._msg(case, t("suspect.again", lang, vendor=case.vendor_name, stop=stop)),
                    [yes, no],
                    case.id,
                )
            amt = (
                t("amount.expected", lang, amount=money(case.amount_expected_paise))
                if case.amount_expected_paise
                else ""
            )
            what = t(f"what.{case.origin.value}", lang)
            return RefundMessage(
                self._msg(
                    case, t("suspect.ask", lang, vendor=case.vendor_name, what=what, amount=amt)
                )
                + " "
                + stop,
                [yes, no],
                case.id,
            )
        if stage == "requested_q":
            return RefundMessage(
                self._msg(
                    case, t("nudge.requested_q", lang, vendor=case.vendor_name, age=age, stop=stop)
                ),
                [self._btn(case, "asked", "btn.asked"), notyet],
                case.id,
            )
        if stage == "received_q":
            d = case.promised_date or ist_date(now)
            return RefundMessage(
                self._msg(
                    case,
                    t(
                        "nudge.received_q",
                        lang,
                        vendor=case.vendor_name,
                        amount=money(case.promised_amount_paise),
                        date=fmt_date(d),
                        stop=stop,
                    ),
                ),
                [recd, notyet],
                case.id,
            )
        if stage == "rejected_q":
            return RefundMessage(
                self._msg(case, t("nudge.rejected_q", lang, vendor=case.vendor_name, stop=stop)),
                [self._btn(case, "chase", "btn.chase"), self._btn(case, "close", "btn.close")],
                case.id,
            )
        if stage == "short_q":
            left = max(0, (self._expected(case) or 0) - (case.amount_received_paise or 0))
            return RefundMessage(
                self._msg(
                    case,
                    t(
                        "nudge.short_q",
                        lang,
                        vendor=case.vendor_name,
                        amount=money(case.amount_received_paise),
                        diff=money(left),
                        stop=stop,
                    ),
                ),
                [self._btn(case, "chase", "btn.chase"), self._btn(case, "close", "btn.close")],
                case.id,
            )
        if stage == "followup":
            return await self._followup_message(case)
        return RefundMessage(
            self._msg(
                case,
                t(
                    "nudge.checkin",
                    lang,
                    vendor=case.vendor_name,
                    amount_part=amount_part,
                    age=age,
                    state=self._state_text(case.state),
                    stop=stop,
                ),
            ),
            [recd, notyet],
            case.id,
        )
