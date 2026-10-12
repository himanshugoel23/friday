"""Real step agents for the project manager: scouting + the engine's vendor calls.

``RealStepAgents`` implements ``StepAgents`` (friday/pm/steps.py). The PM still only sees typed
``StepResult``s; everything below is wiring to existing code, with the heavy parts injected
(``scout_fn``, ``resolve_fn``, ``placer``, ``policy``) so tests use fakes and nothing here opens
a network connection by itself. Phase 1: quote-only calls (no booking from the PM yet).

Vendor dict shape handed to the PM (JSON-safe, server side only):
``{id, name, phone, distance_km, rating, review_count, address, reasons}``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from friday.core.models import GeoPoint
from friday.pm.steps import StepContext, StepResult
from friday.scouting.models import ScoutRequest, ScoutResult

ScoutFn = Callable[[ScoutRequest], Awaitable[ScoutResult]]
ResolveFn = Callable[[str], Awaitable[GeoPoint | None]]
PolicyFn = Callable[[StepContext], Awaitable[tuple[bool, str]]]


@dataclass
class CallResult:
    finished: bool
    outcome: str | None = None  # quote | no_answer | failed | blocked | dnc | wrong_number | ...
    price_inr: int | None = None
    slots: list[str] = field(default_factory=list)


class Placer(Protocol):
    async def place(self, ctx: StepContext, vendor: dict[str, Any]) -> str: ...
    async def report(self, handle: str) -> CallResult: ...


# Reasons the PM relays; the words the USER sees are written by the PM/quotes copy, not here.
_FAIL_REASON = {
    "no_answer": "no_pickup", "failed": "no_pickup", "declined": "declined",
    "wrong_number": "wrong_number", "closed": "closed", "dnc": "dnc",
    "blocked": "blocked_by_policy",
    "no_slot": "no_slot", "price_too_high": "price_too_high",
}

REPORT_TEXT = {
    "en": {
        "head": "Quotes for {service}:",
        "line": "- {name}: Rs {price} ({km} km away{rating})",
        "best": "Lowest: {name} at Rs {price}.",
        "none": "I could not get a price from any of them. Want me to try others?",
    },
    "hinglish": {
        "head": "{service} ke quotes:",
        "line": "- {name}: Rs {price} ({km} km door{rating})",
        "best": "Sabse kam: {name}, Rs {price}.",
        "none": "Kisi ne price nahi bataya. Aur jagah try karun?",
    },
}


class RealStepAgents:
    def __init__(
        self,
        *,
        scout_fn: ScoutFn,
        resolve_fn: ResolveFn,
        placer: Placer,
        policy: PolicyFn | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_s: float = 5.0,
        call_timeout_s: float = 420.0,
    ) -> None:
        self.scout_fn = scout_fn
        self.resolve_fn = resolve_fn
        self.placer = placer
        self.policy = policy
        self.sleep = sleep
        self.poll_s = poll_s
        self.call_timeout_s = call_timeout_s

    async def run(self, step: str, ctx: StepContext) -> StepResult:
        fn = getattr(self, f"_{step}", None)
        if fn is None:
            return StepResult(status="failed", reason=f"unknown step {step}")
        return await fn(ctx)

    # ------------------------------------------------------------------ steps
    async def _locate(self, ctx: StepContext) -> StepResult:
        where = str(ctx.slots.get("where") or "").strip()
        if not where:
            return StepResult(status="needs_user", question="Which area should I look in?")
        try:
            pt = await self.resolve_fn(where)
        except Exception:  # noqa: BLE001
            return StepResult(status="failed", reason="geocode_error", retryable=True)
        if pt is None:
            return StepResult(
                status="needs_user", question="I could not find that place. Which area is it?"
            )
        return StepResult(status="ok", data={"lat": pt.lat, "lng": pt.lng, "area": where})

    async def _search(self, ctx: StepContext) -> StepResult:
        loc = ctx.outputs.get("locate") or {}
        services = [str(ctx.slots["service"])] if ctx.slots.get("service") else []
        req = ScoutRequest(
            category=ctx.category,
            area=str(loc.get("area") or ctx.slots.get("where") or ""),
            near=GeoPoint(lat=loc["lat"], lng=loc["lng"]) if "lat" in loc else None,
            services=services,
            radius_km=ctx.radius_km,
            top_n=ctx.n_vendors + 2,
        )
        try:
            res = await self.scout_fn(req)
        except Exception:  # noqa: BLE001
            return StepResult(status="failed", reason="scout_error", retryable=True)
        vendors = []
        for it in res.shortlist.items:
            c = it.place.candidate
            if it.beyond_default_radius or not c.phone:
                continue
            vendors.append({
                "id": c.place_id, "name": c.name, "phone": c.phone,
                "distance_km": it.distance_km, "rating": c.rating,
                "review_count": c.review_count, "address": c.address, "reasons": it.reasons[:3],
            })
        if not vendors:
            return StepResult(status="empty", reason="no_vendors_in_range")
        return StepResult(status="ok", data={"count": len(vendors), "vendors": vendors})

    async def _passthrough(self, ctx: StepContext) -> StepResult:  # filter/reviews/rank: in scout
        return StepResult(status="ok", data={})

    _filter = _reviews = _rank = _passthrough

    async def _shortlist(self, ctx: StepContext) -> StepResult:
        vendors = (ctx.outputs.get("search") or {}).get("vendors") or []
        if not vendors:
            return StepResult(status="empty", reason="no_vendors_in_range")
        return StepResult(status="ok", data={"vendors": vendors[: ctx.n_vendors + 2]})

    async def _consent(self, ctx: StepContext) -> StepResult:
        if self.policy is not None:
            ok, why = await self.policy(ctx)
            if not ok:
                return StepResult(status="failed", reason="blocked_by_policy", data={"why": why})
        return StepResult(status="ok", data={"approved": True})

    async def _calls(self, ctx: StepContext) -> StepResult:
        v = ctx.vendor or {}
        try:
            handle = await self.placer.place(ctx, v)
        except Exception:  # noqa: BLE001 - e.g. the engine refused (allow-list, kill switch)
            return StepResult(status="failed", reason="blocked_by_policy")
        waited = 0.0
        while True:
            rep = await self.placer.report(handle)
            if rep.finished:
                break
            if waited >= self.call_timeout_s:
                return StepResult(status="failed", reason="timeout")
            await self.sleep(self.poll_s)
            waited += self.poll_s
        if rep.outcome == "quote" and rep.price_inr is not None:
            return StepResult(status="ok", data={
                "vendor_id": v.get("id"), "price_inr": rep.price_inr, "slots": rep.slots})
        reason = _FAIL_REASON.get(rep.outcome or "failed", "no_pickup")
        return StepResult(status="failed", reason=reason)

    async def _collect(self, ctx: StepContext) -> StepResult:
        quotes = [
            {"vendor_id": r["vendor_id"], "price_inr": r.get("price_inr")}
            for r in ctx.outputs.get("calls", [])
            if r.get("outcome") == "ok"
        ]
        return StepResult(status="ok", data={"quotes": quotes})

    async def _compare(self, ctx: StepContext) -> StepResult:
        dist = {
            v["id"]: v.get("distance_km") or 0.0
            for v in (ctx.outputs.get("shortlist") or {}).get("vendors", [])
        }
        priced = [q for q in (ctx.outputs.get("collect") or {}).get("quotes", [])
                  if q.get("price_inr") is not None]
        best = min(priced, key=lambda q: (q["price_inr"], dist.get(q["vendor_id"], 99)),
                   default=None)
        return StepResult(status="ok", data={"best": best["vendor_id"] if best else None})

    async def _report(self, ctx: StepContext) -> StepResult:
        t = REPORT_TEXT["en" if ctx.language == "en" else "hinglish"]
        vendors = {v["id"]: v for v in (ctx.outputs.get("shortlist") or {}).get("vendors", [])}
        quotes = [q for q in (ctx.outputs.get("collect") or {}).get("quotes", [])
                  if q.get("price_inr") is not None]
        if not quotes:
            return StepResult(status="ok", data={"message": t["none"]})
        lines = [t["head"].format(service=ctx.slots.get("service") or ctx.category)]
        for q in sorted(quotes, key=lambda q: q["price_inr"]):
            v = vendors.get(q["vendor_id"], {})
            rating = f", {v['rating']:g}*" if v.get("rating") else ""
            km = f"{v['distance_km']:.1f}" if v.get("distance_km") is not None else "?"
            lines.append(t["line"].format(
                name=v.get("name", "?"), price=int(q["price_inr"]), km=km, rating=rating))
        best_id = (ctx.outputs.get("compare") or {}).get("best")
        if best_id and best_id in vendors:
            bp = next(q["price_inr"] for q in quotes if q["vendor_id"] == best_id)
            lines.append(t["best"].format(name=vendors[best_id]["name"], price=int(bp)))
        return StepResult(status="ok", data={"message": "\n".join(lines)})


class EnginePlacer:
    """Places one vendor call through the quotes flow's engine adapter (EngineVendorCalls)."""

    def __init__(self, calls: Any, clock: Callable[[], Any]) -> None:
        self.calls = calls
        self.clock = clock

    async def place(self, ctx: StepContext, vendor: dict[str, Any]) -> str:
        from friday.quotes.models import Conv, Vendor

        conv = Conv(user_id=ctx.user_id or "user", category=ctx.category or "salon")
        if ctx.slots.get("service"):
            conv.slots.services = [str(ctx.slots["service"])]
        conv.slots.when_text = str(ctx.slots["when"]) if ctx.slots.get("when") else None
        v = Vendor(
            place_id=str(vendor["id"]), name=vendor["name"], phone=vendor.get("phone", ""),
            rating=vendor.get("rating"), review_count=vendor.get("review_count") or 0,
            distance_km=vendor.get("distance_km"), address=vendor.get("address"),
            category=ctx.category,
        )
        return await self.calls.place(conv, v, now=self.clock())

    async def report(self, handle: str) -> CallResult:
        rep = await self.calls.report(handle)
        if not rep.finished:
            return CallResult(finished=False)
        return CallResult(
            True, rep.outcome.value if rep.outcome else "failed", rep.price_inr, list(rep.slots)
        )
