# ruff: noqa: E501
"""Routes of the private browser, mounted by ``create_app`` ONLY when the browser is switched on:

* ``/live/*``                    the live view and takeover pages (``LiveViewHttp``, link token only)
* ``/connectors/otp/{token}``    the one-time page for the LOGIN code (``connectors_otp``)
* ``/connectors/credentials/..`` the one-time page to save a website login (needs saved logins ON)
* ``/connectors/qr/{token}.png`` the payment QR image (short-lived, unguessable token)

No route here needs the admin token: each is guarded by its own single-use / expiring token and
answers 404 for anything else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from friday.api.connectors_credentials import credentials_router
from friday.api.connectors_otp import otp_router


def browser_router(stack: Any) -> APIRouter:
    router = APIRouter(tags=["browser"])

    @router.get("/live/{rest:path}")
    @router.post("/live/{rest:path}")
    async def live(rest: str, request: Request) -> Response:
        body = await request.body() if request.method == "POST" else b""
        if len(body) > 4096:
            raise HTTPException(status_code=413)
        r = await stack.live_http.handle(request.method, f"/live/{rest}", body)
        return Response(r.body, status_code=r.status, media_type=r.content_type, headers=r.headers)

    @router.get("/connectors/qr/{name}")
    async def qr(name: str) -> Response:
        png = stack.qr.get(name.removesuffix(".png"))
        if png is None:
            raise HTTPException(status_code=404)
        return Response(png, media_type="image/png", headers={
            "Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})

    return router


def mount_browser(app: FastAPI, stack: Any) -> None:
    """Mount every browser route on ``app`` (the live view at ``/live``, the pages under
    ``/connectors``)."""
    app.include_router(browser_router(stack))
    app.include_router(otp_router(stack.otp_tokens, stack.otp), prefix="/connectors")
    if stack.credentials is not None:
        app.include_router(
            credentials_router(stack.cred_tokens, stack.credentials.vault), prefix="/connectors")
