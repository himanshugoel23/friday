"""Secure one-time page to save a website login: GET/POST /connectors/credentials/{token}.

The user types the site's username and password HERE, never in WhatsApp. They go straight into the
encrypted vault (``CredentialVault``) and are never echoed back, logged, put in a URL, shown to a
model, or kept anywhere else.

Same hardening as the OTP page: the token is the only credential (unknown / expired / used -> 404);
GET has no side effects; a cross-site ``Origin`` is refused; 5 attempts per token; ``no-store``,
noindex, no referrer, strict CSP; the body is size-capped and parsed by hand; explicit consent
box required. Banks, UPI, cards and IRCTC are refused by the vault.
Wording on this page is PENDING founder approval (docs/CREDENTIAL_VAULT.md).
"""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from friday.connectors.session.credential_tokens import CredentialTokenRegistry
from friday.connectors.session.credentials import CredentialError, CredentialVault

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
_MAX_BODY = 2048
_CSS = (
    "body{font:17px system-ui;margin:0;padding:20px;max-width:440px;margin:auto;line-height:1.45}"
    "input[type=text],input[type=password]{font-size:20px;width:100%;box-sizing:border-box;"
    "padding:10px;margin:8px 0 14px}button{font-size:18px;padding:12px 20px;width:100%}"
    ".err{color:#b00020}small{color:#555}label{display:block}"
)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=_HEADERS)


def _form(site: str, error: str = "") -> str:
    err = f'<p class="err">{escape(error)}</p>' if error else ""
    return (
        f"<h2>Save your {escape(site)} login</h2>"
        "<p>Friday can log in to this site for you later. Your login is stored encrypted, "
        "only used on this site, never shown to anyone or any AI, and you can delete it any "
        "time by telling Friday \"forget my logins\".</p>"
        f"{err}"
        "<form method='post' autocomplete='off'>"
        "<label>Username or phone<input name='u' type='text' maxlength='256' "
        "autocomplete='off' required></label>"
        "<label>Password<input name='p' type='password' maxlength='256' "
        "autocomplete='new-password' required></label>"
        "<label><input name='c' type='checkbox' value='1' required> I agree Friday may save and "
        "use this login for me on this site.</label><br>"
        "<button type='submit'>Save login</button></form>"
        "<p><small>Never enter a bank, card, UPI or payment code or password here.</small></p>"
    )


def credentials_router(tokens: CredentialTokenRegistry, vault: CredentialVault) -> APIRouter:
    router = APIRouter(tags=["connectors"])

    @router.get("/credentials/{token}")
    async def show(token: str) -> HTMLResponse:
        link = tokens.get(token)
        if link is None:
            raise HTTPException(status_code=404)
        return _page("Save login", _form(link.site))

    @router.post("/credentials/{token}")
    async def submit(token: str, request: Request) -> HTMLResponse:
        link = tokens.get(token)
        if link is None:
            raise HTTPException(status_code=404)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(status_code=403)  # cross-site form post
        link.attempts += 1
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > _MAX_BODY:
                raise HTTPException(status_code=413)
        form = parse_qs(raw.decode("utf-8", "ignore"), keep_blank_values=True)
        u = (form.get("u") or [""])[0]
        p = (form.get("p") or [""])[0]
        consent = (form.get("c") or [""])[0] == "1"
        del form, raw
        try:
            vault.save(link.user_id, link.site, u, p, hosts=link.hosts, consent=consent)
        except CredentialError as e:
            u = p = ""
            if link.attempts >= tokens.max_attempts:
                tokens.revoke(token)
                return _page("Too many tries", "<h2>Too many tries</h2><p>This link is now "
                             "closed. Ask Friday for a new one.</p>", 429)
            return _page("Save login", _form(link.site, str(e).capitalize() + "."), 400)
        u = p = ""
        link.used = True
        tokens.revoke(token)
        return _page("Done", "<h2>Saved</h2><p>Friday has your login and will use it only on "
                     "this site. You can close this page.</p>")

    return router
