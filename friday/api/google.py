"""Google connector routes (mounted at ``/google`` by ``create_app``).

  POST /google/connect          {user_id} -> {link, expires_at}   (internal: admin bearer token)
  GET  /google/consent/{state}  Friday's consent page (copy: friday.google.consent_copy)
  GET  /google/callback         Google redirects here with ``code`` + ``state``
  POST /google/disconnect       {user_id} -> {disconnected, revoked}   (internal)
  GET  /google/status?user_id=  connected, scopes, masked email         (internal)

Who calls what: Friday's own backend (the WhatsApp pipeline, after it has recognised the user and,
where needed, checked the PIN) calls connect/status/disconnect with the internal bearer token.
The USER only ever opens the single-use link (consent page) and Google's redirect (callback); the
state in that link is signed, bound to the user, expires in 10 minutes and works once.

Responses never contain a token, an authorisation code or a state: pages are no-store, noindex and
send no referrer; errors say a short reason only.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from friday.core.container import Container
from friday.core.logging import get_logger
from friday.core.models import UserStatus
from friday.google import consent_copy as copy
from friday.google.oauth import (
    GoogleError,
    GoogleOAuth,
    InvalidState,
    NotConfigured,
    ScopeMissing,
)

log = get_logger(__name__)

_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
}
_CSS = (
    "body{font:17px system-ui;max-width:460px;margin:auto;padding:20px;line-height:1.45}"
    "li{margin:8px 0}.btn{display:block;text-align:center;background:#1a73e8;color:#fff;"
    "padding:14px;border-radius:8px;text-decoration:none;font-size:18px}small{color:#555}"
)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=_HEADERS)


def _message(title: str, body: str, status: int = 200) -> HTMLResponse:
    return _page(title, f"<h2>{escape(title)}</h2><p>{escape(body)}</p>", status)


class UserIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)


def google_router(
    c: Container, require_internal: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(tags=["google"])

    def oauth(request: Request) -> GoogleOAuth:
        http = getattr(request.app.state, "google_http_factory", None)
        return GoogleOAuth(c.settings, c.repos.google, clock=c.clock, http=http)

    async def known_user(user_id: str) -> None:
        user = await c.repos.users.get(user_id)
        if user is None or user.status == UserStatus.DELETED:
            raise HTTPException(status_code=404, detail="unknown user")

    @router.post("/connect", dependencies=[Depends(require_internal)])
    async def connect(body: UserIn, request: Request) -> dict[str, str]:
        await known_user(body.user_id)
        try:
            start = await oauth(request).start(body.user_id)
        except NotConfigured:
            raise HTTPException(status_code=503, detail="google connector not configured") from None
        return {"link": start.link, "expires_at": start.expires_at.isoformat()}

    @router.get("/consent/{state}")
    async def consent(state: str, request: Request) -> HTMLResponse:
        o = oauth(request)
        try:
            url = await o.consent_url(state)
        except NotConfigured:
            return _message("Not available", "This feature is not switched on yet.", 503)
        if url is None:
            return _message(copy.EXPIRED_TITLE, copy.EXPIRED_BODY, 404)
        return _page(
            copy.TITLE,
            copy.consent_body_html(url, gmail_enabled=c.settings.google_gmail_enabled),
        )

    @router.get("/callback")
    async def callback(request: Request) -> HTMLResponse:
        q = request.query_params
        state, code, error = q.get("state", ""), q.get("code", ""), q.get("error")
        o = oauth(request)
        try:
            if error or not code:
                # The user declined (or Google refused): burn the attempt, save nothing.
                try:
                    user_id, nonce = o.parse_state(state)
                    await o.repo.consume_state(user_id, nonce)
                except InvalidState:
                    pass
                return _message(copy.DENIED_TITLE, copy.DENIED_BODY, 400)
            await o.handle_callback(state, code)
        except NotConfigured:
            return _message("Not available", "This feature is not switched on yet.", 503)
        except InvalidState:
            return _message(copy.EXPIRED_TITLE, copy.EXPIRED_BODY, 400)
        except ScopeMissing:
            return _message(copy.DENIED_TITLE, copy.CALENDAR_REQUIRED_BODY, 400)
        except GoogleError as e:
            log.warning("google callback failed reason=%s", e.code)
            return _message(copy.DENIED_TITLE, copy.DENIED_BODY, 502)
        return _message(copy.DONE_TITLE, copy.DONE_BODY)

    @router.post("/disconnect", dependencies=[Depends(require_internal)])
    async def disconnect(body: UserIn, request: Request) -> dict[str, bool]:
        res = await oauth(request).disconnect(body.user_id)
        return {"disconnected": res.deleted, "revoked": res.revoked}

    @router.get("/status", dependencies=[Depends(require_internal)])
    async def status(user_id: str, request: Request) -> dict[str, Any]:
        st = await oauth(request).status(user_id)
        return {
            "connected": st.connected,
            "status": st.status,
            "scopes": st.scopes,
            "email_masked": st.email_masked,
            "gmail": st.gmail,
        }

    return router
