"""Admin endpoints for the quality loop (mounted by ``admin_router``; same admin token).

  POST /admin/quality/rating   {"call_id": "...", "rating": 1-5 | "up" | "down"}
  GET  /admin/quality/calls    recent stored calls: ids, metadata, labels, rating (NO transcripts)

Transcripts are read only with ``friday review show`` (needs database access)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from friday.quality.store import TranscriptStore


class RatingIn(BaseModel):
    call_id: str
    rating: int | str


def add_quality_routes(router: APIRouter, c: Any, require_admin: Any) -> None:
    from fastapi import Depends

    @router.post("/quality/rating", dependencies=[Depends(require_admin)])
    async def post_rating(body: RatingIn) -> dict[str, Any]:
        try:
            ok = await TranscriptStore.from_container(c).record_rating(body.call_id, body.rating)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        if not ok:
            raise HTTPException(status_code=404, detail="no stored call with that id")
        return {"ok": True}

    @router.get("/quality/calls", dependencies=[Depends(require_admin)])
    async def list_calls(limit: int = 20) -> dict[str, Any]:
        calls = await TranscriptStore.from_container(c).recent(max(1, min(limit, 200)))
        return {
            "calls": [
                {
                    "call_id": x.call_id,
                    "stored_at": x.stored_at.isoformat(),
                    "expires_at": x.expires_at.isoformat(),
                    "meta": x.meta,
                    "labels": x.labels,
                    "rating": x.rating,
                }
                for x in calls
            ]
        }
