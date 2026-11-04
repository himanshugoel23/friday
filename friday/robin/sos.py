# ruff: noqa: E501
"""SOS: the parent presses the help button (widget press-and-hold, called by the device API) or phones the number.

Robin rings the child, WhatsApps the child and the second contact (location only if consented), logs, and
repeats on the ladder (alerts.plan_for 'sos'). One-tap 'call 112' is SHOWN to the parent (``show_112``); Robin
NEVER dials 112 itself in Phase 1 (the CallGate also refuses emergency numbers). An SOS works even after the
parent paused Robin: the parent pressed it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.robin.alerts import AlertEngine, AlertResult, RobinAlert
from friday.robin.context import Ctx
from friday.robin.models import Step, Tier


@dataclass
class SosResult:
    alert: AlertResult
    show_112: bool = True  # the app/widget shows a one-tap 'call 112' button; Robin does not dial it
    parent_lines: list[str] = field(default_factory=list)


class SosService:
    def __init__(self, ctx: Ctx, alerts: AlertEngine) -> None:
        self.ctx, self.alerts = ctx, alerts

    async def trigger(self, parent_member_id: str, source: str = "app", location: tuple[float, float] | None = None) -> SosResult:
        parent = await self.ctx.store.get_member(parent_member_id)
        if parent is None:
            return SosResult(AlertResult(False, "no_such_parent"))
        fam = await self.ctx.store.get_family(parent.family_id)
        label = fam.parent_label if fam else "Parent"
        how = "pressed the help button" if source == "app" else f"phoned {self.ctx.brand} for help"
        bucket = int(self.ctx.clock.now().timestamp() // 300)
        res = await self.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.EMERGENCY, scenario="sos", why=f"{label} {how}", dedupe_key=f"sos:{parent.id}:{bucket}", location=location))
        return SosResult(res, True, ["sos.parent", "sos.ask", "sos.noted"] if source == "call" else [])

    async def call_steps(self, parent_member_id: str) -> list[Step]:
        """What Robin says when the parent phones in for help (the voice front door plays these)."""
        parent = await self.ctx.store.get_member(parent_member_id)
        fam = await self.ctx.store.get_family(parent.family_id) if parent else None
        if fam is None:
            return []
        slots = await self.ctx.slots(fam)
        return [Step(line="sos.parent", slots=slots), Step(line="sos.ask", slots=slots, expect="free"), Step(line="sos.noted", slots=slots)]
