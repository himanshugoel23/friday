# ruff: noqa: E501
"""'Screen unknown callers' and 'listen in' modes (T16, tested with fakes only). Design in docs/ROBIN_FAMILY_CORE.md section 9.

T16 adds ``run_screen`` / ``run_listen_in`` at the bottom: they drive a ``callbridge.CallBridge`` and feed the call turns to
``DeviceService.feed_call_turn`` (tier output -> scenario S4P -> the child). The older ``screen`` / ``listen_in_*`` methods are the original
decision stubs and stay.

THE ORIGINAL STUB TEXT FOLLOWS. NOTHING HERE DIALS, ANSWERS OR LISTENS WITHOUT A BRIDGE (none is wired). It defines the interfaces and the decision flow so that the
telephony wiring (carrier forwarding to Robin's own line, like friday/receptionist) and the analyzer (another
builder, friday/robindevice) can plug in. Both modes are behind switches, default OFF
(``FRIDAY_ROBIN_SCREEN_UNKNOWN_ENABLED``, ``FRIDAY_ROBIN_LISTEN_IN_ENABLED``) and every line is PENDING.

* SCREEN-FIRST: Robin answers an unknown inbound caller first (the call arrives on Robin's line by carrier
  forwarding), says it is an AI assistant, asks who is calling and why, streams the transcript to a
  ``CallPatternAnalyzer`` and bridges to the parent ONLY if the verdict is FINE. The analyzer judges the
  PATTERN of the call (urgency ramp, secrecy, a money ask), not a safe word (founder decision 2026-11-04).
* LISTEN-IN: the parent adds Robin to a live 3-way call. Robin speaks an audible disclosure at the start,
  listens, and whispers a warning to the parent only. Needs the parent's ``call_listening`` consent (a
  sensitive item: the parent's own yes). No recording; with retention 0 days only verdict cues are kept.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from friday.robin import answers as ans
from friday.robin import lines
from friday.robin.callbridge import BridgeRefused, BridgeSession, CallBridge
from friday.robin.context import Ctx
from friday.robin.models import ConsentItem, Family, FamilyStatus, Member

TIERS = ("NONE", "INFO", "WATCH", "HIGH")
MAX_SCREEN_TURNS = 3  # the unknown caller gets three turns to say who they are
MAX_LISTEN_TURNS = 400  # hard bound on one listen-in
# "Robin, suno" / "Robin, listen" (the parent, on a call)
LISTEN_TRIGGER = re.compile(r"\b(suno|suniye|sunna|listen( in)?|sun lo|sun lijiye)\b|सुनो|सुनिए|सुन लो", re.IGNORECASE)


def is_listen_trigger(text: str, brand: str = "Robin") -> bool:
    t = text.strip().lower()
    return bool(LISTEN_TRIGGER.search(t)) and (brand.lower() in t or "रॉबिन" in t or len(t.split()) <= 3)


class Verdict(StrEnum):
    FINE = "fine"
    RISKY = "risky"
    UNSURE = "unsure"


@dataclass(frozen=True)
class PatternVerdict:
    verdict: Verdict
    why: str = ""  # one line, shown to the child
    signals: tuple[str, ...] = ()  # e.g. ('urgency_ramp', 'secrecy', 'money_ask')


@runtime_checkable
class CallPatternAnalyzer(Protocol):
    """Implemented elsewhere (friday/robindevice). Gets the transcript so far, text only, no audio."""

    async def analyze(self, *, family_id: str, parent_member_id: str, transcript: list[str], final: bool) -> PatternVerdict: ...


class FakeAnalyzer:
    def __init__(self, verdict: PatternVerdict | None = None) -> None:
        self.verdict = verdict or PatternVerdict(Verdict.FINE)
        self.seen: list[list[str]] = []

    async def analyze(self, *, family_id: str, parent_member_id: str, transcript: list[str], final: bool) -> PatternVerdict:  # noqa: ARG002
        self.seen.append(list(transcript))
        return self.verdict


@dataclass
class ScreenDecision:
    action: str  # bridge | decline | refused
    reason: str = ""
    lines: list[str] = field(default_factory=list)  # line keys Robin would speak


class ScreeningService:
    """Decision flow only. The real call leg is attached by the telephony wiring (not built)."""

    def __init__(self, ctx: Ctx, analyzer: CallPatternAnalyzer | None = None, *, bridge: CallBridge | None = None, device: Callable[[], Any] | None = None) -> None:
        self.ctx, self.analyzer = ctx, analyzer or FakeAnalyzer()
        self.bridge, self._device = bridge, device or (lambda: None)  # T16: the call bridge and the DeviceService (None = nothing runs)

    def enabled(self, mode: str) -> bool:
        return bool(getattr(self.ctx.settings, "robin_screen_unknown_enabled" if mode == "screen" else "robin_listen_in_enabled", False))

    async def screen(self, family: Family, parent: Member, transcript: list[str]) -> ScreenDecision:
        if not self.enabled("screen"):
            return ScreenDecision("refused", "switch_off")
        if family.status != FamilyStatus.ACTIVE or parent.paused:
            return ScreenDecision("refused", "not_active")
        v = await self.analyzer.analyze(family_id=family.id, parent_member_id=parent.id, transcript=transcript, final=True)
        if v.verdict == Verdict.FINE:
            await self.ctx.audit(family, "screen", f"Screened an unknown caller for {family.parent_label}: connected.")
            return ScreenDecision("bridge", v.why, ["screen.connect"])
        child_lang = await self.ctx.chat_lang(family)
        await self.ctx.tell_child(family, self.ctx.say("screen.child_note", child_lang, parent=family.parent_label, verdict=v.verdict.value, why=v.why or "-"))
        await self.ctx.audit(family, "screen", f"Screened an unknown caller for {family.parent_label}: not connected ({v.verdict.value}).")
        return ScreenDecision("decline", v.why, ["screen.decline"])

    async def listen_in_start(self, family: Family, parent: Member) -> ScreenDecision:
        """The parent adds Robin to a live call. Refused without the parent's own consent; the disclosure is always the first thing spoken."""
        if not self.enabled("listen"):
            return ScreenDecision("refused", "switch_off")
        if not await self.ctx.has_consent(parent, ConsentItem.CALL_LISTENING):
            return ScreenDecision("refused", "no_consent")
        return ScreenDecision("bridge", "", ["listen.disclose"])

    async def listen_in_verdict(self, family: Family, parent: Member, transcript: list[str]) -> ScreenDecision:
        v = await self.analyzer.analyze(family_id=family.id, parent_member_id=parent.id, transcript=transcript, final=False)
        if v.verdict == Verdict.RISKY:
            return ScreenDecision("warn", v.why, ["listen.warn"])  # whispered to the parent only
        return ScreenDecision("continue")


    # ------------------------------------------------------------------ T16: the full path (bridge -> DeviceService.feed_call_turn -> S4P)
    async def _gate(self, family: Family, parent: Member, mode: str) -> ScreenDecision | None:
        """None = go ahead. Security paths ignore time of day: quiet hours and the calling window are never consulted here."""
        if not self.enabled(mode):
            return ScreenDecision("refused", "switch_off")
        if family.status != FamilyStatus.ACTIVE or parent.paused:  # the parent said stop (or Robin is not set up): Robin does not listen
            return ScreenDecision("refused", "not_active")
        if not await self.ctx.has_consent(parent, ConsentItem.CALL_LISTENING):  # given by the child on the parent's behalf; off by default
            return ScreenDecision("refused", "no_consent")
        if self.bridge is None or self._device() is None:
            return ScreenDecision("refused", "no_bridge")
        return None

    async def run_screen(self, call_ref: str, family: Family, parent: Member, *, caller_known: bool = False) -> ScreenDecision:
        """Screen-first. The unknown caller hears ``screen.ask`` BEFORE the parent's phone rings; the parent's phone rings only when the pattern
        stays below WATCH. No answer from the caller, WATCH or HIGH: declined, the child is told why (no transcript)."""
        if (refused := await self._gate(family, parent, "screen")) is not None:
            return refused
        if caller_known:  # a saved number is not screened
            return ScreenDecision("bridge", "known_caller", [])
        dev, lang = self._device(), parent.language if parent.language in lines.LANGS else "hinglish"
        try:
            session = await self.bridge.answer(call_ref, screening_line=self.ctx.say("screen.ask", lang, parent=family.parent_label))  # type: ignore[union-attr]
        except BridgeRefused as e:
            return ScreenDecision("refused", str(e))
        tier, n, ok = "NONE", 0, False
        try:
            async for turn in session.turns():
                if turn.speaker != "caller":
                    continue
                n += 1
                res = await dev.feed_call_turn(parent.id, call_ref, "caller", turn.text, turn.t, {"unknown_number": True, "first_contact": True})
                tier = res.get("tier", tier) if isinstance(res, dict) else tier
                if tier in ("WATCH", "HIGH") or n >= MAX_SCREEN_TURNS:
                    break
            ok = n > 0 and tier in ("NONE", "INFO")
            if ok:
                await session.speak(self.ctx.say("screen.connect", lang, parent=family.parent_label), to="both")
                await session.connect_parent()
            else:
                await session.speak(self.ctx.say("screen.decline", lang, parent=family.parent_label), to="both")
                await session.leave()
        finally:
            dev.finish_call(parent.id, call_ref)
        if ok:
            await self.ctx.audit(family, "screen", f"Screened an unknown caller for {family.parent_label}: connected.")
            return ScreenDecision("bridge", "", ["screen.ask", "screen.connect"])
        why = "no answer from the caller" if n == 0 else f"call pattern level {tier}"
        await self.ctx.tell_child(family, self.ctx.say("screen.child_note", await self.ctx.chat_lang(family), parent=family.parent_label, verdict="not connected", why=why))
        await self.ctx.audit(family, "screen", f"Screened an unknown caller for {family.parent_label}: not connected ({tier}).")
        return ScreenDecision("decline", why, ["screen.ask", "screen.decline"])

    async def run_listen_in(self, call_ref: str, family: Family, parent: Member) -> ScreenDecision:
        """Listen-in, asked by the parent ("Robin, suno"). The disclosure is spoken to BOTH sides before the first word is analysed; HIGH is
        whispered to the parent only (once); the parent saying stop ends it. Transcript text is scored and dropped."""
        if (refused := await self._gate(family, parent, "listen")) is not None:
            return refused
        dev, lang = self._device(), parent.language if parent.language in lines.LANGS else "hinglish"
        try:
            session: BridgeSession = await self.bridge.join(call_ref, disclosure=self.ctx.say("listen.disclose", lang, parent=family.parent_label))  # type: ignore[union-attr]
        except BridgeRefused as e:
            return ScreenDecision("refused", str(e))
        top, warned, stopped, n = "NONE", False, False, 0
        child = await self.ctx.child(family)
        slots = {"parent": family.parent_label, "child": (child.name if child and child.name else "ji")}
        try:
            async for turn in session.turns():
                n += 1
                if turn.speaker == "parent" and ans.is_stop(turn.text):
                    stopped = True
                    break
                res = await dev.feed_call_turn(parent.id, call_ref, turn.speaker, turn.text, turn.t, {"unknown_number": True})
                tier = res.get("tier", "NONE") if isinstance(res, dict) else "NONE"
                top = max(top, tier, key=TIERS.index)
                if tier == "HIGH" and not warned:
                    warned = True
                    await session.speak(self.ctx.say("listen.warn", lang, **slots), to="parent")  # whispered: the caller does not hear it
                if n >= MAX_LISTEN_TURNS:
                    break
            await session.speak(self.ctx.say("listen.left", lang), to="both")
            await session.leave()
        finally:
            dev.finish_call(parent.id, call_ref)
        await self.ctx.audit(family, "listen_in", f"Robin listened in on a call for {family.parent_label} and left (highest level {top}; nothing recorded).")
        if top != "NONE":
            await self.ctx.tell_child(family, self.ctx.say("listen.child_note", await self.ctx.chat_lang(family), parent=family.parent_label, tier=top))
        return ScreenDecision("stopped" if stopped else "done", top, ["listen.disclose", *(["listen.warn"] if warned else []), "listen.left"])
