"""Read-only update status for the small server: ``GET /ops-status/{token}`` (docs/AUTOUPDATE.md).

The auto-updater (deploy/autoupdate.sh) writes a plain-text report; this serves it so the developer
can read it without a console. Off unless FRIDAY_OPS_STATUS_TOKEN is set (16+ chars). The report
holds no secrets: git commit ids and migration/doctor lines only.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

_DEFAULT_FILE = "/opt/friday/var/autoupdate/status.txt"
_MAX_BYTES = 60_000


def _token() -> str:
    # The server's .env is read by pydantic only, not exported to the process: look in both places.
    env = os.environ.get("FRIDAY_OPS_STATUS_TOKEN")
    return env or str(dotenv_values(".env").get("FRIDAY_OPS_STATUS_TOKEN") or "")


def _read(path: Path) -> PlainTextResponse:
    try:
        data = path.read_bytes()[-_MAX_BYTES:]
    except OSError:
        return PlainTextResponse("no report yet\n")
    return PlainTextResponse(data.decode("utf-8", "replace"))


def _authorised(token: str) -> None:
    expected = _token()
    if len(expected) < 16 or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=404, detail="Not Found")


def ops_status_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{token}", response_class=PlainTextResponse)
    def status(token: str) -> PlainTextResponse:
        _authorised(token)
        return _read(Path(os.environ.get("FRIDAY_OPS_STATUS_FILE", _DEFAULT_FILE)))

    @router.get("/{token}/logs", response_class=PlainTextResponse)
    def logs(token: str) -> PlainTextResponse:
        _authorised(token)
        default = str(Path(_DEFAULT_FILE).with_name("logs.txt"))
        return _read(Path(os.environ.get("FRIDAY_OPS_LOGS_FILE", default)))

    @router.get("/{token}/calls", response_class=PlainTextResponse)
    async def calls(token: str, request: Request, n: int = 5) -> PlainTextResponse:
        _authorised(token)
        from friday.ops import callreview

        if not callreview.enabled():  # off by default: same 404 as a wrong token
            raise HTTPException(status_code=404, detail="Not Found")
        c = request.app.state.container
        return PlainTextResponse(await callreview.render_review(c.db, c.settings, n))

    @router.get("/{token}/bench", response_class=PlainTextResponse)
    def bench(token: str) -> PlainTextResponse:
        _authorised(token)
        from friday.bench import ops as bench_ops

        if not bench_ops.enabled():  # off by default: same 404 as a wrong token
            raise HTTPException(status_code=404, detail="Not Found")
        return _read(Path(bench_ops.report_path()))
    def _probe_store(request: Request) -> object | None:
        """The site MCP probe store, or None while FRIDAY_SITE_MCP_PROBE_ENABLED is off (then both routes are a plain 404)."""
        st = request.app.state.container.settings
        if not st.site_mcp_probe_enabled:
            return None
        from friday.sitemcp.wiring import store_for

        return store_for(st)

    @router.get("/{token}/probe", response_class=PlainTextResponse)
    def probe(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        store = _probe_store(request)
        if store is None:
            raise HTTPException(status_code=404, detail="Not Found")
        from friday.sitemcp.live import render_report

        return PlainTextResponse(render_report(store))  # type: ignore[arg-type]

    @router.get("/{token}/shot/{site}")
    def shot(token: str, site: str, request: Request) -> Response:
        """Last screenshot of a PUBLIC page for this site (never a logged-in page: the probe is anonymous only)."""
        _authorised(token)
        store = _probe_store(request)
        png = store.shot(site) if store is not None else None  # type: ignore[attr-defined]
        if png is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    return router
