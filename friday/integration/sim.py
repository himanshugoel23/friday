"""Offline lines for tests and ``friday consumer demo``: a callee played by a W2 simulation persona.

``PersonaTelephony`` maps a dialled number to a persona id (friendly elder, voicemail, wrong number,
"stop calling", ...), so the whole path (approval -> gate -> task -> W2 engine -> report) can be run
with no network and no real audio. All numbers used with it are invented.
"""

from __future__ import annotations

from datetime import date

from friday.integration.bridge import TelephonyFactory, TelephonyLease
from friday.liveagent.contracts import CallBrief as LiveBrief
from friday.liveagent.contracts import Callee as LiveCallee
from friday.liveagent.simulation.callee import FakeUserChannel, SimClock, SimTelephony
from friday.liveagent.simulation.personas import PERSONAS, Persona
from friday.savings.rules import EXAMPLE_VERIFIER, CardRule, RewardType


def persona_by_id(persona_id: str) -> Persona:
    return next(p for p in PERSONAS if p.id == persona_id)


class PersonaTelephony(TelephonyFactory):
    """``dial_number -> persona``; a number with no persona gets silence (nobody picks up)."""

    def __init__(
        self, personas: dict[str, str] | None = None, *, default: str | None = None
    ) -> None:
        self.personas = dict(personas or {})
        self.default = default
        self.dialled: list[str] = []  # masked-safe: only ever holds what the test dialled
        self.lines: list[SimTelephony] = []

    def assign(self, number: str, persona_id: str) -> None:
        self.personas[number] = persona_id

    async def open(
        self, *, brief: LiveBrief, callee: LiveCallee, dial_number: str, from_number: str | None
    ) -> TelephonyLease:
        self.dialled.append(dial_number)
        pid = self.personas.get(dial_number, self.default)
        clock = SimClock()
        if pid is None:
            line = SimTelephony([], brief.language, clock, tail="silence")
            self.lines.append(line)
            return TelephonyLease(line, clock.now)
        persona = persona_by_id(pid)
        line = SimTelephony(persona.script, brief.language, clock, tail=persona.tail)
        self.lines.append(line)
        channel = (
            FakeUserChannel(answer=persona.user_answer, clock=clock) if persona.asks_user else None
        )
        return TelephonyLease(line, clock.now, channel)


def demo_card_rules(today: date) -> list[CardRule]:
    """INVENTED rules for "HDFC Regalia" and "SBI Cashback", marked as EXAMPLE rows (an
    ``example.invalid`` source, verifier ``EXAMPLE_NOT_REAL``). They are served only when the
    savings config allows example rows (tests and the demo), never in production, and the rates
    are made up: they say nothing about the real cards."""
    note = "EXAMPLE ROW: invented for tests and demos. NOT a real offer."
    common = dict(
        reward_type=RewardType.CASHBACK,
        source_url="https://example.invalid/demo-card",
        checked_on=today,
        verified_by=EXAMPLE_VERIFIER,
        notes=note,
    )
    return [
        CardRule(
            bank="HDFC Bank", card_name="Regalia", category="food_delivery", rate_bp=200,
            monthly_cap_paise=50_000, **common,
        ),  # type: ignore[arg-type]
        CardRule(
            bank="HDFC Bank", card_name="Regalia", category="all", rate_bp=100, **common,
        ),  # type: ignore[arg-type]
        CardRule(
            bank="SBI Card", card_name="Cashback", category="food_delivery", rate_bp=500,
            monthly_cap_paise=30_000, **common,
        ),  # type: ignore[arg-type]
        CardRule(
            bank="SBI Card", card_name="Cashback", category="all", rate_bp=100, **common,
        ),  # type: ignore[arg-type]
    ]  # fmt: skip
