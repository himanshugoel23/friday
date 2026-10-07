"""Voice HTTP/WS endpoints (mounted by friday/api at ``/voice``).

Twilio (live):
  POST /voice/twilio/status      call status callbacks (outbound + inbound)
  POST /voice/twilio/recording   recording status callbacks
  POST /voice/twilio/inbound     a call to a Friday number -> TwiML (media stream)
  WS   /voice/twilio/media       bidirectional Media Streams
All Twilio POSTs require a valid ``X-Twilio-Signature`` (URL = FRIDAY_PUBLIC_BASE_URL +
path + query).

Simulator (QA / local):
  POST /voice/sim/inbound        {"from_phone", "to_number"?, "answered"?, "ring_s"?}
  POST /voice/sim/deliver-due    deliver scheduled business call-backs / missed calls
  GET  /voice/recordings/{name}  local simulator recordings (transcript files)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from friday.core.container import Container
from friday.core.logging import get_logger
from friday.voice.telephony.twilio import TwilioTelephony, validate_twilio_signature

log = get_logger(__name__)


class SimInboundRequest(BaseModel):
    from_phone: str
    to_number: str | None = None
    answered: bool = True
    ring_s: float = 5.0


def build_router(c: Container) -> APIRouter:
    router = APIRouter(tags=["voice"])

    def telephony() -> Any:
        try:
            return c.telephony
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, "telephony not configured") from e

    def twilio() -> TwilioTelephony:
        tel = telephony()
        if not isinstance(tel, TwilioTelephony):
            raise HTTPException(404, "twilio is not the active telephony provider")
        return tel

    async def verified_form(request: Request, tel: TwilioTelephony) -> dict[str, str]:
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        url = c.settings.public_base_url.rstrip("/") + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        if not validate_twilio_signature(
            tel.auth_token, url, params, request.headers.get("X-Twilio-Signature")
        ):
            log.warning("rejected twilio webhook with bad signature on %s", request.url.path)
            raise HTTPException(403, "invalid signature")
        return params

    @router.post("/twilio/status")
    async def twilio_status(request: Request) -> Response:
        tel = twilio()
        params = await verified_form(request, tel)
        await tel.handle_status(params, request.query_params.get("key"))
        return Response(status_code=204)

    @router.post("/twilio/recording")
    async def twilio_recording(request: Request) -> Response:
        tel = twilio()
        params = await verified_form(request, tel)
        await tel.handle_recording(params, request.query_params.get("key"))
        return Response(status_code=204)

    @router.post("/twilio/inbound")
    async def twilio_inbound(request: Request) -> Response:
        tel = twilio()
        params = await verified_form(request, tel)
        return Response(content=tel.inbound_twiml(params), media_type="application/xml")

    @router.websocket("/twilio/media")
    async def twilio_media(ws: WebSocket) -> None:
        tel = twilio()
        await ws.accept()
        state: dict[str, Any] = {}
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                await tel.handle_stream_message(msg, ws.send_text, state)
                if msg.get("event") == "stop":
                    break
        except WebSocketDisconnect:
            leg = state.get("leg")
            if leg is not None:
                leg.on_stream_stop()

    # ---------------------------------------------------------------- simulator
    @router.post("/sim/inbound")
    async def sim_inbound(body: SimInboundRequest) -> dict[str, Any]:
        tel = telephony()
        if not hasattr(tel, "simulate_inbound_call"):
            raise HTTPException(404, "simulator telephony not active")
        call_id = await tel.simulate_inbound_call(
            body.from_phone, body.to_number, answered=body.answered, ring_s=body.ring_s
        )
        return {"provider_call_id": call_id, "answered": call_id is not None}

    @router.post("/sim/deliver-due")
    async def sim_deliver_due() -> dict[str, Any]:
        tel = telephony()
        if not hasattr(tel, "deliver_due_inbound"):
            raise HTTPException(404, "simulator telephony not active")
        return {"answered_call_ids": await tel.deliver_due_inbound()}

    @router.get("/recordings/{name}")
    async def recording(name: str) -> FileResponse:
        folder = (Path(c.settings.media_dir) / "recordings").resolve()
        path = (folder / name).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    return router
