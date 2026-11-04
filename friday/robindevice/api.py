"""Device API: ``/robin/device/*`` for the parent's Android app (bearer device token).

* A bad, missing or revoked token is a plain 404 (no hint that the route exists), checked BEFORE the body is read.
* Bodies are read with a hard size cap; schemas are ``extra=forbid``; validation errors name the field and
  the rule, never the value. Tokens are never logged.
* Per-device rate limits (429). The parent in the token is the only parent a request can touch.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from friday.core.logging import get_logger
from friday.robindevice.schemas import (
    AckIn,
    ConsentIn,
    HeartbeatIn,
    LocationIn,
    PairIn,
    PauseIn,
    ShareIn,
    SignalBatchIn,
)
from friday.robindevice.service import DeviceService
from friday.robindevice.store import ParentState

log = get_logger(__name__)

MAX_BODY = 65_536
MAX_VOICE_BYTES = 1_048_576
MAX_VOICE_SECONDS = 60
VOICE_MIMES = {"audio/ogg", "audio/mp4", "audio/aac", "audio/amr", "audio/wav", "audio/webm", "audio/mpeg"}
# route -> (requests, per seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "pair": (10, 60), "heartbeat": (12, 60), "signals": (30, 60), "share": (10, 60), "ack": (30, 60),
    "sos": (10, 60), "voice": (10, 60), "prompts": (30, 60), "consent": (30, 60), "pause": (10, 60),
    "stop": (10, 60), "resume": (10, 60), "transparency": (20, 60), "erase": (3, 60),
}
HEADERS = {"Cache-Control": "no-store"}


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, route: str) -> bool:
        limit, window = LIMITS[route]
        now = self._clock()
        q = self._hits[(key, route)]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def _json(data: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=HEADERS)


def _invalid(e: ValidationError) -> JSONResponse:
    fields = [{"field": ".".join(str(x) for x in err["loc"]), "rule": err["type"]} for err in e.errors()]
    return _json({"error": "invalid", "fields": fields[:10]}, 422)


async def _read(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="too large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="too large")
        chunks.append(chunk)
    return b"".join(chunks)


_M = TypeVar("_M", bound=BaseModel)


async def _model(request: Request, model: type[_M]) -> _M | JSONResponse:
    raw = await _read(request, MAX_BODY)
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as e:
        return _invalid(e)


def device_router(service: DeviceService, limiter: RateLimiter | None = None) -> APIRouter:
    router = APIRouter()
    lim = limiter or RateLimiter()

    def authed(request: Request, route: str) -> ParentState:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        st = service.authenticate(token) if token else None
        if st is None:
            raise HTTPException(status_code=404, detail="Not Found")
        if not lim.allow(st.parent_id, route):
            raise HTTPException(status_code=429, detail="slow down")
        return st

    @router.post("/pair")
    async def pair(request: Request) -> JSONResponse:
        host = request.client.host if request.client else "?"
        if not lim.allow(host, "pair"):
            raise HTTPException(status_code=429, detail="slow down")
        body = await _model(request, PairIn)
        if isinstance(body, JSONResponse):
            return body
        res = await service.pair(body)
        if res is None:
            raise HTTPException(status_code=404, detail="Not Found")  # wrong, used or expired code
        return _json(res)

    @router.post("/heartbeat")
    async def heartbeat(request: Request) -> JSONResponse:
        st = authed(request, "heartbeat")
        body = await _model(request, HeartbeatIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.heartbeat(st, body))

    @router.post("/signals")
    async def signals(request: Request) -> JSONResponse:
        st = authed(request, "signals")
        body = await _model(request, SignalBatchIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.ingest(st, body.events))

    @router.post("/share")
    async def share(request: Request) -> JSONResponse:
        st = authed(request, "share")
        body = await _model(request, ShareIn)
        if isinstance(body, JSONResponse):
            return body
        res = await service.share(st, body.kind, body.value)
        if res.get("error") == "no_consent":
            return _json(res, 403)
        if "error" in res:
            return _json(res, 422)
        return _json(res)

    @router.post("/ack")
    async def ack(request: Request) -> JSONResponse:
        st = authed(request, "ack")
        body = await _model(request, AckIn)
        if isinstance(body, JSONResponse):
            return body
        res = await service.ack(st, body)
        return _json(res, 404 if res.get("error") == "unknown_prompt" else 200)

    @router.post("/sos")
    async def sos(request: Request) -> JSONResponse:
        st = authed(request, "sos")
        raw = await _read(request, MAX_BODY)
        loc = None
        if raw.strip() not in (b"", b"{}"):
            try:
                loc = LocationIn.model_validate_json(raw)
            except ValidationError as e:
                return _invalid(e)
        return _json(await service.sos(st, loc))

    @router.post("/voice")
    async def voice(request: Request) -> JSONResponse:
        """Press-to-talk: raw audio body, ``Content-Type: audio/*``, ``X-Duration-S``. Not stored."""
        st = authed(request, "voice")
        mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
        dur = request.headers.get("x-duration-s", "")
        if mime not in VOICE_MIMES or not dur.isdigit() or not 1 <= int(dur) <= MAX_VOICE_SECONDS:
            return _json({"error": "invalid", "fields": [{"field": "content-type/x-duration-s", "rule": "bad"}]}, 422)
        audio = await _read(request, MAX_VOICE_BYTES)
        if not audio:
            return _json({"error": "invalid", "fields": [{"field": "body", "rule": "empty"}]}, 422)
        res = await service.voice_message(st, audio, mime, int(dur))
        if res.get("error") == "no_consent":
            return _json(res, 403)
        if "error" in res:
            return _json(res, 503)
        return _json(res)

    @router.get("/prompts")
    async def prompts(request: Request) -> JSONResponse:
        st = authed(request, "prompts")
        return _json({"prompts": await service.pending_prompts(st)})

    @router.get("/consent")
    async def get_consent(request: Request) -> JSONResponse:
        st = authed(request, "consent")
        return _json(await service.consent_view(st))

    @router.put("/consent")
    async def put_consent(request: Request) -> JSONResponse:
        """The phone can only WITHDRAW consent; the family admin grants it (admin_on_behalf)."""
        st = authed(request, "consent")
        body = await _model(request, ConsentIn)
        if isinstance(body, JSONResponse):
            return body
        try:
            return _json(await service.sync_consent(st, body.items))
        except PermissionError:
            return _json({"error": "consent_given_by_family_admin"}, 403)
        except ValueError:
            return _json({"error": "invalid", "fields": [{"field": "items", "rule": "unknown_item"}]}, 422)

    @router.post("/pause")
    async def pause(request: Request) -> JSONResponse:
        st = authed(request, "pause")
        body = await _model(request, PauseIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.pause(st, body.minutes))

    @router.post("/stop")
    async def stop(request: Request) -> JSONResponse:
        st = authed(request, "stop")
        return _json(await service.stop(st))

    @router.post("/resume")
    async def resume(request: Request) -> JSONResponse:
        st = authed(request, "resume")
        return _json(await service.resume(st))

    @router.get("/transparency")
    async def transparency(request: Request) -> JSONResponse:
        st = authed(request, "transparency")
        return _json(await service.transparency(st))

    @router.delete("/erase")
    async def erase(request: Request) -> JSONResponse:
        st = authed(request, "erase")
        return _json(await service.erase(st))

    return router


def mount_robin_device(app: FastAPI, service: DeviceService, limiter: RateLimiter | None = None) -> None:
    app.include_router(device_router(service, limiter), prefix="/robin/device")
    app.state.robin_device = service
