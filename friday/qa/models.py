# ruff: noqa: E501
"""Small data classes shared by the QA runner, the backends, the page and the CLI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from friday.qa.scenarios import Scenario

# run phases, in order. A run ends in one of FINAL.
PHASES = ("planned", "countdown", "dialling", "in_call", "done", "failed", "cancelled", "refused")
FINAL = frozenset({"done", "failed", "cancelled", "refused"})


@dataclass
class CallSpec:
    """What a backend needs to place ONE QA call. ``number`` is always the allow-listed number
    (QaGuard fills it); a scenario never carries a number."""

    scenario: Scenario
    number: str = field(repr=False)
    seconds: int
    run_id: str
    first_name: str
    vendor_name: str = ""
    area: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallReport:
    status: str  # completed | no_answer | busy | failed | refused | chat
    duration_s: float = 0.0
    cost_inr: float = 0.0
    summary: str = ""
    transcript: list[dict[str, str]] = field(default_factory=list)  # {who, text}
    transcript_path: str | None = None
    outcome: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> CallReport:
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in names})


Emit = Callable[[str], None]


class CallBackend(Protocol):
    async def run(self, spec: CallSpec, emit: Emit) -> CallReport: ...


class ChatBackend(Protocol):
    async def run(self, scenario: Scenario, emit: Emit) -> CallReport: ...


@dataclass
class Run:
    id: str
    scenario: str
    title: str
    kind: str
    phase: str = "planned"
    created: float = 0.0
    ring_at: float | None = None  # epoch seconds: when the phone will ring
    lines: list[str] = field(default_factory=list)
    report: CallReport | None = None
    error: str = ""
    est_cost_inr: float = 0.0
    seconds: int = 0
    real: list[str] = field(default_factory=list)
    simulated: list[str] = field(default_factory=list)
    cancel_requested: bool = False

    def to_json(self, now: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "title": self.title,
            "kind": self.kind,
            "phase": self.phase,
            "final": self.phase in FINAL,
            "seconds_to_ring": max(0, int(self.ring_at - now))
            if self.ring_at and self.phase == "countdown"
            else None,
            "lines": list(self.lines[-60:]),
            "report": self.report.to_json() if self.report else None,
            "error": self.error,
            "est_cost_inr": self.est_cost_inr,
            "max_seconds": self.seconds,
            "real": self.real,
            "simulated": self.simulated,
        }
