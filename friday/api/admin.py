"""Ops/admin endpoints (admin-only; SECURITY-28, NP-5).

Auth: ``Authorization: Bearer <token>``. The token is ``FRIDAY_ADMIN_TOKEN`` when set;
in dev (not live) it falls back to a key derived from the app secret so local tools
work; in live mode with no explicit token the admin routes answer 404 (disabled).

  GET /admin/health    component availability, queue depth, dead letters
  GET /admin/numbers   caller-ID pool dashboard (health / volume / status per number)
"""

from __future__ import annotations

import hmac
import os
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from friday.core.container import FACTORIES, ComponentNotAvailable, Container
from friday.core.logging import mask_phone
from friday.core.models import FridayNumber


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
        try:
            pool = c.get("number_pool")
        except ComponentNotAvailable:
            pass
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

    return router
