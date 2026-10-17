"""Watch pages for browser runs: GET /connectors/watch/{token}[...] (token = the only credential).

Unknown, expired or revoked tokens answer 404 (no hint which). Responses are no-store, noindex and
send no referrer. Read-only: the page accepts no input (takeover is a later, separate feature).
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from friday.connectors.report import render_watch
from friday.connectors.watch import WatchEntry, WatchRegistry

_BLANK = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_HEADERS = {
    "Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer",
}


def watch_router(
    registry: WatchRegistry, require_admin: Callable[..., Any] | None = None
) -> APIRouter:
    router = APIRouter(tags=["connectors"])

    def entry(token: str) -> WatchEntry:
        e = registry.get(token)
        if e is None:
            raise HTTPException(status_code=404)
        return e

    @router.get("/watch/{token}")
    async def page(token: str) -> HTMLResponse:
        return HTMLResponse(render_watch(token, entry(token).recorder), headers=_HEADERS)

    @router.get("/watch/{token}/state.json")
    async def state(token: str) -> JSONResponse:
        rec = entry(token).recorder
        return JSONResponse({"done": rec.done, "result": rec.result,
                             "steps": [s.public() for s in rec.steps]}, headers=_HEADERS)

    @router.get("/watch/{token}/latest.png")
    async def latest(token: str) -> Response:
        png = entry(token).recorder.latest_screenshot() or _BLANK
        return Response(png, media_type="image/png", headers=_HEADERS)

    @router.get("/watch/{token}/step/{n}.png")
    async def step_png(token: str, n: int) -> Response:
        steps = entry(token).recorder.steps
        if not 1 <= n <= len(steps) or not steps[n - 1].screenshot:
            raise HTTPException(status_code=404)
        return Response(steps[n - 1].screenshot, media_type="image/png", headers=_HEADERS)

    @router.get("/watch/{token}/trace.zip")
    async def trace(token: str) -> Response:
        path = entry(token).trace_path
        if not path or not await asyncio.to_thread(Path(path).is_file):
            raise HTTPException(status_code=404, detail="no trace for this run")
        return FileResponse(path, media_type="application/zip", filename="trace.zip",
                            headers=_HEADERS)

    if require_admin is not None:

        @router.post("/admin/revoke/{token}", dependencies=[Depends(require_admin)])
        async def revoke(token: str) -> dict[str, bool]:
            return {"revoked": registry.revoke(token)}

    return router
