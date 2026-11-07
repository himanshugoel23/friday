"""Device API: ``/robin/device/*`` for the parent's Android app (bearer device token).

* A bad, missing or revoked token is a plain 404 (no hint that the route exists), checked BEFORE the body is read.
* Bodies are read with a hard size cap; schemas are ``extra=forbid``; validation errors name the field and
  the rule, never the value. Tokens are never logged.
* Per-device rate limits (429), shared by every replica through the device store (DB rows, no new table); the in-memory
  ``RateLimiter`` is for tests. SOS is exempt from every limit. The parent in the token is the only parent a request can touch.
* Pairing: per-source rate, per-code attempts, and a lockout of the source after ``PAIR_LOCKOUT_BAD`` bad codes.
* JSON bodies must be ``application/json`` (415 otherwise).
"""

from __future__ import annotations

import hashlib
import inspect
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
EXEMPT_ROUTES = frozenset({"sos"})  # an SOS is never rate-limited away (it is still authenticated)
PAIR_LOCKOUT_BAD = 5  # bad codes from one source ...
PAIR_LOCKOUT_S = 15 * 60  # ... inside this window lock that source out for the rest of the window
PAIR_CODE_ATTEMPTS = 5  # failed tries on the same code string inside the window
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


class StoreRateLimiter:
    """Rate limit whose counts live in the device store (DB rows with ``DbDeviceStore``): shared across replicas and restarts."""

    def __init__(self, store: Any, now_ms: Callable[[], int]) -> None:
        self.store, self.now_ms = store, now_ms

    async def allow(self, key: str, route: str) -> bool:
        limit, window = LIMITS[route]
        await self.store.ensure_loaded()
        return await self.store.rate_hit(f"{route}:{key}", limit, window * 1000, self.now_ms())


async def _allow(lim: Any, key: str, route: str) -> bool:
    res = lim.allow(key, route)
    return bool(await res) if inspect.isawaitable(res) else bool(res)


def _json(data: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=HEADERS)


def _invalid(e: ValidationError) -> JSONResponse:
    # An unknown key is attacker-chosen text: never echo it (report the parent path and "*" instead).
    fields = [{"field": ".".join([*(str(x) for x in err["loc"][:-1]), "*"] if err["type"] == "extra_forbidden" else (str(x) for x in err["loc"])), "rule": err["type"]} for err in e.errors()]
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


def _is_json(request: Request) -> bool:
    return request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json"


async def _model(request: Request, model: type[_M]) -> _M | JSONResponse:
    raw = await _read(request, MAX_BODY)
    if raw.strip() and not _is_json(request):
        raise HTTPException(status_code=415, detail="json only")
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as e:
        return _invalid(e)


def device_router(service: DeviceService, limiter: RateLimiter | None = None) -> APIRouter:
    router = APIRouter()
    lim = limiter or StoreRateLimiter(service.store, service.now_ms)

    async def authed(request: Request, route: str) -> ParentState:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        st = await service.authenticate(token) if token else None
        if st is None:
            raise HTTPException(status_code=404, detail="Not Found")
        if route not in EXEMPT_ROUTES and not await _allow(lim, st.parent_id, route):
            raise HTTPException(status_code=429, detail="slow down")
        return st

    @router.post("/pair")
    async def pair(request: Request) -> JSONResponse:
        host = request.client.host if request.client else "?"
        store, now = service.store, service.now_ms()
        await store.ensure_loaded()
        window_ms = PAIR_LOCKOUT_S * 1000
        src_key = "pairbad:" + host
        if await store.rate_count(src_key, now) >= PAIR_LOCKOUT_BAD:  # locked out: even a right code waits
            raise HTTPException(status_code=429, detail="slow down")
        if not await _allow(lim, host, "pair"):
            raise HTTPException(status_code=429, detail="slow down")
        body = await _model(request, PairIn)
        if isinstance(body, JSONResponse):
            await store.rate_note(src_key, window_ms, now)  # a malformed pairing request counts as a bad try
            return body
        code_key = "paircode:" + hashlib.sha256(body.code.encode()).hexdigest()[:32]
        if await store.rate_count(code_key, now) >= PAIR_CODE_ATTEMPTS:
            await store.rate_note(src_key, window_ms, now)
            raise HTTPException(status_code=429, detail="slow down")
        res = await service.pair(body)
        if res is None:
            await store.rate_note(src_key, window_ms, now)
            await store.rate_note(code_key, window_ms, now)
            raise HTTPException(status_code=404, detail="Not Found")  # wrong, used or expired code
        return _json(res)

    @router.post("/heartbeat")
    async def heartbeat(request: Request) -> JSONResponse:
        st = await authed(request, "heartbeat")
        body = await _model(request, HeartbeatIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.heartbeat(st, body))

    @router.post("/signals")
    async def signals(request: Request) -> JSONResponse:
        st = await authed(request, "signals")
        body = await _model(request, SignalBatchIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.ingest(st, body.events))

    @router.post("/share")
    async def share(request: Request) -> JSONResponse:
        st = await authed(request, "share")
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
        st = await authed(request, "ack")
        body = await _model(request, AckIn)
        if isinstance(body, JSONResponse):
            return body
        res = await service.ack(st, body)
        return _json(res, 404 if res.get("error") == "unknown_prompt" else 200)

    @router.post("/sos")
    async def sos(request: Request) -> JSONResponse:
        st = await authed(request, "sos")
        raw = await _read(request, MAX_BODY)
        loc = None
        if raw.strip() not in (b"", b"{}"):
            if not _is_json(request):
                raise HTTPException(status_code=415, detail="json only")
            try:
                loc = LocationIn.model_validate_json(raw)
            except ValidationError as e:
                return _invalid(e)
        return _json(await service.sos(st, loc))

    @router.post("/voice")
    async def voice(request: Request) -> JSONResponse:
        """Press-to-talk: raw audio body, ``Content-Type: audio/*``, ``X-Duration-S``. Not stored."""
        st = await authed(request, "voice")
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
        st = await authed(request, "prompts")
        return _json({"prompts": await service.pending_prompts(st)})

    @router.get("/consent")
    async def get_consent(request: Request) -> JSONResponse:
        st = await authed(request, "consent")
        return _json(await service.consent_view(st))

    @router.put("/consent")
    async def put_consent(request: Request) -> JSONResponse:
        """The phone can only WITHDRAW consent; the family admin grants it (admin_on_behalf)."""
        st = await authed(request, "consent")
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
        st = await authed(request, "pause")
        body = await _model(request, PauseIn)
        if isinstance(body, JSONResponse):
            return body
        return _json(await service.pause(st, body.minutes))

    @router.post("/stop")
    async def stop(request: Request) -> JSONResponse:
        st = await authed(request, "stop")
        return _json(await service.stop(st))

    @router.post("/resume")
    async def resume(request: Request) -> JSONResponse:
        st = await authed(request, "resume")
        return _json(await service.resume(st))

    @router.get("/transparency")
    async def transparency(request: Request) -> JSONResponse:
        st = await authed(request, "transparency")
        return _json(await service.transparency(st))

    @router.delete("/erase")
    async def erase(request: Request) -> JSONResponse:
        st = await authed(request, "erase")
        return _json(await service.erase(st))

    return router


def mount_robin_device(app: FastAPI, service: DeviceService, limiter: RateLimiter | None = None) -> None:
    app.include_router(device_router(service, limiter), prefix="/robin/device")
    app.state.robin_device = service
