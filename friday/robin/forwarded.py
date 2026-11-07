# ruff: noqa: E501
"""A call FORWARDED from a Robin member's phone (T10): Robin answers, takes who / what / urgent in at most ~75 s, and hands it to the missed-call flow.

    api/callbacks.py::_from_event  (answered inbound call, BEFORE the receptionist's ``claims``)
        -> RobinHub.forwarded_call(event)
        -> ForwardedCalls.claims: switch on? redirecting number = the phone of a PARENT or CHILD of an ACTIVE family?
        -> ForwardedCalls.serve: the voice agent speaks the fixed ``missed.*`` lines over the parked leg (cap 60-90 s, default 75),
           collects the answers, ``MissedCallService.on_missed`` (message to the missed person; urgent: the ring loop, every 3 min, 6 tries,
           stops on pickup / acknowledgement / "I am fine"; security paths ignore time of day, T20), then a WhatsApp "X has been told" to the
           caller when the caller is a known family member (and ONLY then).

A number that is not a Robin member's is NOT claimed: the receptionist path (or the front door) runs exactly as before. Switch off = no change.

Nothing here dials: the only telephony used is the leg the carrier already delivered. Spoken lines are the PENDING ``missed.*`` lines; the
caller hears the missed person's language (parent: their own; child: the chat language). The caller's number is never put in a message or a log
(only the family label, or "an unknown caller"). Not verified on a real SIM or on Vobiz: which webhook field carries the redirecting number
(see friday/receptionist/probe.py), and how each carrier fills the caller id of a forwarded call.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from friday.calls.numbers import canonical
from friday.core.logging import get_logger
from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, TelephonyPort
from friday.receptionist.carriers import CARRIER_ALIASES, codes_for, find_carrier
from friday.receptionist.identify import candidate_values, pick_original
from friday.receptionist.models import ReceptionistConfig
from friday.robin import answers as ans
from friday.robin import lines
from friday.robin.context import Ctx
from friday.robin.missedcall import MissedCallService, MissedResult
from friday.robin.models import AnswerRaw, Family, FamilyStatus, Member, Role
from friday.robin.store import Record

log = get_logger(__name__)

LISTEN_S = 7.0  # one listen window (the receptionist uses the same)
CLOSE_RESERVE_S = 8.0  # kept free for the closing line inside the cap
MIN_QUESTION_S = 6.0  # do not start a question with less than this left
SHORT_SILENCES = 1  # a question is repeated at most once


def forward_target(settings: Any) -> str | None:
    """The number the carrier forwards to (Robin's line): the shared receptionist number, else the first Friday number. None = not set."""
    inbound = getattr(settings, "receptionist_inbound_number", None)
    nums = [inbound] if inbound else list(getattr(settings, "friday_numbers", []) or [])
    return str(nums[0]) if nums else None


def known_carrier(text: str) -> str | None:
    """'forwarding jio' / 'airtel' / 'vodafone idea' -> 'jio' | 'airtel' | 'vi' (BSNL is known to carriers.py but not offered in the onboarding)."""
    t = " ".join((text or "").lower().replace("forwarding", " ").replace("forward", " ").split())
    key = CARRIER_ALIASES.get(t)
    return key if key in ("jio", "airtel", "vi") else None


def forwarding_text(ctx: Ctx, carrier_key: str, *, who: str, lang: str, config: ReceptionistConfig | None = None) -> str | None:
    """The per-carrier setup text for one phone. Every code is general knowledge about the GSM standard and marked [U] (unverified on a real SIM);
    None when Robin's forwarding number is not configured."""
    number = forward_target(ctx.settings)
    carrier = find_carrier(carrier_key)
    if number is None or carrier is None:
        return None
    cs = codes_for(carrier, config or ReceptionistConfig(enabled=True), number)
    codes = "\n".join(f"- {c.label.replace('_', ' ')}: {c.code} [U] ({c.condition_text})" for c in cs.activate)
    status = " ".join(code for _, code in cs.status)
    notes = " ".join(n for n in cs.notices[1:])  # the general-knowledge notice is already in the line itself
    return ctx.say("forward.codes", lang, who=who, carrier=carrier.name, codes=codes, status=status, cancel=cs.cancel_all, notes=notes)


class ForwardedCalls:
    def __init__(self, ctx: Ctx, missed: MissedCallService, *, telephony: Callable[[], Any], mono: Callable[[], float] = time.monotonic) -> None:
        self.ctx, self.missed, self._telephony, self.mono = ctx, missed, telephony, mono

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.ctx.settings, "robin_forwarded_calls_enabled", False))

    # ------------------------------------------------------------------ who was this call for?
    def redirecting_number(self, event: Any) -> str | None:
        """The original dialled (diverting) number, E.164, from the configured webhook keys. Friday's own numbers, the caller's and the dialled
        number are not diversions. Nothing is guessed: a value must still contain a phone number."""
        s = self.ctx.settings
        own = {x for x in (canonical(n) for n in [getattr(s, "receptionist_inbound_number", None), *list(getattr(s, "friday_numbers", []) or [])] if n) if x}
        caller_n = canonical(getattr(event, "from_phone", None) or "")
        dialled_n = canonical(getattr(event, "to_number", None) or "")
        for name, value in candidate_values(getattr(event, "redirecting", None), getattr(event, "call_fields", None), list(getattr(s, "receptionist_redirect_fields", []) or [])):
            raw = pick_original(name, value)
            n = canonical(raw) if raw else None
            if n is None or n in own or n in (caller_n, dialled_n):
                continue
            return n
        return None

    async def claims(self, event: Any) -> tuple[Family, Member] | None:
        """(family, missed member) when this is a forwarded call for a PARENT or CHILD of an ACTIVE family; else None (not ours)."""
        if not self.enabled:
            return None
        e164 = self.redirecting_number(event)
        if e164 is None:
            return None
        for m in await self.ctx.store.members_by_phone(e164):
            if m.role not in (Role.PARENT, Role.CHILD):
                continue
            fam = await self.ctx.store.get_family(m.family_id)
            if fam is not None and fam.status == FamilyStatus.ACTIVE:  # onboarding (no consent yet), paused (the parent said stop) or deleted: not ours
                return fam, m
        return None

    # ------------------------------------------------------------------ the call
    async def handle(self, event: Any) -> bool:
        """True = the call was Robin's (the receptionist and the front door must not see it)."""
        hit = await self.claims(event)
        if hit is None:
            return False
        fam, missed = hit
        caller_phone = getattr(event, "from_phone", None)
        ref = getattr(event, "provider_call_id", None)
        log.info("robin: forwarded call for a %s", missed.role.value)  # no number, no names
        lang = await self._lang(fam, missed)
        leg = None
        tel = self._telephony()
        take = getattr(tel, "take_inbound", None)
        if callable(take) and ref:
            leg = take(ref)
        answers: list[AnswerRaw] = []
        if leg is None:
            log.warning("robin: no parked leg for a forwarded call; the missed person still gets a 'called' message")
        else:
            from friday.liveagent.sarvam_adapter import SarvamLegPort  # noqa: PLC0415

            answers = await self.collect(SarvamLegPort(leg), fam, missed, lang)
        answers = await self._limit_urgent(fam, answers)
        res = await self.missed.on_missed(missed.phone or "", caller_phone, answers)
        if res is not None:
            await self._tell_caller(fam, missed, caller_phone, res)
        return True

    async def _lang(self, fam: Family, missed: Member) -> str:
        if missed.role == Role.PARENT and missed.language in lines.LANGS:
            return missed.language
        return await self.ctx.chat_lang(fam)

    async def collect(self, port: TelephonyPort, fam: Family, missed: Member, lang: str) -> list[AnswerRaw]:
        """Speak the fixed questions, listen, close. Hard cap ``robin_forwarded_call_max_s`` (60-90 s); never dials; a hang-up ends it and what was said so far counts."""
        c = self.ctx
        cap = float(c.settings.robin_forwarded_call_max_s)
        t0 = self.mono()
        label = fam.parent_label if missed.role == Role.PARENT else (missed.name or "ji")
        steps = await self.missed.steps_for(fam, missed)
        clang = CallLanguage(lang if lang in lines.LANGS else "hinglish")
        out: list[AnswerRaw] = []
        closing = "missed.normal_ack"
        try:
            for step in steps:
                silences = 0
                while True:
                    if cap - (self.mono() - t0) < MIN_QUESTION_S + CLOSE_RESERVE_S:
                        break
                    await port.speak(c.say(step.line, lang, **step.slots), clang)
                    left = cap - (self.mono() - t0) - CLOSE_RESERVE_S
                    heard = await port.listen(max(1.0, min(LISTEN_S, left)))
                    said = " ".join((getattr(heard, "text", "") or "").split())[:200]
                    if not said or (step.expect == "yesno" and ans.yesno(said) is None):
                        silences += 1
                        if silences > SHORT_SILENCES:
                            break
                        continue
                    out.append(AnswerRaw(line=step.line, text=said))
                    if step.expect == "yesno" and ans.yesno(said) is True:
                        closing = step.on_yes or closing
                    break
            await port.speak(c.say(closing, lang, parent=label), clang)
        except CallDropped:
            log.info("robin: forwarded caller hung up")
        except Exception as e:  # noqa: BLE001 - CallEnded and anything else: take what we have
            log.info("robin: forwarded call ended (%s)", type(e).__name__)
        finally:
            with contextlib.suppress(Exception):
                await port.hangup()
        return out

    # ------------------------------------------------------------------ anti-abuse
    async def _limit_urgent(self, fam: Family, answers: list[AnswerRaw]) -> list[AnswerRaw]:
        """More forwarded calls than ``robin_forwarded_per_hour`` in the last hour for one family: the message is still delivered but a bare 'yes' to
        'is it urgent' no longer starts the ring loop (a stranger can otherwise make Robin ring the family six times, repeatedly). Danger words in what
        was said still count (missedcall.py)."""
        c = self.ctx
        now = c.clock.now()
        rows = await c.store.list(fam.id, "audit", since=now - timedelta(hours=1), until=now + timedelta(minutes=1))
        recent = sum(1 for r in rows if r.data.get("event") == "missed_call")
        if recent < int(c.settings.robin_forwarded_per_hour):
            return answers
        log.warning("robin: forwarded-call cap reached for a family; urgent answers are not acted on")
        return [AnswerRaw(line=a.line, text="no" if a.line == "missed.ask_urgent" else a.text) for a in answers]

    # ------------------------------------------------------------------ "X has been told", to a known family caller only
    async def _tell_caller(self, fam: Family, missed: Member, caller_phone: str | None, res: MissedResult) -> None:
        c = self.ctx
        e = canonical(caller_phone) if caller_phone else None
        if e is None:
            return
        caller = next((m for m in await c.store.members_by_phone(e) if m.family_id == fam.id and m.id != missed.id and m.role in (Role.PARENT, Role.CHILD, Role.CO_ADMIN)), None)
        if caller is None:  # a stranger gets nothing (no confirmation that this number is a Robin family's)
            return
        label = fam.parent_label if missed.role == Role.PARENT else (missed.name or "ji")
        key = "missed.caller_told_urgent" if res.urgent else "missed.caller_told"
        try:
            if caller.role == Role.PARENT:
                text = c.say(key, caller.language, missed=label)
                ch = c.parent_channel
                if ch is not None:
                    await ch.send_text(caller, text)
                    await ch.send_voice_note(caller, text, caller.language)
                else:
                    await c.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=c.clock.now(), data={"member_id": caller.id, "line": key, "purpose": "missed_told", "text": text, "incident_id": None}))
            elif caller.user_id:
                await c.send(caller.user_id, c.say(key, await c.chat_lang(fam), missed=label), [])
        except Exception as e2:  # noqa: BLE001 - the confirmation never breaks the flow
            log.warning("robin: 'has been told' message failed (%s)", type(e2).__name__)
