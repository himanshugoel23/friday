"""Ops/admin endpoints (admin-only; SECURITY-28, NP-5).

Auth: ``Authorization: Bearer <token>``. The token is ``FRIDAY_ADMIN_TOKEN`` when set;
in dev (not live) it falls back to a key derived from the app secret so local tools
work; in live mode with no explicit token the admin routes answer 404 (disabled).

  GET /admin/health    component availability, queue depth, dead letters
  GET /admin/numbers   caller-ID pool dashboard (health / volume / status per number)

Pilot profile ONLY (FRIDAY_PROFILE=pilot; the routes do not exist otherwise):
  POST /admin/livecall       place ONE short test call (same rules as ``friday livecall``)
  GET  /admin/livecall/last  summary of the last test call made by this process
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from friday.core.container import FACTORIES, ComponentNotAvailable, Container
from friday.core.logging import mask_phone
from friday.core.models import FridayNumber
from friday.pilot import HARD_MAX_SECONDS, LiveCallRefused, place_test_call


class LiveCallIn(BaseModel):
    to: str
    goal: str | None = Field(default=None, max_length=1000)
    max_seconds: int = 180


def admin_token(settings: Any) -> str | None:
    explicit = os.environ.get("FRIDAY_ADMIN_TOKEN")
    if explicit:
        return explicit
    if settings.is_live:
        return None
    return settings.derived_key("admin_api").hex()


def admin_router(c: Container) -> APIRouter:
    router = APIRouter(tags=["admin"])

    async def require_admin(request: Request) -> None:
        token = admin_token(c.settings)
        if token is None:
            raise HTTPException(status_code=404)  # disabled: don't reveal the route
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="admin token required")

    @router.get("/health", dependencies=[Depends(require_admin)])
    async def admin_health() -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": "ok",
            "mode": c.settings.mode,
            "components": {name: c.is_available(name) for name in FACTORIES},
        }
        try:
            queue = c.get("job_queue")
            out["queue_depth"] = await queue.depth()
            dead = getattr(queue, "dead_count", None)
            out["dead_letters"] = await dead() if dead else None
        except ComponentNotAvailable:
            pass
        return out

    @router.get("/numbers", dependencies=[Depends(require_admin)])
    async def numbers() -> dict[str, Any]:
        now = c.clock.now()
        pool = None
        with contextlib.suppress(ComponentNotAvailable):
            pool = c.get("number_pool")
        listed: list[FridayNumber]
        if pool is not None:
            listed = await pool.list_numbers()
        else:
            listed = await c.repos.numbers.list()
        rows = []
        for n in listed:
            day = await c.repos.numbers.count_outcomes(n.phone, since=now - timedelta(days=1))
            hour = await c.repos.numbers.count_outcomes(n.phone, since=now - timedelta(hours=1))
            rows.append(
                {
                    "number": mask_phone(n.phone),
                    "provider": n.provider,
                    "city": n.city,
                    "circle": n.circle,
                    "status": n.status.value,
                    "warmup_day": n.warmup_day,
                    "cooldowns": n.cooldowns,
                    "cooling_until": n.cooling_until.isoformat() if n.cooling_until else None,
                    "calls_1h": hour,
                    "calls_24h": day,
                    "businesses": await c.repos.numbers.assignments_for(n.phone),
                    "health": {
                        "score": n.health.score,
                        "answer_rate": round(n.health.answer_rate, 3),
                        "short_call_rate": round(n.health.short_call_rate, 3),
                        "dnc_requests": n.health.dnc_requests,
                        "blocks": n.health.blocks,
                        "spam_labelled": n.health.spam_labelled,
                    },
                }
            )
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {"numbers": rows, "totals": {"count": len(rows), "by_status": by_status}}

    if c.settings.is_pilot:
        _add_livecall_routes(router, c, require_admin)
    return router


def _add_livecall_routes(router: APIRouter, c: Container, require_admin: Any) -> None:
    state: dict[str, Any] = {"last": None, "busy": False}

    @router.post("/livecall", dependencies=[Depends(require_admin)])
    async def livecall(body: LiveCallIn) -> dict[str, Any]:
        if state["busy"]:  # one call at a time, even before the lock file is taken
            raise HTTPException(status_code=409, detail="a test call is already in progress")
        if body.max_seconds > HARD_MAX_SECONDS:
            raise HTTPException(status_code=422, detail=f"max_seconds is at most {HARD_MAX_SECONDS}")
        state["busy"] = True

        async def go() -> dict[str, Any]:
            try:
                summary = await place_test_call(
                    c, body.to, goal=body.goal, max_seconds=body.max_seconds
                )
                state["last"] = {**summary, "finished_at": c.clock.now().isoformat()}
                return summary
            finally:
                state["busy"] = False

        task = asyncio.create_task(go())  # survives a dropped HTTP connection
        try:
            return await asyncio.shield(task)
        except LiveCallRefused as e:
            raise HTTPException(status_code=e.status, detail=e.reasons) from None

    @router.get("/livecall/last", dependencies=[Depends(require_admin)])
    async def livecall_last() -> dict[str, Any]:
        return {"in_progress": state["busy"], "last": state["last"]}
