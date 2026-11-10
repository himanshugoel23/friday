# ruff: noqa: E501
"""C3: the staff web console. Server-rendered HTML, no JavaScript, no external assets, nothing to download.

* every page is behind a session (password + one-time code, idle timeout); POSTs carry a CSRF token and are same-origin only
* one-screen request view: only what the errand needs; the phone number is masked; contact goes through the masked bridge
* every page carries a watermark with the staff id; no-store, no-frame, no-referrer, no-index; printing is blanked
* there is NO export, download, CSV or bulk route (an ``/export...`` path answers 404 and is audited)
All wording here is plain working text for staff; nothing is spoken to a user from this file.
"""

from __future__ import annotations

import hmac
from html import escape
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from friday.concierge.audit import AuditLog
from friday.concierge.auth import Sessions, can
from friday.concierge.desk import FALSE_ALARM_REASONS, OUTCOMES, DeskService
from friday.concierge.models import PROOF_KINDS
from friday.concierge.ports import StaffAccount
from friday.concierge.service import ESCALATE_REASONS, ConciergeService, DeskError
from friday.core.logging import get_logger

log = get_logger(__name__)
COOKIE = "rc_session"
MAX_FORM = 8192
HEADERS = {
    "Cache-Control": "no-store", "Pragma": "no-cache", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'; frame-ancestors 'none'",
}
_CSS = (
    "body{font:15px/1.4 system-ui,sans-serif;margin:0;background:#f6f6f4;color:#1b1b1b}header{background:#1b1b1b;color:#fff;padding:8px 16px;display:flex;gap:16px;align-items:center}"
    "header a{color:#fff}main{max-width:860px;margin:16px auto;padding:0 16px}table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #ddd;padding:6px 8px;text-align:left}"
    ".p-safety{color:#b00020;font-weight:700}.p-health{color:#a45a00;font-weight:700}.late{background:#ffe5e5}.card{background:#fff;border:1px solid #ddd;padding:12px 16px;margin:12px 0}"
    "input,select,textarea{font:inherit;padding:4px;margin:2px 0}button{font:inherit;padding:5px 12px}.msg{background:#fff3c4;padding:6px 10px}.muted{color:#666}"
    "@media print{body{display:none}}"
)


def _watermark(staff_id: str) -> str:
    sid = escape(staff_id or "")
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='260' height='140'><text x='10' y='90' transform='rotate(-25 130 70)' font-size='18' fill='rgba(0,0,0,0.09)' font-family='sans-serif'>{sid}</text></svg>"
    return "url(\"data:image/svg+xml;utf8," + svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23") + "\")"


def _page(title: str, body: str, *, staff_id: str = "", csrf: str = "", msg: str = "", nav: bool = True) -> HTMLResponse:
    wm = f"<div style='position:fixed;inset:0;pointer-events:none;z-index:9;background-image:{_watermark(staff_id)}'></div>" if staff_id else ""
    head = ""
    if nav and staff_id:
        head = (f"<header><b>Robin desk</b><a href='/concierge/'>Queue</a><a href='/concierge/desk'>Emergency desk</a><span class='muted' style='margin-left:auto;color:#ccc'>signed in as {escape(staff_id)}</span>"
                f"<form method='post' action='/concierge/logout' style='margin:0'><input type='hidden' name='csrf' value='{escape(csrf)}'><button>Sign out</button></form></header>")
    note = f"<p class='msg'>{escape(msg)}</p>" if msg else ""
    html = f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'><title>{escape(title)}</title><style>{_CSS}</style></head><body>{wm}{head}<main>{note}{body}</main></body></html>"
    return HTMLResponse(html, headers=HEADERS)


def _csrf_field(csrf: str) -> str:
    return f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"


async def _form(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > MAX_FORM:
        return {}
    return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # same-origin form posts from some browsers omit it; SameSite=Strict + the CSRF token cover that case
    host = request.headers.get("host", "")
    return origin.split("://", 1)[-1].rstrip("/") == host


def build_console(service: ConciergeService, desk: DeskService, sessions: Sessions, audit: AuditLog, *, secure_cookie: bool = True) -> APIRouter:  # noqa: C901
    r = APIRouter()

    def go(path: str, msg: str = "") -> RedirectResponse:
        return RedirectResponse(path + (f"?msg={quote(msg)}" if msg else ""), status_code=303, headers=HEADERS)

    async def auth(request: Request) -> tuple[Any, StaffAccount] | Response:
        tok = request.cookies.get(COOKIE)
        got = await sessions.get(tok)
        if got is None:
            if sessions.was_expired(tok):
                pass
            resp = go("/concierge/login", "Please sign in again.")
            resp.delete_cookie(COOKIE, path="/concierge")
            return resp
        return got

    async def post_auth(request: Request) -> tuple[Any, StaffAccount, dict[str, str]] | Response:
        if not _same_origin(request):
            return Response(status_code=403, headers=HEADERS)
        got = await auth(request)
        if isinstance(got, Response):
            return got
        form = await _form(request)
        if not hmac.compare_digest(form.get("csrf", ""), got[0].csrf):
            return Response("Bad form token.", status_code=403, headers=HEADERS)
        return got[0], got[1], form

    # ------------------------------------------------------------------ login / logout
    @r.get("/login")
    async def login_page(request: Request) -> HTMLResponse:
        msg = request.query_params.get("msg", "")[:80]
        body = ("<h2>Staff sign-in</h2><form method='post' action='/concierge/login' class='card' autocomplete='off'>"
                "<p><label>Staff id<br><input name='staff_id' maxlength='48' required></label></p>"
                "<p><label>Password<br><input name='password' type='password' maxlength='200' required></label></p>"
                "<p><label>One-time code<br><input name='code' inputmode='numeric' maxlength='10' required></label></p><button>Sign in</button></form>")
        return _page("Robin desk sign-in", body, msg=msg, nav=False)

    @r.post("/login")
    async def login(request: Request) -> Response:
        if not _same_origin(request):
            return Response(status_code=403, headers=HEADERS)
        f = await _form(request)
        res = await sessions.login(f.get("staff_id", ""), f.get("password", ""), f.get("code", ""))
        if res is None:
            await audit.record("unknown", "login_failed", "", attempts=1)  # who typed what is never logged
            return go("/concierge/login", "That did not work.")
        token, s = res
        await audit.record(s.staff_id, "login", "")
        resp = go("/concierge/")
        resp.set_cookie(COOKIE, token, httponly=True, secure=secure_cookie, samesite="strict", path="/concierge", max_age=None)
        return resp

    @r.post("/logout")
    async def logout(request: Request) -> Response:
        got = await post_auth(request)
        if isinstance(got, Response):
            return got
        s, _a, _f = got
        sessions.logout(request.cookies.get(COOKIE))
        await audit.record(s.staff_id, "logout", "")
        resp = go("/concierge/login", "Signed out.")
        resp.delete_cookie(COOKIE, path="/concierge")
        return resp

    # ------------------------------------------------------------------ queue
    @r.get("/")
    async def queue(request: Request) -> Response:
        got = await auth(request)
        if isinstance(got, Response):
            return got
        s, staff = got
        try:
            rows = await service.queue(staff)
        except DeskError:
            return _page("Not allowed", "<p>Your role cannot see the queue.</p>", staff_id=s.staff_id, csrf=s.csrf)
        trs = "".join(
            f"<tr class='{'late' if x.sla != 'ok' else ''}'><td class='p-{x.priority.value}'>{x.priority.value}</td><td>{escape(x.category)}</td><td>{x.status.value}</td>"
            f"<td>{escape(x.claimed_by or '-')}</td><td>{x.age_min} min</td><td>{x.sla.replace('_', ' ')}</td><td><a href='/concierge/r/{escape(x.id)}'>open</a></td></tr>"
            for x in rows)
        body = f"<h2>Requests ({len(rows)})</h2><table><tr><th>Priority</th><th>Kind</th><th>Status</th><th>Taken by</th><th>Age</th><th>Time limit</th><th></th></tr>{trs}</table>"
        return _page("Queue", body, staff_id=s.staff_id, csrf=s.csrf, msg=request.query_params.get("msg", "")[:80])

    # ------------------------------------------------------------------ one request, one screen
    @r.get("/r/{request_id}")
    async def request_page(request: Request, request_id: str) -> Response:
        got = await auth(request)
        if isinstance(got, Response):
            return got
        s, staff = got
        try:
            v = await service.view(staff, request_id)
        except DeskError as e:
            return _page("Request", f"<p>Cannot show this request ({escape(e.code)}).</p>", staff_id=s.staff_id, csrf=s.csrf)
        mine = v.claimed_by == staff.id
        notes = "".join(f"<li>{escape(t)} <span class='muted'>({escape(sid)})</span></li>" for sid, t in v.notes) or "<li class='muted'>none</li>"
        proofs = "".join(f"<li>{escape(k)} <span class='muted'>#{escape(pid[:6])}</span></li>" for pid, k in v.proofs) or "<li class='muted'>none yet (needed before Done)</li>"
        c = _csrf_field(s.csrf)
        base = f"/concierge/r/{escape(v.id)}"

        def form(action: str, inner: str, label: str) -> str:
            return f"<form method='post' action='{base}/{action}' class='card'>{c}{inner}<button>{label}</button></form>"

        acts = ""
        if v.status.value in ("new", "escalated") and can(staff, "request.claim"):
            acts += form("claim", "", "Take this request")
        if mine:
            acts += form("note", "<input name='text' maxlength='500' size='60' placeholder='Short note (never a code or password)'>", "Add note")
            acts += form("proof", "<select name='kind'>" + "".join(f"<option>{k}</option>" for k in PROOF_KINDS) + "</select> <input name='ref' maxlength='300' size='50' placeholder='photo or receipt reference, or a short call note'>", "Add proof")
            acts += form("contact", "<select name='party'><option>parent</option><option>child</option></select>", "Contact through a Robin line")
            acts += form("done", "", "Mark done (needs proof)")
            acts += form("escalate", "<select name='reason'>" + "".join(f"<option>{x}</option>" for x in ESCALATE_REASONS) + "</select>", "Escalate to a lead")
            acts += form("release", "", "Give back to the queue")
        body = (f"<h2>{escape(v.category)} <span class='p-{v.priority.value}'>[{v.priority.value}]</span> - {v.status.value}</h2>"
                f"<div class='card'><p><b>Wanted:</b> {escape(v.summary)}</p><p><b>For:</b> {escape(v.parent_label)} - {escape(v.parent_phone_masked)} - language: {escape(v.language)}</p>"
                f"<p class='muted'>Numbers are hidden. Use the contact button: Robin connects you; you never see the number.</p>"
                f"<p>Time limit: {v.sla.replace('_', ' ')}{' | waiting for the child to say yes to the spend' if v.waiting_for_child else ''}{' | a UPI link is ready for the user to tap' if v.has_pay_link else ''}</p></div>"
                f"<h3>Notes</h3><ul>{notes}</ul><h3>Proof</h3><ul>{proofs}</ul>{acts}<p class='muted'>The desk never pays, never asks for a code, password or PIN.</p>")
        return _page("Request", body, staff_id=s.staff_id, csrf=s.csrf, msg=request.query_params.get("msg", "")[:80])

    @r.post("/r/{request_id}/{action}")
    async def request_action(request: Request, request_id: str, action: str) -> Response:
        got = await post_auth(request)
        if isinstance(got, Response):
            return got
        s, staff, f = got
        back = f"/concierge/r/{request_id}"
        try:
            if action == "claim":
                await service.claim(staff, request_id)
            elif action == "release":
                await service.release(staff, request_id)
                back = "/concierge/"
            elif action == "note":
                await service.note(staff, request_id, f.get("text", ""))
            elif action == "proof":
                await service.proof(staff, request_id, f.get("kind", ""), f.get("ref", ""))
            elif action == "done":
                await service.done(staff, request_id)
                back = "/concierge/"
            elif action == "escalate":
                await service.escalate(staff, request_id, f.get("reason", ""))
                back = "/concierge/"
            elif action == "contact":
                link = await service.contact(staff, request_id, f.get("party", ""))
                return go(back, f"Connecting: {link.masked_label}")
            else:
                return Response(status_code=404, headers=HEADERS)
        except DeskError as e:
            return go(back, f"Not done: {e.code}")
        return go(back, "Saved.")

    # ------------------------------------------------------------------ lane 2
    @r.get("/desk")
    async def desk_page(request: Request) -> Response:
        got = await auth(request)
        if isinstance(got, Response):
            return got
        s, staff = got
        try:
            hs = await desk.open_handoffs(staff)
        except DeskError:
            return _page("Not allowed", "<p>Your role is not on the emergency desk.</p>", staff_id=s.staff_id, csrf=s.csrf)
        trs = "".join(f"<tr><td>{escape(h.card['tier'])}</td><td>{h.status}</td><td>{escape(h.card['why'])}</td><td>{escape(h.joined_by or '-')}</td><td><a href='/concierge/desk/{escape(h.card['incident_id'])}'>open</a></td></tr>" for h in hs)
        return _page("Emergency desk", f"<h2>Emergency handoffs ({len(hs)})</h2><table><tr><th>Level</th><th>State</th><th>Why</th><th>Person on it</th><th></th></tr>{trs}</table>",
                     staff_id=s.staff_id, csrf=s.csrf, msg=request.query_params.get("msg", "")[:80])

    @r.get("/desk/{incident_id}")
    async def desk_card(request: Request, incident_id: str) -> Response:
        got = await auth(request)
        if isinstance(got, Response):
            return got
        s, staff = got
        try:
            h = await desk.view(staff, incident_id)
        except DeskError as e:
            return _page("Handoff", f"<p>Cannot show this ({escape(e.code)}).</p>", staff_id=s.staff_id, csrf=s.csrf)
        card, c = h.card, _csrf_field(s.csrf)
        sig = "".join(f"<li>{escape(a)} <span class='muted'>{escape(b)}</span></li>" for a, b in card["signals"]) or "<li class='muted'>none</li>"
        rung = "".join(f"<li>{escape(a)}: {escape(b)}</li>" for a, b in card["rung"]) or "<li class='muted'>nobody yet</li>"
        base = f"/concierge/desk/{escape(incident_id)}"
        acts = ""
        if h.status in ("paged", "unanswered", "no_desk"):
            acts += f"<form method='post' action='{base}/ack' class='card'>{c}<button>I got it (acknowledge)</button></form>"
        if h.status in ("paged", "acked", "unanswered", "no_desk", "handed_back"):
            acts += f"<form method='post' action='{base}/join' class='card'>{c}<button>I am on the line (stops Robin ringing again)</button></form>"
        if h.status == "joined" and h.joined_by == staff.id:
            acts += f"<form method='post' action='{base}/handback' class='card'>{c}<button>Hand back to Robin</button></form>"
        if h.status != "closed":
            acts += (f"<form method='post' action='{base}/close' class='card'>{c}<select name='outcome'>" + "".join(f"<option>{o}</option>" for o in OUTCOMES) + "</select> "
                     "<select name='reason'><option value=''>(false alarm reason)</option>" + "".join(f"<option>{x}</option>" for x in FALSE_ALARM_REASONS) + "</select><button>Close incident</button></form>")
        body = (f"<h2>{escape(card['tier'])} - {h.status}</h2><div class='card'><p><b>Why:</b> {escape(card['why'])}</p><p>Language: {escape(card['language'])}</p>"
                f"<p>Consent on file: {escape(', '.join(card['consent_items']) or 'none')}</p><p class='muted'>Authority calls (112, bank, police) are not made from here yet: tell the family to call 112 themselves.</p></div>"
                f"<h3>Signals</h3><ul>{sig}</ul><h3>Who Robin rang</h3><ul>{rung}</ul><h3>What Robin did</h3><p>{escape(', '.join(card['ai_actions']) or '-')}</p>{acts}")
        return _page("Handoff", body, staff_id=s.staff_id, csrf=s.csrf, msg=request.query_params.get("msg", "")[:80])

    @r.post("/desk/{incident_id}/{action}")
    async def desk_action(request: Request, incident_id: str, action: str) -> Response:
        got = await post_auth(request)
        if isinstance(got, Response):
            return got
        _s, staff, f = got
        back = f"/concierge/desk/{incident_id}"
        try:
            if action == "ack":
                await desk.ack(staff, incident_id)
            elif action == "join":
                await desk.join(staff, incident_id)
            elif action == "handback":
                await desk.hand_back(staff, incident_id)
            elif action == "close":
                await desk.close(staff, incident_id, f.get("outcome", ""), f.get("reason") or None)
                back = "/concierge/desk"
            else:
                return Response(status_code=404, headers=HEADERS)
        except DeskError as e:
            return go(back, f"Not done: {e.code}")
        return go(back, "Saved.")

    # ------------------------------------------------------------------ no export, anywhere
    @r.api_route("/export{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    @r.api_route("/download{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    @r.api_route("/csv{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    async def no_export(request: Request, rest: str = "") -> Response:  # noqa: ARG001
        got = await sessions.get(request.cookies.get(COOKIE))
        if got is not None:
            await audit.record(got[0].staff_id, "export_denied", "")
        return Response(status_code=404, headers=HEADERS)

    return r
