# ruff: noqa: E501
"""STUB: 'screen unknown callers' and 'listen in' modes. Design in docs/ROBIN_FAMILY_CORE.md section 9.

NOTHING HERE DIALS, ANSWERS OR LISTENS. It defines the interfaces and the decision flow so that the
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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from friday.robin.context import Ctx
from friday.robin.models import ConsentItem, Family, FamilyStatus, Member


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

    def __init__(self, ctx: Ctx, analyzer: CallPatternAnalyzer) -> None:
        self.ctx, self.analyzer = ctx, analyzer

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
