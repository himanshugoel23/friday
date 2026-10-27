# ruff: noqa: E501
"""Routes of the private browser, mounted by ``create_app`` ONLY when the browser is switched on:

* ``/live/*``                    the live view and takeover pages (``LiveViewHttp``, link token only)
* ``/connectors/otp/{token}``    the one-time page for the LOGIN code (``connectors_otp``)
* ``/connectors/credentials/..`` the one-time page to save a website login (needs saved logins ON)
* ``/connectors/qr/{token}.png`` the payment QR image (short-lived, unguessable token)
* ``/ride/code/{token}``        the one-time page that shows the ride-start code (POST reveals)

No route here needs the admin token: each is guarded by its own single-use / expiring token and
answers 404 for anything else.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

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

    @router.get("/ride/code/{token}")
    async def ride_code_page(token: str) -> Response:
        """GET only shows a button: a link preview must not use up the one-time code."""
        return _html(
            "<h2>Ride-start code</h2><p>Open this only when your driver has arrived and asks for "
            "the code. It is shown once.</p><form method='post'><button type='submit' "
            "style='font-size:18px;padding:12px 20px;width:100%'>Show my code</button></form>")

    @router.post("/ride/code/{token}")
    async def ride_code_show(token: str, request: Request) -> Response:
        from html import escape

        from friday.connectors.sites.ride import DEFAULT_REVEAL

        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(status_code=403)
        code = DEFAULT_REVEAL.take(token)
        if code is None:
            raise HTTPException(status_code=404)
        return _html(f"<h2>Your ride-start code</h2><p style='font-size:40px;letter-spacing:.2em'>"
                     f"{escape(code)}</p><p>Tell it to the driver only. This page will not show it "
                     "again.</p>")

    return router


_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Robots-Tag": "noindex",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}


def _html(body: str) -> Response:
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>Friday</title></head><body style='font:17px system-ui;max-width:440px;"
            f"margin:auto;padding:20px'>{body}</body></html>")
    return Response(page, media_type="text/html; charset=utf-8", headers=_HEADERS)


def mount_browser(app: FastAPI, stack: Any) -> None:
    """Mount every browser route on ``app`` (the live view at ``/live``, the pages under
    ``/connectors``)."""
    app.include_router(browser_router(stack))
    app.include_router(otp_router(stack.otp_tokens, stack.otp), prefix="/connectors")
    if stack.credentials is not None:
        app.include_router(
            credentials_router(stack.cred_tokens, stack.credentials.vault), prefix="/connectors")
