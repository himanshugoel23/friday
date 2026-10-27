"""Secure one-time page for the LOGIN code: GET/POST /connectors/otp/{token}.

The founder types the code Zomato sent HIM; it goes straight into ``OneTimeOtpChannel`` (memory,
single use) and from there only into the browser's login field. It is never echoed back, logged,
put in a URL, or shown to a model. Payment codes / PINs / cards are never asked for here.

Safety: the token is the only credential (unknown / expired / used -> 404); POST only changes
state (GET has no side effects); a cross-site ``Origin`` is refused; 5 attempts per token, then
it is burned; every response is ``no-store``, noindex, no referrer, with a strict CSP; the body
is read with a small size cap and parsed by hand (no form library, nothing logged).
"""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from friday.api.page_security import PageLimiter, client_key, same_site
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry

_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
}
_MAX_BODY = 256
_CSS = (
    "body{font:17px system-ui;margin:0;padding:20px;max-width:440px;margin:auto;line-height:1.45}"
    "input{font-size:28px;letter-spacing:.3em;width:100%;box-sizing:border-box;padding:10px;"
    "margin:14px 0}button{font-size:18px;padding:12px 20px;width:100%}"
    ".err{color:#b00020}small{color:#555}"
)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=_HEADERS)


def _form(hint: str, error: str = "") -> str:
    where = f" ending <b>{escape(hint)}</b>" if hint else ""
    err = f'<p class="err">{escape(error)}</p>' if error else ""
    return (
        "<h2>Login code</h2>"
        f"<p>Enter the login code Zomato just sent to your phone{where}. "
        "Friday uses it once, never stores or logs it, and never asks for payment codes.</p>"
        f"{err}"
        "<form method='post' autocomplete='off'>"
        "<input name='code' type='text' inputmode='numeric' pattern='[0-9]*' maxlength='8' "
        "autocomplete='one-time-code' autofocus required aria-label='Login code'>"
        "<button type='submit'>Send code to Friday</button></form>"
        "<p><small>Do not enter a bank, card or payment code here.</small></p>"
    )


def otp_router(tokens: OtpTokenRegistry, channel: OneTimeOtpChannel,
               limiter: PageLimiter | None = None) -> APIRouter:
    router = APIRouter(tags=["connectors"])
    limiter = limiter or PageLimiter()

    def gate(request: Request) -> str:
        key = client_key(request)
        if not limiter.allow(key):
            raise HTTPException(status_code=429, headers={"Retry-After": "600", **_HEADERS})
        return key

    @router.get("/otp/{token}")
    async def show(token: str, request: Request) -> HTMLResponse:
        key = gate(request)
        entry = tokens.get(token)
        if entry is None:
            limiter.miss(key)
            raise HTTPException(status_code=404)
        return _page("Login code", _form(entry.phone_hint))

    @router.post("/otp/{token}")
    async def submit(token: str, request: Request) -> HTMLResponse:
        key = gate(request)
        entry = tokens.get(token)
        if entry is None:
            limiter.miss(key)
            raise HTTPException(status_code=404)
        if not same_site(request.headers):
            raise HTTPException(status_code=403)  # cross-site form post
        entry.attempts += 1
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > _MAX_BODY:
                raise HTTPException(status_code=413)
        form = parse_qs(raw.decode("utf-8", "ignore"), keep_blank_values=True)
        code = (form.get("code") or [""])[0]
        try:
            channel.submit(entry.task_id, code)
        except ValueError:
            code = ""
            if entry.attempts >= tokens.max_attempts:
                tokens.revoke(token)  # burned: 5 tries per link
                return _page("Too many tries", "<h2>Too many tries</h2><p>This link is now "
                             "closed. Ask Friday for a new one.</p>", 429)
            return _page("Login code", _form(
                entry.phone_hint, "That did not look like a login code (4 to 8 digits)."), 400)
        code = ""
        entry.used = True
        tokens.revoke(token)
        return _page("Done", "<h2>Done</h2><p>Thank you. Friday has the code and will use it "
                     "once. You can close this page.</p>")

    return router
