# ruff: noqa: E501
"""Routes: GET /robin (page), POST /robin/join, GET /robin/privacy. Mounted only when the switch is on."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from friday.core.models import normalize_phone
from friday.robinwaitlist import page
from friday.robinwaitlist.store import FOR, LANGS, WORRIES, WaitlistStore

MAX_PER_HOUR_PER_IP = 8
MAX_PER_DAY_TOTAL = 3000


class JoinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=40)
    phone: str = Field(max_length=32)
    whom: str = "mother"
    city: str = Field(default="", max_length=60)
    lang: str = "hindi"
    worries: list[str] = Field(default_factory=list, max_length=6)
    consent: bool = False
    website: str = ""  # honeypot
    src: str = Field(default="", max_length=32)


def _ip_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
    return hashlib.sha256(ip.encode()).hexdigest()[:16]  # kept in memory only, never stored


def waitlist_router(store: WaitlistStore, *, contact: str = "", clock: Any = time.time) -> APIRouter:
    router = APIRouter()
    hits: dict[str, deque[float]] = defaultdict(deque)
    day = {"d": "", "n": 0}

    def _limited(key: str) -> bool:
        now = clock()
        q = hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= MAX_PER_HOUR_PER_IP:
            return True
        q.append(now)
        return False

    @router.get("", response_class=HTMLResponse)
    def home(request: Request, src: str = "") -> HTMLResponse:
        store.view(src)
        return HTMLResponse(page.PAGE, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    @router.get("/privacy", response_class=HTMLResponse)
    def privacy() -> HTMLResponse:
        text = contact.strip() or "reply DELETE to any WhatsApp message from Robin, or tell the person who invited you."
        return HTMLResponse(page.PRIVACY.replace("{CONTACT}", text), headers={"X-Robots-Tag": "noindex"})

    @router.post("/join")
    def join(body: JoinIn, request: Request) -> JSONResponse:
        if body.website:  # a bot filled the hidden field: pretend success, store nothing
            return JSONResponse({"ok": True})
        if _limited(_ip_key(request)):
            return JSONResponse({"ok": False, "field": "busy"}, status_code=429)
        today = time.strftime("%Y-%m-%d", time.gmtime(clock()))
        if day["d"] != today:
            day.update(d=today, n=0)
        if day["n"] >= MAX_PER_DAY_TOTAL:
            return JSONResponse({"ok": False, "field": "busy"}, status_code=429)
        name = " ".join(body.name.split())
        city = " ".join(body.city.split())
        if not name:
            return JSONResponse({"ok": False, "field": "name"}, status_code=422)
        if not city:
            return JSONResponse({"ok": False, "field": "city"}, status_code=422)
        if not body.consent:
            return JSONResponse({"ok": False, "field": "consent"}, status_code=422)
        try:
            phone = normalize_phone(body.phone)
        except ValueError:
            return JSONResponse({"ok": False, "field": "phone"}, status_code=422)
        digits = phone[1:]
        if not (8 <= len(digits) <= 15) or (phone.startswith("+91") and len(digits) != 12):
            return JSONResponse({"ok": False, "field": "phone"}, status_code=422)
        whom = body.whom if body.whom in FOR else "other"
        lang = body.lang if body.lang in LANGS else "other"
        worries = [w for w in body.worries if w in WORRIES]
        _, created = store.add(name=name, phone=phone, city=city, lang=lang, whom=whom, worries=worries, src=body.src)
        if created:
            day["n"] += 1
        return JSONResponse({"ok": True})

    return router
