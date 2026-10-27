# ruff: noqa: E501
"""Base of the new-site adapters. Same protocol as ``FoodAdapter`` / ``MovieAdapter``:
``prepare`` is read-only and builds the ``Proposal``; ``execute`` runs only after approval.

Extra, so BrowserFlow can drive them without guessing (shared-file wiring in docs/BROWSER_TRAIN_SHOP.md):
* ``missing(slots)``: the next slot the user must give before ``prepare`` (never invented).
* ``pending``: set whenever ``prepare`` returns ``Problem("need_choice" | "need_detail")``:
  ``{"slot", "kind", "text_key", "options"}`` so the flow asks the user (options are page labels,
  cleaned of instruction-like text).
* ``Proposal.details["read_only"]``: nothing to approve (track order, eRail info).
* ``Proposal.details["extra_approval"]``: a second, explicit approval line is required (waitlisted
  ticket, cancelling an order); ``execute`` does nothing until ``extra_approval_given`` is True.
"""

from __future__ import annotations

from typing import Any

from friday.connectors.contract import ItemQty
from friday.connectors.gate import Grant, Verdict
from friday.connectors.sites.adapters import (
    APPROVAL_TTL,
    ExecResult,
    Prepared,
    Problem,
    Proposal,
    RunCtx,
)
from friday.connectors.sites.safety import ExtendedGate


class ScriptedAdapter:
    key = site = use_case = site_name = ""
    required: tuple[str, ...] = ()
    gate_cls: type[ExtendedGate] = ExtendedGate

    def __init__(self, ctx: RunCtx, credentials: Any = None) -> None:
        self.ctx, self.gate = ctx, self.gate_cls(now=ctx.now)
        self.credentials = credentials or getattr(ctx, "credentials", None)
        self.pending: dict[str, Any] | None = None
        self.kit = self.make_kit()
        self.conn = self.make_conn()

    # ---- to override
    def make_kit(self) -> Any:
        raise NotImplementedError

    def make_conn(self) -> Any:
        raise NotImplementedError

    def missing(self, slots: dict[str, Any]) -> str | None:
        return next((s for s in self.required if not slots.get(s)), None)

    # ---- shared
    def flags(self) -> dict[str, bool]:
        return {"injection": self.kit.safety.injection_count > 0, "repaired": bool(self.kit.repairs.records)}

    def _kw(self) -> dict[str, Any]:
        c = self.ctx
        kw: dict[str, Any] = dict(base_url=c.base_url, task_id=c.task_id, otp_channel=c.otp,
                                  phone=c.profile.phone or None, on_code_wait=c.on_code_wait,
                                  otp_wait_s=c.otp_wait_s, poll_s=c.poll_s)
        if c.sleep:
            kw["sleep"] = c.sleep
        return kw

    def _grant(self, group: str, items: list[ItemQty], max_total: int) -> Grant:
        return Grant(task_id=self.ctx.task_id, connector=self.key, restaurant_id=group, items=items,
                     max_total_paise=max_total, expires_at=self.ctx.now() + APPROVAL_TTL)

    def _args(self, group: str, items: list[ItemQty]) -> dict[str, Any]:
        return {"task_id": self.ctx.task_id, "connector": self.key, "restaurant_id": group,
                "items": [i.model_dump() for i in items]}

    def _allowed(self, tool: str, args: dict[str, Any], grant: Grant) -> bool:
        return self.gate.decide(tool, args, [grant]) == Verdict.allow

    def _expires(self):  # noqa: ANN202
        return self.ctx.now() + APPROVAL_TTL

    def _need(self, kind: str, slot: str, text_key: str, what: str, options: list[str] | None = None) -> Prepared:
        """Stop and ask the user: a choice among page options, or a detail we must not guess."""
        self.pending = {"slot": slot, "kind": kind, "text_key": text_key, "options": list(options or [])}
        return Prepared(problem=Problem(kind, what))  # type: ignore[arg-type]

    def _reask(self, p: Proposal, reason: str, *, notes: dict[str, bool] | None = None,
               **update: Any) -> ExecResult:
        new = p.model_copy(update={"exact": True, "expires_at": self._expires(), **update})
        return ExecResult("reapprove", reason=reason, proposal=new, notes={**self.flags(), **(notes or {})})


__all__ = ["ScriptedAdapter"]
