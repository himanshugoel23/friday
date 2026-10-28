"""The Chat Lab web app: one HTML page and a small JSON API, every URL behind an unguessable token.

    GET  /lab/<token>/                 the page
    GET  /lab/api/<token>/...          the API (see ``_api``)

A bad, unknown or expired token answers 404 with no hint. Responses are no-store, noindex and send
no referrer. The app is created by ``create_lab_app``; it refuses to be created when the
environment says ``FRIDAY_MODE=live`` unless ``allow_live_env`` is given, and even then it builds a
simulator world (``friday/lab/safety.py``).
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from friday.core.config import Settings
from friday.lab.safety import check_may_start, environment_settings
from friday.lab.world import LabError, LabWorld

STATIC = Path(__file__).parent / "static"
DEFAULT_TTL_HOURS = 8.0
HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}
PAGE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src blob:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


_DEV_BLOCK = re.compile(r"<!--DEV-->.*?<!--/DEV-->|/\*DEV\*/.*?/\*/DEV\*/", re.S)


class TokenGate:
    """One unguessable token (24 random bytes) that expires; the only credential."""

    def __init__(
        self, ttl_hours: float, now: Callable[[], float] = time.time, token: str | None = None
    ) -> None:
        self._now = now
        self.token = token or secrets.token_urlsafe(24)
        self.expires_at = now() + ttl_hours * 3600

    def ok(self, supplied: str) -> bool:
        return secrets.compare_digest(supplied.encode(), self.token.encode()) and (
            self._now() < self.expires_at
        )

    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - self._now()))


class SendIn(BaseModel):
    phone: str
    text: str = Field(max_length=2000)


class VoiceIn(BaseModel):
    phone: str
    says: str = Field(max_length=1000)


class LocationIn(BaseModel):
    phone: str
    lat: float
    lng: float


class ContactIn(BaseModel):
    phone: str
    name: str = Field(max_length=80)
    number: str


class SampleIn(BaseModel):
    phone: str
    name: str


class TapIn(BaseModel):
    phone: str
    message_id: str
    button_id: str


class AdvanceIn(BaseModel):
    phone: str
    how: str


class PhoneIn(BaseModel):
    phone: str


class PersonaIn(BaseModel):
    persona: str


class SwitchIn(BaseModel):
    name: str
    on: bool


class LlmIn(BaseModel):
    mode: str


class MarkIn(BaseModel):
    phone: str
    seq: int
    note: str = Field(default="", max_length=1000)


def create_lab_app(
    *,
    env: Settings | None = None,
    allow_live_env: bool = False,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    notes_path: Path | str = "var/lab/notes.jsonl",
    token: str | None = None,
    now: Callable[[], float] = time.time,
) -> FastAPI:
    env = env or environment_settings()
    check_may_start(env, allow_live_env=allow_live_env)  # raises LabRefused in live mode
    gate = TokenGate(ttl_hours, now, token)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        world = await LabWorld.create(env=env, notes_path=notes_path)
        app.state.world = world
        try:
            yield
        finally:
            await world.close()

    app = FastAPI(
        title="Friday Chat Lab",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.gate = gate
    app.state.world = None

    def world_for(token: str) -> LabWorld:
        if not gate.ok(token):
            raise HTTPException(status_code=404)
        w = app.state.world
        if w is None:  # pragma: no cover - lifespan not started
            raise HTTPException(status_code=503)
        return w

    @app.exception_handler(LabError)
    async def _lab_error(request: Request, exc: LabError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422, headers=HEADERS)

    pages = APIRouter()

    @pages.get("/{token}/")
    async def page(token: str, dev: str = "") -> HTMLResponse:
        world_for(token)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        if dev != "1":  # the default page is only the chat: the dev parts are never even sent
            html = _DEV_BLOCK.sub("", html)
        html = html.replace("__API_BASE__", f"/lab/api/{token}")
        return HTMLResponse(html, headers={**HEADERS, "Content-Security-Policy": PAGE_CSP})

    app.include_router(pages, prefix="/lab")
    app.include_router(_api(world_for, gate), prefix="/lab/api/{token}")
    return app


def _api(world_for: Callable[[str], LabWorld], gate: TokenGate) -> APIRouter:
    r = APIRouter()

    def json_(data: Any) -> JSONResponse:
        return JSONResponse(data, headers=HEADERS)

    async def snapshot(
        w: LabWorld, phone: str, turn: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        phone = w.clean_phone(phone)
        w.user_for(phone)
        turns = w.turns[phone]
        return {
            "entries": [{k: v for k, v in e.items() if k != "rendered"} for e in w.entries[phone]],
            "turn": turn if turn is not None else (turns[-1] if turns else None),
            "user": await w.user_state(phone),
            "switches": w.switches(),
            "clock": w.clock_info(),
            "persona": w.persona,
            "llm": {"mode": w.llm_mode, "real_available": w.real_llm_available()},
            "token_seconds_left": gate.seconds_left(),
            "other_out": w.other_out[-20:],
        }

    @r.get("/config")
    async def config(token: str) -> JSONResponse:
        return json_(world_for(token).config())

    @r.get("/state")
    async def state(token: str, phone: str) -> JSONResponse:
        w = world_for(token)
        return json_(await snapshot(w, phone))

    @r.get("/turn")
    async def turn(token: str, phone: str, seq: int) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(phone)
        w.user_for(phone)
        for t in w.turns[phone]:
            if seq == t.get("input_seq") or seq in t.get("output_seqs", []):
                return json_(t)
        raise HTTPException(status_code=404)

    @r.post("/send")
    async def send(token: str, body: SendIn) -> JSONResponse:
        w = world_for(token)
        if not body.text.strip():
            raise LabError("type something first")
        phone = w.clean_phone(body.phone)
        msg = w.inbound_text(phone, body.text)
        t = await w.send_inbound(phone, msg, body.text.strip())
        return json_(await snapshot(w, phone, t))

    @r.post("/voice")
    async def voice(token: str, body: VoiceIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        t = await w.send_inbound(phone, w.inbound_voice(phone, body.says), body.says.strip())
        return json_(await snapshot(w, phone, t))

    @r.post("/location")
    async def location(token: str, body: LocationIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        msg = w.inbound_location(phone, body.lat, body.lng)
        t = await w.send_inbound(phone, msg, f"{body.lat:.4f}, {body.lng:.4f}")
        return json_(await snapshot(w, phone, t))

    @r.post("/contact")
    async def contact(token: str, body: ContactIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        msg = w.inbound_contact(phone, body.name, body.number)
        t = await w.send_inbound(phone, msg, body.name.strip() or "contact")
        return json_(await snapshot(w, phone, t))

    @r.post("/sample")
    async def sample(token: str, body: SampleIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        t = await w.send_inbound(phone, w.inbound_sample(phone, body.name), body.name)
        return json_(await snapshot(w, phone, t))

    @r.post("/file")
    async def file(
        token: str, phone: str = Form(...), file: UploadFile = File(...)
    ) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(phone)
        data = await file.read(5 * 1024 * 1024 + 1)
        name = (file.filename or "file")[:80]
        msg = w.inbound_file(phone, name, file.content_type or "", data)
        t = await w.send_inbound(phone, msg, name)
        return json_(await snapshot(w, phone, t))

    @r.post("/tap")
    async def tap(token: str, body: TapIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        msg = w.inbound_button(phone, body.message_id, body.button_id)
        t = await w.send_inbound(phone, msg, msg.text or body.button_id)
        return json_(await snapshot(w, phone, t))

    @r.post("/advance")
    async def advance(token: str, body: AdvanceIn) -> JSONResponse:
        w = world_for(token)
        t = await w.advance(body.phone, body.how)
        return json_(await snapshot(w, body.phone, t))

    @r.post("/new-user")
    async def new_user(token: str) -> JSONResponse:
        w = world_for(token)
        u = await w.new_user()
        return json_({"phone": u.phone, "config": w.config()})

    @r.post("/reset")
    async def reset(token: str, body: PhoneIn) -> JSONResponse:
        w = world_for(token)
        await w.reset(w.clean_phone(body.phone))
        return json_(await snapshot(w, body.phone))

    @r.post("/persona")
    async def persona(token: str, body: PersonaIn) -> JSONResponse:
        w = world_for(token)
        w.set_persona(body.persona)
        return json_({"persona": w.persona})

    @r.post("/switch")
    async def switch(token: str, body: SwitchIn) -> JSONResponse:
        w = world_for(token)
        w.set_switch(body.name, body.on)
        return json_(w.switches())

    @r.post("/llm")
    async def llm(token: str, body: LlmIn) -> JSONResponse:
        w = world_for(token)
        w.set_llm(body.mode)
        return json_({"mode": w.llm_mode})

    @r.post("/mark-wrong")
    async def mark(token: str, body: MarkIn) -> JSONResponse:
        w = world_for(token)
        phone = w.clean_phone(body.phone)
        w.mark_wrong(phone, body.seq, body.note)
        return json_({"ok": True})

    @r.get("/export.json")
    async def export_json(token: str, phone: str) -> Response:
        w = world_for(token)
        import json

        data = w.export(w.clean_phone(phone))
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            media_type="application/json",
            headers={
                **HEADERS,
                "Content-Disposition": 'attachment; filename="friday-lab-chat.json"',
            },
        )

    @r.get("/export.md")
    async def export_md(token: str, phone: str) -> Response:
        w = world_for(token)
        return Response(
            w.export_markdown(w.clean_phone(phone)),
            media_type="text/markdown; charset=utf-8",
            headers={**HEADERS, "Content-Disposition": 'attachment; filename="friday-lab-chat.md"'},
        )

    return r
