"""Offline lines for tests and ``friday consumer demo``: a callee played by a W2 simulation persona.

``PersonaTelephony`` maps a dialled number to a persona id (friendly elder, voicemail, wrong number,
"stop calling", ...), so the whole path (approval -> gate -> task -> W2 engine -> report) can be run
with no network and no real audio. All numbers used with it are invented.
"""

from __future__ import annotations

from friday.integration.bridge import TelephonyFactory, TelephonyLease
from friday.liveagent.contracts import CallBrief as LiveBrief
from friday.liveagent.contracts import Callee as LiveCallee
from friday.liveagent.simulation.callee import FakeUserChannel, SimClock, SimTelephony
from friday.liveagent.simulation.personas import PERSONAS, Persona


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
