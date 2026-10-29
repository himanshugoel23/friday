# ruff: noqa: E501
"""Mounts the web channel inside ``friday serve``:

    GET  /web/<token>/                 the chat page (the Chat Lab page, dev panel never sent)
    GET  /web/<token>/manifest.webmanifest, sw.js, icon-*.png      add to home screen
    *    /web/<token>/api/...          the JSON API (state, send, voice-note, file, tap, feedback, ...)
    GET  /web/privacy                  privacy / grievance placeholder (public, noindex)
    *    /web/admin/<admin token>/...  testers, invites, feedback (only when FRIDAY_WEB_ADMIN_TOKEN is set)

Each personal token maps to ONE tester (name + own phone). A wrong, revoked or expired token is a plain
404 on every call. Inbound messages go through ``Runtime.accept_inbound`` (same dedupe, queue, onboarding,
consumer router and task engine as the WhatsApp webhook). Nothing here can reach Meta.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from friday.channels.sms import FakeSMS
from friday.core.logging import get_logger
from friday.core.models import (
    Channel,
    InboundMessage,
    LocationPin,
    MessageKind,
)
from friday.webchat import copy, icons
from friday.webchat.channel import ChatStore, WebChannel
from friday.webchat.config import WebConfig
from friday.webchat.guard import (
    GuardedTelephony,
    RateLimiter,
    WebGuard,
    ensure_dialable,
    startup_problems,
)
from friday.webchat.registry import InviteRefused, Registry, Tester, allowed_numbers, mask

log = get_logger(__name__)

LAB_PAGE = Path(__file__).resolve().parent.parent / "lab" / "static" / "index.html"
DEV_BLOCK = re.compile(r"<!--DEV-->.*?<!--/DEV-->|/\*DEV\*/.*?/\*/DEV\*/", re.S)
MAX_UPLOAD = 5 * 1024 * 1024
HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}
PAGE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self'; manifest-src 'self'; "
    "worker-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
PWA_HEAD = (
    '<link rel="manifest" href="manifest.webmanifest">'
    '<link rel="apple-touch-icon" href="apple-touch-icon.png">'
    '<link rel="icon" type="image/png" href="icon-192.png">'
    '<meta name="apple-mobile-web-app-title" content="Friday">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
)
PWA_SCRIPT = (
    '<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("sw.js").catch(function(){});}</script>'
)
SW_JS = (
    'self.addEventListener("install",function(e){self.skipWaiting();});'
    'self.addEventListener("activate",function(e){e.waitUntil(self.clients.claim());});'
    'self.addEventListener("fetch",function(e){});'
)


class WebState:
    """Everything the web channel owns in this process."""

    def __init__(self, c: Any, cfg: WebConfig, registry: Registry, channel: WebChannel, guard: WebGuard) -> None:
        self.c, self.cfg, self.registry, self.channel, self.guard = c, cfg, registry, channel, guard
        self.limiter = RateLimiter(cfg.messages_per_min)
        self.runtime: Any = None
        self.tasks: set[asyncio.Task[Any]] = set()

    def now(self) -> datetime:
        return self.c.clock.now()


def prepare_web(c: Any, cfg: WebConfig | None = None) -> WebState | None:
    """Build the web channel and swap it in for WhatsApp/SMS/telephony. Call BEFORE ``Runtime(c)``.
    Returns None (and changes nothing) when the switch is off or a rule refuses."""
    cfg = cfg or WebConfig()
    if not cfg.channel_enabled:
        return None
    problems = startup_problems(c.settings, cfg)
    if problems:
        msg = "Friday web channel NOT started: " + " ".join(problems)
        log.error(msg)
        print(msg, flush=True)
        return None
    registry = Registry(cfg.path, c.clock.now)
    channel = WebChannel(registry, c.clock.now)
    guard = WebGuard(c.settings, cfg, registry, now=c.clock.now)
    state = WebState(c, cfg, registry, channel, guard)
    c.override("messaging", channel)  # no Meta/WhatsApp send exists while the web channel is on
    c.override("sms", FakeSMS(dict(c.settings.sms_dlt_templates), c.clock))
    for t in registry.active(c.clock.now()):
        ensure_dialable(c.settings, t.phone)
    try:
        inner = c.get("telephony")
    except Exception:  # noqa: BLE001 - no telephony configured: no calls at all
        log.info("web channel: no telephony provider; calls are not possible")
    else:
        c.override("telephony", GuardedTelephony(inner, guard, _requester_resolver(c, registry)))
    return state


def _requester_resolver(c: Any, registry: Registry) -> Any:
    async def resolve(request: Any) -> Tester | None:
        task = await c.repos.tasks.get(request.task_id)
        if task is None:
            return None
        user = await c.repos.users.get(task.requester_user_id)
        return registry.by_phone(user.phone, c.clock.now()) if user is not None else None

    return resolve


def link_for(settings: Any, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/web/{token}/"


# --------------------------------------------------------------------------------- request models
class SendIn(BaseModel):
    phone: str = ""
    text: str = Field(max_length=2000)


class LocationIn(BaseModel):
    phone: str = ""
    lat: float
    lng: float


class TapIn(BaseModel):
    phone: str = ""
    message_id: str
    button_id: str


class FeedbackIn(BaseModel):
    message_id: str
    kind: str
    note: str = Field(default="", max_length=1000)


class InviteIn(BaseModel):
    name: str
    phone: str
    days: float | None = None


class RevokeIn(BaseModel):
    ref: str


class ReviewIn(BaseModel):
    action: str  # approve | reject | edit
    text: str = Field(default="", max_length=2000)


def mount_web(app: FastAPI, state: WebState, runtime: Any) -> None:
    state.runtime = runtime
    app.state.web = state
    c, cfg = state.c, state.cfg
    router = APIRouter()

    def json_(data: Any, status: int = 200) -> JSONResponse:
        return JSONResponse(data, status_code=status, headers=HEADERS)

    def tester_for(token: str) -> Tester:
        t = state.registry.by_token(token, state.now())
        if t is None or not ensure_dialable(c.settings, t.phone):
            raise HTTPException(status_code=404)
        return t

    # ------------------------------------------------------------------ public placeholder
    @router.get("/privacy")
    async def privacy() -> HTMLResponse:
        return HTMLResponse(copy.PRIVACY_HTML, headers={**HEADERS, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    # ------------------------------------------------------------------ admin (token protected)
    def admin_ok(admin_token: str) -> None:
        want = cfg.admin_token
        if not want or cfg.problems() or not secrets.compare_digest(admin_token.encode(), want.encode()):
            raise HTTPException(status_code=404)

    def tester_row(t: Tester) -> dict[str, Any]:
        calls, spend = state.registry.usage(t.id, state.now())
        return {**t.public(), "calls_today": calls, "spend_today_inr": round(spend, 1)}

    @router.get("/admin/{admin_token}/")
    async def admin_page(admin_token: str) -> HTMLResponse:
        admin_ok(admin_token)
        html = copy.ADMIN_HTML.replace("__API__", f"/web/admin/{admin_token}/api")
        return HTMLResponse(html, headers={**HEADERS, "Content-Security-Policy": PAGE_CSP})

    @router.get("/admin/{admin_token}/api/overview")
    async def admin_overview(admin_token: str) -> JSONResponse:
        admin_ok(admin_token)
        from friday.pause import is_paused

        calls, spend = state.registry.usage(None, state.now())
        return json_(
            {
                "testers": [tester_row(t) for t in state.registry.all()],
                "feedback": state.registry.feedback()[-100:][::-1],
                "paused": is_paused(c.settings),
                "today": {"calls": calls, "spend_inr": round(spend, 1)},
                "caps": {
                    "calls_per_day": cfg.max_calls_per_day or "unlimited",
                    "spend_per_day_inr": cfg.max_spend_inr or "unlimited",
                    "global_spend_per_day_inr": cfg.global_max_spend_inr or "unlimited",
                },
            }
        )

    @router.post("/admin/{admin_token}/api/invite")
    async def admin_invite(admin_token: str, body: InviteIn) -> JSONResponse:
        admin_ok(admin_token)
        try:
            tester, token = state.registry.invite(
                body.name, body.phone, allowed=allowed_numbers(c.settings),
                days=body.days or cfg.invite_days, default_cc=c.settings.default_country_code, now=state.now(),
            )
        except InviteRefused as e:
            return json_({"detail": str(e)}, 422)
        ensure_dialable(c.settings, tester.phone)
        return json_({"tester": tester.public(), "link": link_for(c.settings, token)})  # shown once

    @router.post("/admin/{admin_token}/api/revoke")
    async def admin_revoke(admin_token: str, body: RevokeIn) -> JSONResponse:
        admin_ok(admin_token)
        t = state.registry.revoke(body.ref, state.now())
        if t is None:
            return json_({"detail": "no such tester"}, 404)
        state.channel.store_for(t.id).clear()
        return json_({"tester": t.public()})

    # ------------------------------------------------------------------ reply review (founder; docs/REPLY_WRITER.md)
    def reply_log() -> Any:
        from friday.replywriter.log import ReplyLog

        return ReplyLog.open(c.settings, now=state.now)

    @router.get("/admin/{admin_token}/review")
    async def review_page(admin_token: str) -> HTMLResponse:
        admin_ok(admin_token)
        html = copy.REVIEW_HTML.replace("__API__", f"/web/admin/{admin_token}/api")
        return HTMLResponse(html, headers={**HEADERS, "Content-Security-Policy": PAGE_CSP})

    @router.get("/admin/{admin_token}/api/review")
    async def review_list(admin_token: str, limit: int = 40) -> JSONResponse:
        admin_ok(admin_token)
        rl = reply_log()
        rows = [
            {
                "id": i["id"], "ts": i["ts"], "intent": i["intent"], "writer": i["writer"], "fact_check": i["fact_check"],
                "status": i["status"], "reactions": i["reactions"], "messages": i["output"]["messages"], "gold": i["gold"],
            }
            for i in rl.items()[: max(1, min(limit, 200))]
        ]
        return json_({"enabled": bool(getattr(c.settings, "reply_log_enabled", False)), "stats": rl.stats(), "items": rows})

    @router.post("/admin/{admin_token}/api/review/{rid}")
    async def review_act(admin_token: str, rid: str, body: ReviewIn) -> JSONResponse:
        admin_ok(admin_token)
        status = {"approve": "approved", "reject": "rejected", "edit": "edited"}.get(body.action)
        if status is None or not reply_log().review(rid, status, body.text):
            return json_({"detail": "cannot review that reply"}, 422)
        return json_({"ok": True, "status": status})

    # ------------------------------------------------------------------ the tester's page
    @router.get("/{token}/")
    async def page(token: str, dev: str = "") -> HTMLResponse:
        t = tester_for(token)
        html = DEV_BLOCK.sub("", LAB_PAGE.read_text(encoding="utf-8"))  # the dev panel is never sent
        html = html.replace("__API_BASE__", f"/web/{token}/api")
        html = html.replace("</head>", PWA_HEAD + "</head>", 1)
        html = html.replace("</body>", PWA_SCRIPT + "</body>", 1)
        if dev == "1":  # a tiny status line, nothing else
            calls, spend = state.registry.usage(t.id, state.now())
            left = int((datetime.fromisoformat(t.expires_at) - state.now()).total_seconds() // 3600)
            line = f"web · {t.name} · {mask(t.phone)} · calls today {calls} · Rs {spend:.0f} · link {left}h left"
            html = html.replace(
                '<div class="main">',
                f'<div id="webstatus" style="font:11px/1.4 system-ui;padding:2px 12px;opacity:.7">{line}</div><div class="main">',
                1,
            )
        return HTMLResponse(html, headers={**HEADERS, "Content-Security-Policy": PAGE_CSP})

    @router.get("/{token}/manifest.webmanifest")
    async def manifest(token: str) -> Response:
        tester_for(token)
        base = f"/web/{token}/"
        doc = {
            "name": "Friday", "short_name": "Friday", "start_url": base, "scope": base,
            "display": "standalone", "background_color": "#0b141a", "theme_color": "#008069",
            "icons": [
                {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        }
        return Response(json.dumps(doc), media_type="application/manifest+json", headers=HEADERS)

    @router.get("/{token}/sw.js")
    async def sw(token: str) -> Response:
        tester_for(token)
        return Response(SW_JS, media_type="text/javascript", headers=HEADERS)

    @router.get("/{token}/{icon}.png")
    async def icon(token: str, icon: str) -> Response:
        tester_for(token)
        size = {"icon-192": 192, "icon-512": 512, "apple-touch-icon": 180}.get(icon)
        if size is None:
            raise HTTPException(status_code=404)
        return Response(icons.png(size), media_type="image/png", headers={**HEADERS, "Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------------ the tester's API
    def _token_first(token: str) -> None:  # runs before body validation: a bad token is a plain 404
        tester_for(token)

    api = APIRouter(prefix="/{token}/api", dependencies=[Depends(_token_first)])

    def snapshot(t: Tester) -> dict[str, Any]:
        store = state.channel.store_for(t.id)
        now = state.now()
        return {
            "entries": store.public_entries(),
            "turn": None,
            "user": {},
            "switches": {},
            "clock": {"iso": now.isoformat(), "label": now.strftime("%d %b %H:%M")},
            "persona": "",
            "llm": {"mode": "real", "real_available": True},
            "token_seconds_left": max(0, int((datetime.fromisoformat(t.expires_at) - now).total_seconds())),
            "other_out": [],
        }

    @api.get("/config")
    async def config(token: str) -> JSONResponse:
        t = tester_for(token)
        return json_(
            {
                "web": True,
                "users": [{"key": "me", "label": t.name, "phone": "me", "masked": mask(t.phone), "saved": True}],
                "personas": {}, "persona": "", "contact_presets": [], "location_presets": {},
                "sample_files": [], "chips": [], "mode": "web",
                "llm": {"mode": "real", "real_available": True},
                "clock": snapshot(t)["clock"],
                "consent": {
                    "required": t.consented_at is None,
                    "text": copy.CONSENT_TEXT,
                    "button": copy.CONSENT_BUTTON,
                    "privacy": "/web/privacy",
                    "privacy_label": copy.PRIVACY_LINK,
                },
            }
        )

    @api.post("/consent")
    async def consent(token: str) -> JSONResponse:
        t = tester_for(token)
        state.registry.set_consent(t.id, state.now())
        return json_({"ok": True})

    @api.get("/state")
    async def get_state(token: str, phone: str = "") -> JSONResponse:
        return json_(snapshot(tester_for(token)))

    @api.get("/media/{media_id}")
    async def media(token: str, media_id: str) -> Response:
        t = tester_for(token)
        blob = state.channel.media_for(t.id, media_id)
        if blob is None:
            raise HTTPException(status_code=404)
        return Response(blob.data, media_type=blob.mime, headers={**HEADERS, "Cache-Control": "private, max-age=3600"})

    async def deliver(t: Tester, msg: InboundMessage, label: str) -> JSONResponse:
        """One inbound message through the SAME pipeline entry the WhatsApp webhook uses."""
        if t.consented_at is None:
            raise HTTPException(status_code=403, detail="Tap Continue first.")
        if state.guard.paused():
            raise HTTPException(status_code=503, detail="Friday is paused for now.")
        if not state.limiter.allow(t.id):
            raise HTTPException(status_code=429, detail="Slow down a little.")
        store = state.channel.store_for(t.id)
        entry = store.add_in(msg, label)
        before = store.out_count()
        accepted = await state.runtime.accept_inbound(msg)  # dedupe + durable enqueue
        entry["status"] = "delivered"
        if accepted and c.settings.has_role("task"):
            job = asyncio.create_task(state.runtime.drain())
            state.tasks.add(job)
            job.add_done_callback(state.tasks.discard)
            await asyncio.wait([job], timeout=cfg.reply_wait_s)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + cfg.reply_wait_s
            while store.out_count() <= before and loop.time() < deadline:
                await asyncio.sleep(0.2)
        return json_(snapshot(t))

    def inbound(t: Tester, kind: MessageKind, **kw: Any) -> InboundMessage:
        return InboundMessage(
            channel=Channel.WHATSAPP,
            from_phone=t.phone,
            kind=kind,
            provider_message_id=f"web.in.{uuid.uuid4().hex}",
            received_at=state.now(),
            **kw,
        )

    @api.post("/send")
    async def send(token: str, body: SendIn) -> JSONResponse:
        t = tester_for(token)
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Type something first.")
        return await deliver(t, inbound(t, MessageKind.TEXT, text=text), text)

    @api.post("/voice-note")
    async def voice_note(token: str, file: UploadFile = File(...), phone: str = Form("")) -> JSONResponse:
        t = tester_for(token)
        mime = (file.content_type or "").split(";")[0].strip().lower()
        if not (mime.startswith("audio/") or mime in ("video/webm", "video/mp4")):
            raise HTTPException(status_code=415, detail="That is not a voice note.")
        data = await file.read(MAX_UPLOAD + 1)
        if not data or len(data) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="That voice note is too long.")
        media_id = state.channel.store_for(t.id).put_media(data, mime, "voice")
        return await deliver(t, inbound(t, MessageKind.VOICE_NOTE, media_url=media_id, media_mime=mime), "Voice message")

    @api.post("/file")
    async def upload(token: str, file: UploadFile = File(...), phone: str = Form("")) -> JSONResponse:
        t = tester_for(token)
        mime = (file.content_type or "").split(";")[0].strip().lower()
        if mime != "application/pdf" and not mime.startswith("image/"):
            raise HTTPException(status_code=415, detail="Only photos and PDFs.")
        data = await file.read(MAX_UPLOAD + 1)
        if not data or len(data) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="That file is too large (5 MB).")
        name = (file.filename or "file")[:80]
        media_id = state.channel.store_for(t.id).put_media(data, mime, name)
        kind = MessageKind.DOCUMENT if mime == "application/pdf" else MessageKind.IMAGE
        return await deliver(t, inbound(t, kind, media_url=media_id, media_mime=mime), name)

    @api.post("/location")
    async def location(token: str, body: LocationIn) -> JSONResponse:
        t = tester_for(token)
        if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
            raise HTTPException(status_code=422, detail="That location is not valid.")
        pin = LocationPin(lat=body.lat, lng=body.lng)
        return await deliver(t, inbound(t, MessageKind.LOCATION, location=pin), "Location")

    @api.post("/tap")
    async def tap(token: str, body: TapIn) -> JSONResponse:
        t = tester_for(token)
        entry = state.channel.store_for(t.id).find_out(body.message_id)
        if entry is None:
            raise HTTPException(status_code=422, detail="That message is no longer there.")
        choices = list(entry.get("buttons") or [])
        for sec in (entry.get("list") or {}).get("sections", []):
            choices += sec.get("items", [])
        pick = next((b for b in choices if b["id"] == body.button_id), None)
        if pick is None:
            raise HTTPException(status_code=422, detail="That button is not on that message.")
        msg = inbound(t, MessageKind.BUTTON_REPLY, button_id=pick["id"], text=pick["title"], reply_to_provider_id=entry.get("provider_id"))
        return await deliver(t, msg, pick["title"])

    @api.post("/feedback")
    async def feedback(token: str, body: FeedbackIn) -> JSONResponse:
        t = tester_for(token)
        store: ChatStore = state.channel.store_for(t.id)
        entry = store.find_out(body.message_id)
        if entry is None or body.kind not in ("up", "down", "wrong"):
            raise HTTPException(status_code=422, detail="Cannot rate that message.")
        entry["mark"] = body.kind
        state.registry.add_feedback(t, body.kind, body.message_id, entry.get("text") or "", body.note, state.now())
        rs = getattr(getattr(runtime, "pipeline", None), "reply_service", None)
        if rs is not None:  # the thumb becomes the reaction on the reply-log record that sent this text
            rs.react(entry.get("text") or "", body.kind, body.note)
        return json_({"ok": True})

    router.include_router(api)
    app.include_router(router, prefix="/web")
    if cfg.admin_token and not cfg.problems():
        print("Friday web channel: admin page at /web/admin/<FRIDAY_WEB_ADMIN_TOKEN>/", flush=True)
    log.info("web channel mounted: %d active tester(s)", len(state.registry.active(state.now())))
