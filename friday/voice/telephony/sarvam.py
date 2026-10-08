"""Sarvam telephony - PRIMARY for India (founder update 2026-10-07), Exotel = fallback,
Twilio = international.

Integration mode: (a) RAW MEDIA STREAMING. A Sarvam-rented number or a BYO carrier
(Vobiz) streams call audio over a WebSocket to ``/voice/sarvam/media``; our
CallSessionRunner + CallPolicy decide EVERY turn, ``friday.core.safety`` checks every
utterance / key press, and Sarvam is used for STT (Saarika) and TTS (Bulbul) through
``c.stt`` / ``c.tts``. Sarvam's hosted Conversations agent is NOT used to decide what
Friday says.

Wire protocol: Vobiz exposes a Plivo-compatible Voice API + XML (<Stream
bidirectional="true">) - implemented here. Mode (b) (Sarvam custom-LLM / per-turn
webhook) is NOT implemented: it inverts control of the turn loop and is only needed if
media streaming is unavailable on the chosen number.
  TODO(docs.sarvam.ai/conversations/deploy/telephony/vobiz): confirm Vobiz API base
       URL, auth headers, XML <Stream> attributes and WS event names used below.
  TODO(docs.sarvam.ai/conversations/deploy/deploy-with-code): confirm whether a
       Sarvam-rented number can stream raw audio to a custom WS (else use Vobiz BYO).

Capability matrix (``capabilities()``; the RoutedTelephony falls back to Exotel per call
when a brief needs something missing here):

  capability          | Sarvam/Vobiz (this) | Exotel            | Twilio
  --------------------|---------------------|-------------------|------------------
  outbound            | yes (Call API)      | yes               | yes
  inbound + missed    | yes (answer/hangup) | yes (passthru)    | yes
  media_stream        | yes (bidir WS)      | yes (Voicebot)    | yes (Media Streams)
  dtmf                | yes (REST DTMF)     | in-band tones     | in-band tones
  recording           | yes (REST Record)   | yes (callback)    | yes (callback)
  amd (voicemail)     | yes (machine_det.)  | no (classifier)   | yes
  bridge_transfer     | yes (transfer XML)  | yes (connect 2)   | yes
  bridge_conference   | no  (TODO)          | no                | yes (monitoring)
  custom_llm_turns    | no  (mode b: gap)   | -                 | -

Config (core Settings): sarvam_telephony_auth_id / _auth_token / _base_url (default
https://api.vobiz.ai/api/v1, TODO verify), sarvam_caller_ids (sticky per business),
telephony_route (default sarvam,exotel,twilio; see telephony/routing.py).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote, urlparse
from xml.sax.saxutils import escape, quoteattr

import httpx

from friday.core.clock import Clock
from friday.core.container import Container
from friday.core.events import EventBus
from friday.core.interfaces import AudioClassifier, ProviderError, STTProvider, TTSProvider
from friday.core.logging import get_logger, mask_phone
from friday.core.models import DialStatus, OutboundCallRequest, new_id
from friday.voice._http import VendorHTTP
from friday.voice.callerid import CallerIdSelector, choose_from_number
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.events import InboundCallReceived, MissedCallReceived
from friday.voice.signals import block_signal
from friday.voice.telephony.exotel import exotel_token as _token
from friday.voice.telephony.twilio import FRAME_BYTES, TwilioCallLeg
from friday.voice.tts.cache import cached_tts

log = get_logger(__name__)

CAPABILITIES = frozenset({
    "outbound", "inbound", "missed_call", "media_stream", "dtmf", "recording", "amd",
    "bridge_transfer",
})  # fmt: skip
DEFAULT_BASE_URL = "https://api.vobiz.ai/api/v1"  # TODO(.../deploy/telephony/vobiz)
INBOUND_MESSAGE = (
    "This is Friday, an AI assistant. I called you on behalf of a customer. "
    "I'll call you back shortly. Thank you."
)
# Plivo-style hangup causes.  TODO(.../telephony/vobiz): verify cause names.
_HANGUP = {
    "USER_BUSY": DialStatus.BUSY,
    "BUSY": DialStatus.BUSY,
    "NO_ANSWER": DialStatus.NO_ANSWER,
    "NO_USER_RESPONSE": DialStatus.NO_ANSWER,
    "ORIGINATOR_CANCEL": DialStatus.NO_ANSWER,
    "UNALLOCATED_NUMBER": DialStatus.FAILED,
}
SendText = Callable[[str], Awaitable[None]]


def sarvam_token(secret: str, scope: str) -> str:
    return _token(secret, f"sarvam:{scope}")


def stream_xml(ws_url: str, *, extra: str = "") -> str:
    # TODO(.../telephony/vobiz): <Stream bidirectional keepCallAlive contentType> attrs.
    return (
        f'<Response>{extra}<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-mulaw;rate=8000">{escape(ws_url)}</Stream></Response>'
    )


class SarvamCallLeg(TwilioCallLeg):
    """Same VAD -> STT -> classifier pipeline; Plivo/Vobiz stream framing + REST."""

    provider = "sarvam"

    def __init__(self, tel: SarvamTelephony, **kw: Any) -> None:
        super().__init__(tel, **kw)  # type: ignore[arg-type]
        self.tel_s = tel
        self._close: Callable[[], Awaitable[None]] | None = None

    async def _play(self, ulaw: bytes) -> None:
        assert self._send is not None
        for i in range(0, len(ulaw), FRAME_BYTES * 10):
            await self._send(
                json.dumps(
                    {
                        "event": "playAudio",
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": base64.b64encode(ulaw[i : i + FRAME_BYTES * 10]).decode(),
                        },
                    }
                )
            )
        name = f"cp{new_id()[:10]}"
        ev = asyncio.Event()
        self._marks[name] = ev
        await self._send(
            json.dumps({"event": "checkpoint", "streamId": self.stream_sid, "name": name})
        )
        try:
            await asyncio.wait_for(ev.wait(), timeout=len(ulaw) / 8000 + 5)
        except TimeoutError:
            self._marks.pop(name, None)
        self._check_live()

    async def send_dtmf(self, digits: str) -> None:
        self._check_live()
        if not self.provider_call_id:
            raise ProviderError("sarvam", "no call id for DTMF")
        await self.tel_s.rest("POST", f"/Call/{self.provider_call_id}/DTMF/", {"digits": digits})

    async def add_participant(self, phone: str, *, announce: str | None = None) -> SarvamCallLeg:
        """Transfer (no conference): the business leg is redirected to XML that dials
        the user from the same number. Friday cannot monitor afterwards."""
        self._check_live()
        key = new_id()
        user = SarvamCallLeg(
            self.tel_s, key=key, to_phone=phone, from_number=self.from_number, listen_only=True
        )
        self.tel_s.legs[key] = user
        self.children.append(user)
        url = self.tel_s.url(
            "transfer", key, to=phone, caller=self.from_number or "", say=(announce or "")[:200]
        )
        await self.tel_s.rest(
            "POST",
            f"/Call/{self.provider_call_id}/",
            {"legs": "aleg", "aleg_url": url, "aleg_method": "POST"},
        )
        self.bridged = True
        self._send = None
        return user

    async def wait_for_answer(self, timeout_s: float) -> Any:
        if self.listen_only:
            try:
                await asyncio.wait_for(self._status_event.wait(), timeout=timeout_s + 10)
            except TimeoutError:
                self.status = DialStatus.NO_ANSWER
            return self.status or DialStatus.NO_ANSWER
        return await super().wait_for_answer(timeout_s)

    async def leave(self) -> None:
        self.left = True
        self._end()

    async def hangup(self) -> None:
        await self._complete_call()
        self._end()

    async def _complete_call(self) -> None:
        if self.provider_call_id and not self.bridged:
            try:
                await self.tel_s.rest("DELETE", f"/Call/{self.provider_call_id}/", None)
            except ProviderError as e:
                log.debug("sarvam hangup failed: %s", e)

    async def play_fixed_message_and_hangup(self, text: str = INBOUND_MESSAGE) -> None:
        with contextlib.suppress(Exception):
            await self.speak(text, self.language)
        await self.hangup()

    async def fetch_recording(self, url: str) -> bytes | None:
        return await self.tel_s.fetch_recording(url)


class SarvamTelephony:
    name = "sarvam"

    def __init__(
        self,
        *,
        auth_id: str,
        auth_token: str,
        caller_ids: list[str],
        public_base_url: str,
        secret: str,
        stt: STTProvider,
        tts: TTSProvider,
        classifier: AudioClassifier | None = None,
        bus: EventBus | None = None,
        clock: Clock | None = None,
        base_url: str = DEFAULT_BASE_URL,
        record: bool = True,
        inbound_claim_timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.auth_id = auth_id
        self.caller_ids = caller_ids
        self.public_base_url = public_base_url.rstrip("/")
        self.secret = secret
        self.stt = stt
        self.tts = tts
        self.classifier = classifier or HeuristicAudioClassifier()
        self.bus = bus
        self.clock = clock
        self.record = record
        self.inbound_claim_timeout_s = inbound_claim_timeout_s
        self.caller_id_selector: CallerIdSelector | None = None
        self.legs: dict[str, SarvamCallLeg] = {}
        self.by_sid: dict[str, SarvamCallLeg] = {}
        self.inbound_legs: dict[str, SarvamCallLeg] = {}
        # TODO(.../telephony/vobiz): auth header names (Plivo uses HTTP Basic).
        auth = base64.b64encode(f"{auth_id}:{auth_token}".encode()).decode()
        self._http = VendorHTTP(
            "sarvam",
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Basic {auth}"},
            transport=transport,
        )

    def _own_recording(self, url: str) -> bool:
        base = urlparse(self._http._client.base_url.__str__())
        u = urlparse(url)
        return u.scheme == "https" and bool(u.hostname) and u.hostname == base.hostname

    async def fetch_recording(self, url: str) -> bytes | None:
        if not self._own_recording(url):  # never send our credentials to another host
            return None
        return (await self._http.request("GET", url)).content

    async def delete_recording(self, url: str) -> None:
        """SECURITY-14. TODO(docs.sarvam.ai/conversations/deploy/telephony/vobiz): confirm
        the Recording delete endpoint; Plivo-style ``DELETE /Account/{id}/Recording/{rid}/``."""
        m = re.search(r"/Recording/([0-9A-Za-z\-]+)", url)
        if not m or not self._own_recording(url):
            raise ProviderError("sarvam", "not a recording of this account")
        try:
            await self.rest("DELETE", f"/Recording/{m.group(1)}/", None)
        except ProviderError as e:
            if "HTTP 404" not in str(e):
                raise

    def capabilities(self) -> frozenset[str]:
        return CAPABILITIES

    # ------------------------------------------------------------------ urls / REST
    def token(self, scope: str) -> str:
        return sarvam_token(self.secret, scope)

    def url(self, path: str, key: str = "", **params: str) -> str:
        scope = key or "inbound"
        q = "&".join(f"{k}={quote(v, safe='')}" for k, v in {"key": key, **params}.items() if v)
        q = f"{q}&token={self.token(scope)}" if q else f"token={self.token(scope)}"
        return f"{self.public_base_url}/voice/sarvam/{path}?{q}"

    def media_ws_url_for(self, key: str) -> str:
        """SECURITY-18: per-call stream URL; the token only authorises THIS call key."""
        base = self.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/voice/sarvam/media?key={key}&token={self.token(f'media:{key}')}"

    async def rest(self, method: str, path: str, data: dict | None) -> dict:
        resp = await self._http.request(
            method, f"/Account/{self.auth_id}{path}", json=data if data is not None else None
        )
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {}

    # ------------------------------------------------------------------ TelephonyProvider
    async def place_call(self, request: OutboundCallRequest) -> SarvamCallLeg:
        from_number = choose_from_number(request, self.caller_ids, self.caller_id_selector)
        if not from_number:
            raise ProviderError("sarvam", "no Sarvam/Vobiz caller ID configured")
        key = new_id()
        leg = SarvamCallLeg(
            self,
            key=key,
            to_phone=request.to_phone,
            from_number=from_number,
            language=request.language,
        )
        self.legs[key] = leg
        # TODO(.../telephony/vobiz): Instant Outbound / Call API field names.
        body = await self.rest(
            "POST",
            "/Call/",
            {
                "from": from_number.lstrip("+"),
                "to": request.to_phone.lstrip("+"),
                "answer_url": self.url("answer", key),
                "answer_method": "POST",
                "hangup_url": self.url("hangup", key),
                "hangup_method": "POST",
                "ring_timeout": request.ring_timeout_s,
                "time_limit": request.max_duration_s + 1800,
                "machine_detection": "true" if request.metadata.get("role") != "user" else "false",
                "machine_detection_url": self.url("machine", key),
            },
        )
        sid = body.get("request_uuid") or body.get("call_uuid") or body.get("CallUUID")
        if not sid:
            raise ProviderError("sarvam", "no call uuid in response")
        leg.provider_call_id = str(sid)
        self.by_sid[leg.provider_call_id] = leg
        log.info(
            "sarvam call %s -> %s from %s",
            sid,
            mask_phone(request.to_phone),
            mask_phone(from_number),
        )
        return leg

    def take_inbound(self, provider_call_id: str) -> SarvamCallLeg | None:
        leg = self.inbound_legs.pop(provider_call_id, None)
        if leg is not None:
            leg.claimed = True
        return leg

    # ------------------------------------------------------------------ webhooks
    def _leg(self, params: Mapping[str, str], key: str | None) -> SarvamCallLeg | None:
        if key and key in self.legs:
            return self.legs[key]
        for k in ("CallUUID", "RequestUUID", "call_uuid"):
            if params.get(k) in self.by_sid:
                return self.by_sid[params[k]]
        return None

    async def answer_xml(self, params: Mapping[str, str], key: str | None) -> str:
        """answer_url: outbound pick-up, or an inbound call to a Friday number."""
        leg = self._leg(params, key)
        if leg is None:  # inbound
            sid = params.get("CallUUID") or new_id()
            key = new_id()
            leg = SarvamCallLeg(
                self,
                key=key,
                to_phone=params.get("From", "anonymous"),
                from_number=params.get("To"),
                inbound=True,
            )
            leg.provider_call_id = sid
            self.legs[key] = leg
            self.by_sid[sid] = leg
        else:
            leg.provider_call_id = params.get("CallUUID") or leg.provider_call_id
            if leg.provider_call_id:
                self.by_sid[leg.provider_call_id] = leg
        if self.record and not leg.inbound:
            asyncio.ensure_future(self._start_recording(leg))
        return stream_xml(self.media_ws_url_for(leg.key))

    async def _start_recording(self, leg: SarvamCallLeg) -> None:
        try:
            # TODO(.../telephony/vobiz): Record API path + response field ("url").
            body = await self.rest("POST", f"/Call/{leg.provider_call_id}/Record/", {})
            leg.recording = body.get("url") or body.get("recording_url")
            leg.record_expected = True
            if leg.recording:
                leg._recording_event.set()
        except ProviderError as e:
            log.warning("sarvam recording not started: %s", e)

    async def handle_machine(self, params: Mapping[str, str], key: str | None) -> None:
        leg = self._leg(params, key)
        if (
            leg is not None
            and str(params.get("Machine", "")).lower() == "true"
            and leg.status is None
        ):
            leg.status = DialStatus.VOICEMAIL
            leg._status_event.set()

    async def handle_hangup(self, params: Mapping[str, str], key: str | None) -> None:
        leg = self._leg(params, key)
        if leg is None:
            return
        cause = str(params.get("HangupCause") or params.get("HangupCauseName") or "").upper()
        streamed = leg.stream_sid is not None
        if leg.status is None:
            leg.block_signal = block_signal(
                params.get("SipResponseCode"), cause.replace("_", " ")
            ) or ("rejected" if cause == "CALL_REJECTED" else None)
            if leg.block_signal:
                leg.status = DialStatus.FAILED
            elif leg.listen_only and cause == "NORMAL_CLEARING":
                leg.status = DialStatus.ANSWERED
            else:
                leg.status = _HANGUP.get(
                    cause, DialStatus.NO_ANSWER if not streamed else DialStatus.ANSWERED
                )
            leg._status_event.set()
        if params.get("RecordUrl"):
            leg.recording = params["RecordUrl"]
            leg._recording_event.set()
        leg._end()
        if leg.inbound and not streamed:
            await self._publish(
                MissedCallReceived(
                    provider=self.name,
                    provider_call_id=leg.provider_call_id,
                    from_phone=leg.to_phone,
                    to_number=leg.from_number,
                    ring_seconds=float(params.get("Duration") or 0),
                    reason="short_ring",
                )
            )

    def transfer_xml(self, params: Mapping[str, str]) -> str:
        to, caller, say = params.get("to", ""), params.get("caller", ""), params.get("say", "")
        speak = f'<Speak voice="WOMAN" language="en-IN">{escape(say)}</Speak>' if say else ""
        return (
            f"<Response>{speak}<Dial callerId={quoteattr(caller)}>"
            f"<Number>{escape(to.lstrip('+'))}</Number></Dial></Response>"
        )

    async def handle_transfer_status(self, params: Mapping[str, str], key: str | None) -> None:
        leg = self.legs.get(key or "")
        if leg is not None and leg.status is None:
            leg.status = DialStatus.ANSWERED
            leg._status_event.set()

    async def handle_stream_message(
        self,
        msg: dict,
        send: SendText,
        state: dict,
        key: str | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        # TODO(.../telephony/vobiz): event names start/media/dtmf/playedStream/stop.
        event = msg.get("event")
        if event == "start":
            start = msg.get("start", {})
            leg = self.legs.get(key or "")  # key was authenticated by the WS route
            if leg is None or leg.stream_sid is not None:
                log.warning("rejected sarvam media stream (unknown call or second start)")
                return
            state["leg"] = leg
            leg._close = close
            leg.attach_stream(start.get("streamId") or msg.get("streamId") or "", send)
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
        elif event == "playedStream":
            leg.on_mark(msg.get("name", ""))
        elif event == "stop":
            leg.on_stream_stop()

    async def _claim_guard(self, leg: SarvamCallLeg) -> None:
        await asyncio.sleep(self.inbound_claim_timeout_s)
        if not leg.claimed and not leg.ended:
            self.inbound_legs.pop(leg.provider_call_id or "", None)
            await leg.play_fixed_message_and_hangup()

    async def _publish(self, event: Any) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def aclose(self) -> None:
        await self._http.aclose()


def build_sarvam_telephony(c: Container) -> SarvamTelephony:
    s = c.settings
    if not (s.sarvam_telephony_auth_id and s.sarvam_telephony_auth_token):
        raise ProviderError("sarvam", "SARVAM_TELEPHONY_AUTH_ID / _AUTH_TOKEN not set")
    try:
        classifier = c.audio_classifier
    except Exception:  # noqa: BLE001
        classifier = HeuristicAudioClassifier()
    return SarvamTelephony(
        auth_id=s.sarvam_telephony_auth_id,
        auth_token=s.sarvam_telephony_auth_token.get_secret_value(),
        caller_ids=list(s.sarvam_caller_ids or s.friday_numbers),
        public_base_url=s.public_base_url,
        secret=s.secret_key.get_secret_value(),
        stt=c.stt,
        tts=cached_tts(c),
        classifier=classifier,
        bus=c.bus,
        clock=c.clock,
        base_url=s.sarvam_telephony_base_url or DEFAULT_BASE_URL,
        record=s.call_record,
        inbound_claim_timeout_s=s.inbound_claim_timeout_s,
    )
