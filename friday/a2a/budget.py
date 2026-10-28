# ruff: noqa: E501
"""Per-task budget shared down the whole agent tree (steps, seconds, cost). Plain code, no model."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "steps" | "seconds" | "cost"


@dataclass
class TaskBudget:
    max_steps: int = 30
    max_seconds: float = 40.0
    max_cost_inr: float = 8.0
    clock: Callable[[], float] = time.monotonic
    steps: int = 0
    cost_inr: float = 0.0
    started: float = field(default=0.0)
    exhausted: str | None = None

    def __post_init__(self) -> None:
        self.started = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def remaining_s(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed())

    def check(self) -> None:
        if self.exhausted:
            raise BudgetExceeded(self.exhausted)
        if self.steps >= self.max_steps:
            self._stop("steps")
        if self.elapsed() >= self.max_seconds:
            self._stop("seconds")
        if self.cost_inr >= self.max_cost_inr:
            self._stop("cost")

    def _stop(self, why: str) -> None:
        self.exhausted = why
        raise BudgetExceeded(why)

    def charge_step(self) -> None:
        """One A2A request. Raises BEFORE the request is sent when the budget is used up."""
        self.check()
        self.steps += 1

    def add_cost(self, inr: float) -> None:
        self.cost_inr += max(0.0, float(inr or 0.0))
        if self.cost_inr >= self.max_cost_inr and not self.exhausted:
            self.exhausted = "cost"  # work already done is kept; the next step is refused

    def summary(self) -> dict[str, object]:
        return {"steps": self.steps, "seconds": round(self.elapsed(), 2), "cost_inr": round(self.cost_inr, 2),
                "exhausted": self.exhausted}
