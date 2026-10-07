"""FastAPI app: ``create_app(container=None)`` (``uv run friday serve``).

Routes
  GET  /health                 liveness + mode + which components are available
  GET  /webhooks/whatsapp      Meta webhook verification handshake
  POST /webhooks/whatsapp      X-Hub-Signature-256 verified; messages -> pipeline,
                               delivery statuses -> message log
  /sim/*                       simulator chat + simulated inbound calls (simulator
                               messaging only)
  /voice/*                     the voice router (c.get("voice_router")) if available

Boots with no keys in simulator mode.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from friday.api.runtime import Runtime
from friday.channels.simulator import SimulatorChannel
from friday.channels.whatsapp import parse_webhook, verify_signature, verify_subscription
from friday.core.config import Settings
from friday.core.container import FACTORIES, ComponentNotAvailable, Container
from friday.core.logging import get_logger
from friday.core.models import normalize_phone

log = get_logger(__name__)


def create_app(
    container: Container | None = None, *, background: bool = True, fast_pin_hash: bool = False
) -> FastAPI:
    c = container or Container(Settings())
    runtime = Runtime(c, fast_pin_hash=fast_pin_hash)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.start(background=background)
        try:
            yield
        finally:
            await runtime.stop()
            if container is None:
                await c.aclose()

    app = FastAPI(title="Friday", version="0.1.0", lifespan=lifespan)
    app.state.container = c
    app.state.runtime = runtime

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": c.settings.mode,
            "components": {name: c.is_available(name) for name in FACTORIES},
        }

    # ------------------------------------------------------------------ WhatsApp webhook
    @app.get("/webhooks/whatsapp")
    async def wa_verify(request: Request) -> PlainTextResponse:
        q = request.query_params
        challenge = verify_subscription(
            q.get("hub.mode"),
            q.get("hub.verify_token"),
            q.get("hub.challenge"),
            c.settings.whatsapp_verify_token.get_secret_value(),
        )
        if challenge is None:
            raise HTTPException(status_code=403, detail="verification failed")
        return PlainTextResponse(challenge)

    @app.post("/webhooks/whatsapp")
    async def wa_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, int]:
        body = await request.body()
        secret = c.settings.whatsapp_app_secret
        if secret is not None:
            if not verify_signature(
                body, request.headers.get("x-hub-signature-256"), secret.get_secret_value()
            ):
                raise HTTPException(status_code=401, detail="bad signature")
        elif c.settings.is_live:
            raise HTTPException(status_code=401, detail="app secret not configured")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid json") from None
        batch = parse_webhook(payload, default_cc=c.settings.default_country_code)
        for msg in batch.messages:
            background_tasks.add_task(runtime.handle, msg)
        for st in batch.statuses:
            if st.provider_message_id and st.status == "failed":
                background_tasks.add_task(
                    c.repos.messages.update_status,
                    st.provider_message_id,
                    ok=False,
                    error=st.error,
                )
        return {"messages": len(batch.messages), "statuses": len(batch.statuses)}

    # ------------------------------------------------------------------ simulator
    app.include_router(_sim_router(c, runtime), prefix="/sim")

    # ------------------------------------------------------------------ voice
    try:
        router = c.get("voice_router")
    except ComponentNotAvailable:
        log.info("voice router not available; /voice not mounted")
    except Exception:  # noqa: BLE001 - voice must not stop the API from booting
        log.exception("voice router failed to build; /voice not mounted")
    else:
        app.include_router(router, prefix="/voice")
    return app


class SimMessageIn(BaseModel):
    phone: str
    text: str = ""


class SimCallIn(BaseModel):
    from_phone: str
    to_number: str | None = None
    answered: bool = True


def _sim_router(c: Container, runtime: Runtime) -> APIRouter:
    router = APIRouter(tags=["simulator"])

    def channel() -> SimulatorChannel:
        try:
            ch = c.messaging
        except ComponentNotAvailable:
            ch = None
        if not isinstance(ch, SimulatorChannel):
            raise HTTPException(status_code=404, detail="simulator channel not active")
        return ch

    def render(ch: SimulatorChannel, msgs: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": m.id,
                "to": m.to_phone,
                "text": m.text,
                "buttons": [b.model_dump() for b in m.buttons],
                "template": m.template.model_dump() if m.template else None,
                "rendered": ch.render(m),
            }
            for m in msgs
        ]

    @router.post("/messages")
    async def sim_send(body: SimMessageIn) -> dict[str, Any]:
        ch = channel()
        try:
            phone = normalize_phone(body.phone, c.settings.default_country_code)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid phone") from None
        before = len(ch.messages_to(phone))
        msg = ch.make_inbound(phone, body.text, default_cc=c.settings.default_country_code)
        await runtime.handle(msg)
        return {"replies": render(ch, ch.messages_to(phone)[before:])}

    @router.get("/messages/{phone}")
    async def sim_inbox(phone: str) -> dict[str, Any]:
        ch = channel()
        phone = normalize_phone(phone, c.settings.default_country_code)
        return {"messages": render(ch, ch.messages_to(phone))}

    @router.get("/outbox")
    async def sim_outbox() -> dict[str, Any]:
        ch = channel()
        return {"messages": render(ch, ch.outbox)}

    @router.post("/calls/inbound")
    async def sim_inbound_call(body: SimCallIn) -> dict[str, Any]:
        channel()
        match, contact = await runtime.callbacks.on_inbound_call(
            body.from_phone, body.to_number, answered=body.answered
        )
        ctx = await runtime.callbacks.safe_context(match)
        return {
            "status": match.status.value,
            "contact_id": contact.id,
            "greeting": runtime.callbacks.greeting(ctx),
        }

    return router
