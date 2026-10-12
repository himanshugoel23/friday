"""Step agents behind a Protocol, plus a configurable fake for tests and ``friday pm-sim``.

The PM hands each step a ``StepContext`` (structured fields only: never script text) and reads
only the typed ``StepResult``. Adapters to the real scouting / quotes / voice code implement
``StepAgents`` elsewhere; the PM never imports them.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

STEP_NAMES = [
    "locate", "search", "filter", "reviews", "rank", "shortlist", "consent", "calls",
    "collect", "compare", "report",
]


class StepContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    step: str
    bucket: str
    category: str
    slots: dict[str, Any]
    radius_km: float
    hard_max_km: float
    n_vendors: int
    outputs: dict[str, Any] = Field(default_factory=dict)  # earlier steps' typed data
    vendor: dict[str, Any] | None = None                   # only for per-vendor "calls"
    user_answer: str | None = None                         # reply to a step_question
    language: str = "en"


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # ok | empty | failed | needs_user
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    question: str | None = None  # needs_user: the question to relay (user-facing text)


@runtime_checkable
class StepAgents(Protocol):
    async def run(self, step: str, ctx: StepContext) -> StepResult: ...


class FakeStepAgents:
    """A tiny pretend world. ``vendors`` have a distance; search/filter honour ``ctx.radius_km``.

    * ``overrides[step]`` is a list of StepResults consumed first (to inject failures).
    * ``pickup[vendor_id]`` False -> that vendor does not answer.
    * ``prices[vendor_id]`` quote price in INR.
    """

    def __init__(self, vendors: list[dict] | None = None, *, pickup: dict[str, bool] | None = None,
                 prices: dict[str, int] | None = None,
                 overrides: dict[str, list[StepResult]] | None = None) -> None:
        self.vendors = vendors if vendors is not None else [
            {"id": "v1", "name": "Glow Studio", "distance_km": 1.4, "rating": 4.6},
            {"id": "v2", "name": "Style Hub", "distance_km": 2.9, "rating": 4.4},
            {"id": "v3", "name": "Urban Cuts", "distance_km": 4.2, "rating": 4.5},
            {"id": "v4", "name": "Trim Time", "distance_km": 4.8, "rating": 4.1},
        ]
        self.pickup = pickup or {}
        self.prices = prices or {}
        self.overrides = {k: list(v) for k, v in (overrides or {}).items()}
        self.calls: list[tuple[str, str | None]] = []  # (step, vendor id) in order

    def _in_range(self, ctx: StepContext) -> list[dict]:
        return sorted((v for v in self.vendors if v["distance_km"] <= ctx.radius_km),
                      key=lambda v: v["distance_km"])

    async def run(self, step: str, ctx: StepContext) -> StepResult:
        self.calls.append((step, ctx.vendor["id"] if ctx.vendor else None))
        queue = self.overrides.get(step)
        if queue:
            return queue.pop(0)
        if step == "locate":
            return StepResult(status="ok", data={"lat": 28.45, "lng": 77.03})
        if step in ("search", "filter"):
            found = self._in_range(ctx)
            if not found:
                return StepResult(status="empty", reason="no_vendors_in_range")
            return StepResult(status="ok", data={"count": len(found)})
        if step in ("reviews", "rank"):
            return StepResult(status="ok", data={})
        if step == "shortlist":
            found = self._in_range(ctx)[: ctx.n_vendors + 2]
            if not found:
                return StepResult(status="empty", reason="no_vendors_in_range")
            return StepResult(status="ok", data={"vendors": found})
        if step == "consent":  # the safety gate (allow-list, call hours...), not the user's yes
            return StepResult(status="ok", data={"approved": True})
        if step == "calls":
            vid = ctx.vendor["id"] if ctx.vendor else ""
            if not self.pickup.get(vid, True):
                return StepResult(status="failed", reason="no_pickup")
            return StepResult(status="ok", data={"vendor_id": vid,
                                                 "price_inr": self.prices.get(vid, 700)})
        if step == "collect":
            return StepResult(status="ok", data={"quotes": [
                {"vendor_id": r["vendor_id"], "price_inr": r.get("price_inr")}
                for r in ctx.outputs.get("calls", []) if r.get("outcome") == "ok"]})
        if step == "compare":
            return StepResult(status="ok", data={"best": None})
        if step == "report":
            return StepResult(status="ok", data={"message": "Report: results are ready."})
        return StepResult(status="failed", reason=f"unknown step {step}")
