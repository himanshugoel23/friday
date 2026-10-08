"""Exotel telephony - DISABLED BY DEFAULT (founder decision 2026-10-08: live calling is
Sarvam only for now; enable with telephony_provider=exotel or an explicit route).

Indian ExoPhones give better answer rates and route business call-backs to us; Twilio is
the fallback / international provider.

Outbound::

    place_call -> POST /v1/Accounts/{sid}/Calls/connect.json
                  From=<callee>, CallerId=<sticky ExoPhone>, Url=<Voicebot flow>,
                  StatusCallback (terminal + answered, JSON), Record, CustomField=<key>
    The flow's Voicebot applet opens our WebSocket (/voice/exotel/media) with raw
    16-bit 8 kHz PCM ("raw/slin") both ways; we reuse the Twilio leg's VAD -> STT ->
    AudioClassifier pipeline and send TTS audio back as PCM chunks + "mark" events.
    send_dtmf  -> in-band DTMF tones over the stream
    recording  -> RecordingUrl from the terminal status callback
    BRIDGE_USER -> LIMITATION: Exotel's v1 API has no ad-hoc conference for a call
                   that is inside a Voicebot applet, so add_participant does a
                   *transfer*: it places a "connect two numbers" call (user first,
                   then the business, from the same ExoPhone); ``leave()`` ends
                   Friday's leg. The business gets a fresh call from the same number
                   within seconds, so the runner's bridge line should say so
                   ("Rahul will call you right now from this number"). No whisper
                   prompt (connect API has none) and Friday cannot monitor (no
                   ``leave_after_bridge=False``). Outcome is still TRANSFERRED.

Inbound (BRIEF E30-35): the ExoPhone's flow = Passthru(/voice/exotel/passthru) ->
Voicebot(/voice/exotel/media). Passthru registers the call; a stream start publishes
``InboundCallReceived`` and parks the leg (``take_inbound``); no stream within
``inbound_stream_wait_s`` (caller hung up while ringing) or a terminal status without a
stream publishes ``MissedCallReceived``.

Webhook auth: Exotel does not sign webhooks, so every URL we hand Exotel carries
``token=HMAC-SHA256(FRIDAY_SECRET_KEY, <scope>)`` (per-call key for status callbacks, the
static scope "exotel" for the dashboard-configured passthru / Voicebot URLs);
``friday.voice.http`` rejects requests without a valid token. Optionally restrict by IP
at the edge (TODO(exotel-docs: "Whitelisting Exotel IPs")).

Config (core change proposed in docs/CORE_CHANGES.md; read from env meanwhile):
  EXOTEL_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_CALLER_ID  (core Settings)
  EXOTEL_SUBDOMAIN            api.exotel.com (SG) | api.in.exotel.com (Mumbai, default)
  EXOTEL_VOICEBOT_APP_ID      flow (app) id whose first applet is Voicebot -> our WS
  EXOTEL_CALLER_IDS           comma-separated ExoPhone pool for sticky caller IDs
Select with FRIDAY_TELEPHONY_PROVIDER=exotel until "auto" prefers Exotel in core.

Exact API details to verify against Exotel docs are marked TODO(exotel-docs: <section>).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from friday.core.clock import Clock
from friday.core.container import Container
from friday.core.events import EventBus
from friday.core.interfaces import (
    AudioClassifier,
    CallEnded,
    ProviderError,
    STTProvider,
    TTSProvider,
)
from friday.core.logging import get_logger, mask_phone
from friday.core.models import DialStatus, Language, OutboundCallRequest, new_id
from friday.voice._http import VendorHTTP
from friday.voice.audio import dtmf_pcm16
from friday.voice.callerid import CallerIdSelector, choose_from_number
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.events import InboundCallReceived, MissedCallReceived
from friday.voice.signals import block_signal
from friday.voice.telephony.twilio import TwilioCallLeg
from friday.voice.tts.cache import cached_tts

log = get_logger(__name__)

PCM_FRAME = 320  # 20 ms of 8 kHz 16-bit mono
# TODO(exotel-docs: "Voicebot applet - media chunk size"): docs ask for multiples of
# 320 bytes, >= 3.2 kB per outbound media message. 100 ms chunks satisfy both.
OUT_CHUNK = 3200
INBOUND_MESSAGE = (
    "This is Friday, an AI assistant. I called you on behalf of a customer. "
    "I'll call you back shortly. Thank you."
)
# TODO(exotel-docs: "Call details / StatusCallback - Status values"): verify set.
_TERMINAL = {"completed", "failed", "busy", "no-answer", "canceled"}
_DIAL = {"busy": DialStatus.BUSY, "no-answer": DialStatus.NO_ANSWER,
         "failed": DialStatus.FAILED, "canceled": DialStatus.FAILED}  # fmt: skip

SendText = Callable[[str], Awaitable[None]]


def exotel_token(secret: str, scope: str) -> str:
    return hmac.new(secret.encode(), f"exotel:{scope}".encode(), hashlib.sha256).hexdigest()[:32]


def validate_exotel_token(secret: str, scope: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(exotel_token(secret, scope), token or "")


class ExotelCallLeg(TwilioCallLeg):
    """Same VAD/STT/classifier pipeline as Twilio; Exotel framing + call control."""

    provider = "exotel"

    def __init__(self, tel: ExotelTelephony, **kw: Any) -> None:
        super().__init__(tel, **kw)  # type: ignore[arg-type]
        self.tel_ex = tel
        self._close: Callable[[], Awaitable[None]] | None = None
        self.transfer_sid: str | None = None

    # ------------------------------------------------------------------ media in
    def on_media(self, payload_b64: str) -> None:
        if self.ended or self.left:
            return
        pcm = base64.b64decode(payload_b64)
        for i in range(0, len(pcm) - PCM_FRAME + 1, PCM_FRAME):
            for seg in self._segmenter.feed_pcm16(pcm[i : i + PCM_FRAME]):
                self._segments.put_nowait(seg)

    # ------------------------------------------------------------------ media out
    async def speak(self, text: str, language: Language) -> None:
        self._check_live()
        if self.listen_only or self._send is None:
            raise ProviderError("exotel", "this leg cannot play audio")
        await self._play_pcm(await self._synth(text, language))

    async def _play_pcm(self, pcm: bytes) -> None:
        assert self._send is not None
        sid = self.stream_sid
        for i in range(0, len(pcm), OUT_CHUNK):
            chunk = pcm[i : i + OUT_CHUNK]
            if len(chunk) % PCM_FRAME:
                chunk += b"\0" * (PCM_FRAME - len(chunk) % PCM_FRAME)
            await self._send(
                json.dumps(
                    {
                        "event": "media",
                        "stream_sid": sid,
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }
                )
            )
        name = f"m{new_id()[:10]}"
        ev = asyncio.Event()
        self._marks[name] = ev
        await self._send(json.dumps({"event": "mark", "stream_sid": sid, "mark": {"name": name}}))
        try:
            await asyncio.wait_for(ev.wait(), timeout=len(pcm) / 16000 + 5)
        except TimeoutError:
            self._marks.pop(name, None)
        self._check_live()

    async def send_dtmf(self, digits: str) -> None:
        # TODO(exotel-docs: "Voicebot applet - DTMF"): Exotel documents inbound "dtmf"
        # events; for sending we use in-band tones over the stream.
        self._check_live()
        if self._send is None:
            raise ProviderError("exotel", "cannot send DTMF without an active stream")
        await self._play_pcm(dtmf_pcm16(digits, 8000))

    # ------------------------------------------------------------------ bridge (transfer)
    async def add_participant(self, phone: str, *, announce: str | None = None) -> ExotelCallLeg:
        """Transfer, not a true three-way call (see module docstring)."""
        self._check_live()
        key = new_id()
        user = ExotelCallLeg(
            self.tel_ex, key=key, to_phone=phone, from_number=self.from_number, listen_only=True
        )
        self.tel_ex.legs[key] = user
        self.children.append(user)
        sid = await self.tel_ex.connect_two_numbers(
            first=phone, second=self.to_phone, caller_id=self.from_number, key=key
        )
        user.provider_call_id = sid
        self.tel_ex.by_sid[sid] = user
        self.transfer_sid = sid
        if announce:
            log.debug("exotel transfer: whisper not supported, %d chars dropped", len(announce))
        return user

    async def leave(self) -> None:
        self.left = True
        await self._complete_call()
        self._end()

    async def hangup(self) -> None:
        await self._complete_call()
        self._end()

    async def _complete_call(self) -> None:
        # Closing the Voicebot socket ends the applet; the flow then hangs up.
        # TODO(exotel-docs: "Voicebot applet - ending the stream"): confirm the flow's
        # next applet is "Hangup" and that closing the socket is the supported way.
        if self._close is not None:
            close, self._close = self._close, None
            try:
                await close()
            except Exception:  # noqa: BLE001
                log.debug("exotel socket already closed")

    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        if self.listen_only:  # transfer leg: answered when Exotel reports the user picked up
            try:
                await asyncio.wait_for(self._status_event.wait(), timeout=timeout_s + 10)
            except TimeoutError:
                self.status = DialStatus.NO_ANSWER
            return self.status or DialStatus.NO_ANSWER
        return await super().wait_for_answer(timeout_s)

    async def play_fixed_message_and_hangup(self, text: str = INBOUND_MESSAGE) -> None:
        with contextlib.suppress(ProviderError, CallEnded):
            await self.speak(text, Language.EN)
        await self.hangup()


class ExotelTelephony:
    name = "exotel"

    def __init__(
        self,
        *,
        sid: str,
        api_key: str,
        api_token: str,
        caller_ids: list[str],
        voicebot_app_id: str,
        public_base_url: str,
        secret: str,
        stt: STTProvider,
        tts: TTSProvider,
        classifier: AudioClassifier | None = None,
        bus: EventBus | None = None,
        clock: Clock | None = None,
        subdomain: str = "api.in.exotel.com",
        record: bool = True,
        inbound_claim_timeout_s: float = 10.0,
        inbound_stream_wait_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sid = sid
        self.caller_ids = caller_ids
        self.voicebot_app_id = voicebot_app_id
        self.public_base_url = public_base_url.rstrip("/")
        self.secret = secret
        self.stt = stt
        self.tts = tts
        self.classifier = classifier or HeuristicAudioClassifier()
        self.bus = bus
        self.clock = clock
        self.record = record
        self.inbound_claim_timeout_s = inbound_claim_timeout_s
        self.inbound_stream_wait_s = inbound_stream_wait_s
        self.caller_id_selector: CallerIdSelector | None = None
        self.worker_id: str | None = None  # S-9 call pinning
        self.legs: dict[str, ExotelCallLeg] = {}
        self.by_sid: dict[str, ExotelCallLeg] = {}
        self.inbound_legs: dict[str, ExotelCallLeg] = {}
        auth = base64.b64encode(f"{api_key}:{api_token}".encode()).decode()
        self._http = VendorHTTP(
            "exotel",
            base_url=f"https://{subdomain}",
            headers={"Authorization": f"Basic {auth}"},
            transport=transport,
        )

    # ------------------------------------------------------------------ urls / auth
    def token(self, scope: str) -> str:
        return exotel_token(self.secret, scope)

    def callback_url(self, key: str) -> str:
        return f"{self.public_base_url}/voice/exotel/status?key={key}&token={self.token(key)}"

    @property
    def flow_url(self) -> str:
        # TODO(exotel-docs: "Make a call - connect to a flow"): http://my.exotel.com/{sid}/exoml/start_voice/{app_id}
        return f"http://my.exotel.com/{self.sid}/exoml/start_voice/{self.voicebot_app_id}"

    @property
    def media_ws_url(self) -> str:
        """Configure this in the Voicebot applet of the ExoPhone / outbound flow."""
        base = self.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
        pin = f"&w={self.worker_id}" if self.worker_id else ""
        return f"{base}/voice/exotel/media?token={self.token('exotel')}{pin}"

    @property
    def passthru_url(self) -> str:
        """Configure this in the Passthru applet of the ExoPhone's inbound flow."""
        return f"{self.public_base_url}/voice/exotel/passthru?token={self.token('exotel')}"

    # ------------------------------------------------------------------ REST
    async def _connect(self, data: dict[str, str]) -> str:
        resp = await self._http.request(
            "POST", f"/v1/Accounts/{self.sid}/Calls/connect.json", data=data
        )
        try:
            return resp.json()["Call"]["Sid"]
        except (ValueError, KeyError, TypeError) as e:
            raise ProviderError("exotel", "no Call.Sid in connect response") from e

    def _common(self, key: str, *, ring_s: int, time_limit: int, record: bool) -> dict[str, str]:
        # TODO(exotel-docs: "Make a call - StatusCallbackEvents"): the array syntax
        # StatusCallbackEvents[0]=terminal / [1]=answered as documented for v1 connect.
        return {
            "CallType": "trans",
            "TimeOut": str(ring_s),
            "TimeLimit": str(time_limit),
            "StatusCallback": self.callback_url(key),
            "StatusCallbackContentType": "application/json",
            "StatusCallbackEvents[0]": "terminal",
            "StatusCallbackEvents[1]": "answered",
            "Record": "true" if record else "false",
            "CustomField": key,
        }

    async def connect_to_flow(
        self, *, to: str, caller_id: str, key: str, ring_s: int, time_limit: int, record: bool
    ) -> str:
        data = {
            "From": to,
            "CallerId": caller_id,
            "Url": self.flow_url,
            **self._common(key, ring_s=ring_s, time_limit=time_limit, record=record),
        }
        return await self._connect(data)

    async def connect_two_numbers(
        self, *, first: str, second: str, caller_id: str | None, key: str
    ) -> str:
        if not caller_id:
            raise ProviderError("exotel", "no ExoPhone caller ID")
        data = {
            "From": first,
            "To": second,
            "CallerId": caller_id,
            **self._common(key, ring_s=25, time_limit=1800, record=self.record),
        }
        return await self._connect(data)

    # ------------------------------------------------------------------ TelephonyProvider
    async def place_call(self, request: OutboundCallRequest) -> ExotelCallLeg:
        from_number = choose_from_number(request, self.caller_ids, self.caller_id_selector)
        if not from_number:
            raise ProviderError("exotel", "no ExoPhone configured (EXOTEL_CALLER_ID)")
        key = new_id()
        leg = ExotelCallLeg(
            self,
            key=key,
            to_phone=request.to_phone,
            from_number=from_number,
            language=request.language,
        )
        self.legs[key] = leg
        sid = await self.connect_to_flow(
            to=request.to_phone,
            caller_id=from_number,
            key=key,
            ring_s=request.ring_timeout_s,
            time_limit=max(request.max_duration_s, 60) + 1800,  # + hold time (care calls)
            record=request.record and self.record,
        )
        leg.provider_call_id = sid
        leg.record_expected = request.record and self.record
        self.by_sid[sid] = leg
        log.info(
            "exotel call %s -> %s from %s",
            sid,
            mask_phone(request.to_phone),
            mask_phone(from_number),
        )
        return leg

    def _own_recording(self, url: str) -> bool:
        u = urlparse(url)
        host = u.hostname or ""
        return u.scheme == "https" and (host == "exotel.com" or host.endswith(".exotel.com"))

    async def fetch_recording(self, url: str) -> bytes | None:
        if not self._own_recording(url):  # credentials only go to Exotel hosts
            return None
        return (await self._http.request("GET", url)).content

    async def delete_recording(self, url: str) -> None:
        """SECURITY-14. TODO(exotel-docs: "Recordings - delete"): no documented delete
        endpoint is confirmed; until verified this fails loudly so the erasure job keeps
        the URL in ``pending_deletions`` and ops deletes it from the dashboard."""
        if not self._own_recording(url):
            raise ProviderError("exotel", "not an Exotel recording")
        raise ProviderError("exotel", "recording deletion API not verified (TODO)")

    def capabilities(self) -> frozenset[str]:
        return frozenset({"outbound", "inbound", "missed_call", "media_stream", "dtmf",
                          "recording", "bridge_transfer"})  # fmt: skip

    def take_inbound(self, provider_call_id: str) -> ExotelCallLeg | None:
        leg = self.inbound_legs.pop(provider_call_id, None)
        if leg is not None:
            leg.claimed = True
        return leg

    # ------------------------------------------------------------------ webhooks
    async def handle_status(self, payload: Mapping[str, Any], key: str | None = None) -> None:
        """Terminal / answered StatusCallback (JSON or form)."""
        sid = str(payload.get("CallSid") or "")
        leg = self.legs.get(key or "") or self.by_sid.get(sid)
        if leg is None:
            return
        status = str(payload.get("Status") or payload.get("CallStatus") or "").lower()
        event = str(payload.get("EventType") or "").lower()
        if payload.get("RecordingUrl"):
            leg.recording = str(payload["RecordingUrl"])
            leg._recording_event.set()
        if event == "answered" or status in ("in-progress", "answered"):
            if leg.status is None:
                leg.status = DialStatus.ANSWERED
                leg._status_event.set()
            return
        if status in _TERMINAL or event == "terminal":
            streamed = leg.stream_sid is not None
            if leg.status is None:
                # TODO(exotel-docs: "Call details - Reason / SipResponseCode"): verify names
                leg.block_signal = block_signal(
                    payload.get("SipResponseCode"), str(payload.get("Reason") or "")
                )
                leg.status = _DIAL.get(status, DialStatus.NO_ANSWER)
                if leg.block_signal:
                    leg.status = DialStatus.FAILED
                leg._status_event.set()
            if leg.listen_only and status == "completed" and leg.status is DialStatus.NO_ANSWER:
                leg.status = DialStatus.ANSWERED  # transfer leg completed after talking
            leg._end()
            if leg.inbound and not streamed:
                await self._missed(leg, reason="caller_hung_up")

    async def handle_passthru(self, params: Mapping[str, str]) -> None:
        """Inbound call reached the ExoPhone flow (before the Voicebot applet)."""
        # TODO(exotel-docs: "Passthru applet - parameters"): CallSid, CallFrom, CallTo,
        # Direction=incoming, CurrentTime, DialWhomNumber...
        sid = params.get("CallSid") or new_id()
        if sid in self.by_sid:
            return
        key = new_id()
        leg = ExotelCallLeg(
            self,
            key=key,
            to_phone=params.get("CallFrom") or "anonymous",
            from_number=params.get("CallTo"),
            inbound=True,
        )
        leg.provider_call_id = sid
        self.legs[key] = leg
        self.by_sid[sid] = leg
        asyncio.ensure_future(self._stream_watchdog(leg))

    async def _stream_watchdog(self, leg: ExotelCallLeg) -> None:
        await asyncio.sleep(self.inbound_stream_wait_s)
        if leg.stream_sid is None and not leg.ended:
            leg._end()
            await self._missed(leg, reason="short_ring")

    async def _missed(self, leg: ExotelCallLeg, *, reason: str) -> None:
        if getattr(leg, "_missed_sent", False):
            return
        leg._missed_sent = True  # type: ignore[attr-defined]
        await self._publish(
            MissedCallReceived(
                provider=self.name,
                provider_call_id=leg.provider_call_id,
                from_phone=leg.to_phone,
                to_number=leg.from_number,
                reason=reason,
            )
        )

    async def handle_stream_message(
        self,
        msg: dict,
        send: SendText,
        state: dict,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """One Voicebot WebSocket message.
        TODO(exotel-docs: "Voicebot applet - WebSocket messages"): event names
        connected/start/media/dtmf/mark/clear/stop and snake_case ``stream_sid`` /
        ``call_sid`` keys as implemented here."""
        event = msg.get("event")
        if event == "start":
            start = msg.get("start", {})
            call_sid = start.get("call_sid") or start.get("callSid") or ""
            custom = start.get("custom_parameters") or {}
            key = custom.get("key") or custom.get("CustomField")
            leg = self.legs.get(key or "") or self.by_sid.get(call_sid)
            if leg is None:  # inbound without passthru: create on the fly
                await self.handle_passthru(
                    {
                        "CallSid": call_sid,
                        "CallFrom": start.get("from", ""),
                        "CallTo": start.get("to", ""),
                    }
                )
                leg = self.by_sid.get(call_sid)
            if leg is None or leg.stream_sid is not None:  # unknown call / second start
                log.warning("rejected exotel media stream (unknown call or second start)")
                return
            state["leg"] = leg
            leg._close = close
            leg.attach_stream(msg.get("stream_sid") or start.get("stream_sid") or "", send)
            if leg.inbound and not leg.claimed and leg.provider_call_id:
                self.inbound_legs[leg.provider_call_id] = leg
                asyncio.ensure_future(self._claim_guard(leg))
                await self._publish(
                    InboundCallReceived(
                        provider=self.name,
                        provider_call_id=leg.provider_call_id,
                        from_phone=leg.to_phone,
                        to_number=leg.from_number,
                    )
                )
            return
        leg = state.get("leg")
        if leg is None:
            return
        if event == "media":
            leg.on_media(msg.get("media", {}).get("payload", ""))
        elif event == "mark":
            leg.on_mark(msg.get("mark", {}).get("name", ""))
        elif event == "stop":
            leg.on_stream_stop()

    async def _claim_guard(self, leg: ExotelCallLeg) -> None:
        await asyncio.sleep(self.inbound_claim_timeout_s)
        if not leg.claimed and not leg.ended:
            self.inbound_legs.pop(leg.provider_call_id or "", None)
            await leg.play_fixed_message_and_hangup()

    async def _publish(self, event: Any) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def aclose(self) -> None:
        await self._http.aclose()


def build_exotel(c: Container) -> ExotelTelephony:
    s = c.settings
    if not (s.exotel_sid and s.exotel_api_key and s.exotel_api_token):
        raise ProviderError("exotel", "EXOTEL_SID / EXOTEL_API_KEY / EXOTEL_API_TOKEN not set")
    app_id = s.exotel_voicebot_app_id
    if not app_id:
        raise ProviderError(
            "exotel", "EXOTEL_VOICEBOT_APP_ID not set (flow with the Voicebot applet)"
        )
    pool = list(s.exotel_caller_ids or s.friday_numbers)
    if s.exotel_caller_id and s.exotel_caller_id not in pool:
        pool.append(s.exotel_caller_id)
    try:
        classifier = c.audio_classifier
    except Exception:  # noqa: BLE001
        classifier = HeuristicAudioClassifier()
    return ExotelTelephony(
        sid=s.exotel_sid,
        api_key=s.exotel_api_key,
        api_token=s.exotel_api_token.get_secret_value(),
        caller_ids=pool,
        voicebot_app_id=app_id,
        public_base_url=s.public_base_url,
        secret=s.secret_key.get_secret_value(),
        stt=c.stt,
        tts=cached_tts(c),
        classifier=classifier,
        bus=c.bus,
        clock=c.clock,
        subdomain=s.exotel_subdomain,
        record=s.call_record,
    )
