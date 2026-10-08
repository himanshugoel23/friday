"""Sarvam telephony - THE live provider (founder decision 2026-10-08: Sarvam only for
now; Exotel / Twilio code stays in the repo but is disabled by default and not in the
default route - see telephony/routing.py).

Integration mode: (a) RAW MEDIA STREAMING. A Sarvam-rented number or a BYO carrier
(Vobiz) streams call audio over a WebSocket to ``/voice/sarvam/media``; OUR
CallSessionRunner + CallPolicy decide EVERY turn, ``friday.core.safety`` checks every
utterance / key press / commitment, and Sarvam is used for STT (Saarika) and TTS (Bulbul)
through ``c.stt`` / ``c.tts``. Sarvam's hosted Conversations agent never decides what
Friday says. Mode (b) (Sarvam custom-LLM / per-turn webhook) is NOT implemented: it
inverts control of the turn loop and is only worth building if media streaming turns
out to be unavailable on our number type (open question 1 in docs/SARVAM_QUESTIONS.md).

Wire protocol: Vobiz Voice API + VobizXML (Plivo-compatible). The founder's number
(+91 80 7158 2175) is a Vobiz number connected to Sarvam, i.e. the direct-Vobiz route.

VERIFIED (2026-10-08, via search summaries of the docs; direct fetch was blocked):
  * Route: Sarvam's own guide "Build a Voice Agent using Vobiz"
    (docs.sarvam.ai/api/integration/build-voice-agent-with-vobiz) - Vobiz's bidirectional
    media stream is plain JSON over WebSocket, Sarvam REST for STT/TTS; Vobiz docs
    (docs.vobiz.ai/solutions/ai-voice-agent) stream raw audio to your WebSocket.
  * REST: base ``https://api.vobiz.ai/api/v1``; headers ``X-Auth-ID`` / ``X-Auth-Token``;
    ``POST /Account/{auth_id}/Call/`` {from, to (E.164), answer_url, answer_method} ->
    ``call_uuid``; ``DELETE /Account/{auth_id}/Call/{call_uuid}`` hangs up (vobiz-ai
    agent-skills "vobiz-voice-calls"); answer_url returns VobizXML (application/xml).
  * Stream (vobiz.ai/docs/concepts/streaming-websockets, /docs/xml/stream/audio-formats):
    ``<Stream bidirectional="true">wss://..</Stream>``; Vobiz -> us: ``start``
    {start:{callId, streamId, tracks, mediaFormat{encoding, sampleRate}}}, ``media``
    (base64, 20 ms), ``playedStream`` (checkpoint reached), ``clearedAudio``, ``stop``;
    us -> Vobiz: ``playAudio`` {streamId, media{contentType, sampleRate, payload}} (raw mono
    L16 8/16/24 kHz or mu-law 8 kHz, no container), ``checkpoint`` {streamId, name},
    ``clearAudio`` {streamId}. Inbound <Stream contentType> accepts L16 at 8/16 kHz.
  * Transfer: Sarvam's Vobiz page ("Call transfer") says Vobiz supports transfer end to
    end to a PSTN E.164 number or SIP URI -> ``bridge_transfer`` is ON by default.
  * Call QUEUING must be OFF on the Vobiz account: with queuing on, outbound calls are held
    and may be marked failed (Sarvam Vobiz connection page).
STILL UNVERIFIED (kept as TODOs): the mid-call REST bodies - DTMF ``POST /Call/{uuid}/DTMF/``
and Record ``POST /Call/{uuid}/Record/`` (only the ``/Call/{uuid}/{action}/`` pattern is
documented); the live-call transfer request (Plivo-style ``legs=aleg`` + ``aleg_url`` here,
and the ``<Dial><Number>`` XML); per-call hangup_url (likely set on the Vobiz Application);
L16 byte order; ``keepCallAlive``; machine-detection fields; hangup-cause names.
  TODO(docs.vobiz.ai API reference: Call -> DTMF / Record / Transfer).

CAPABILITY MATRIX (S = supported, D = degraded, U = unsupported, ? = unverified API)
Because there is no fallback provider, anything D/U/? has a defined graceful path; the
runner reads ``capabilities()`` per call and never pretends.

  capability                 | status | what we do / degrade to
  ---------------------------|--------|-------------------------------------------------
  brain decides every turn   | S (?)  | mode (a): we terminate the audio stream. Transport
                             |        | details unverified (WS events); safety + commit
                             |        | gates run in OUR runner whatever the transport.
  DTMF for IVR               | D (?)  | REST DTMF first (body unverified); else in-band tones over
                             |        | the same stream. If neither works the IVR task
                             |        | declines BEFORE dialling (NEEDS_USER_VERIFICATION,
                             |        | collected["unsupported_capability"]="dtmf").
  inbound call-backs         | S (?)  | answer_url -> <Stream>; InboundCallReceived.
  missed calls               | S (?)  | hangup_url without a stream -> MissedCallReceived.
  inbound on retired numbers | S      | any dialled number is accepted and reported.
  many numbers + per-call    | S (?)  | ``from`` per call from request.from_number (the
  caller ID (number pool)    |        | NumberPool choice); BYO carrier numbers. Rented
                             |        | numbers may be limited (question 4).
  recording                  | D (?)  | REST Record; a failure leaves recording_url=None
                             |        | (the call still succeeds; no local audio kept).
  amd / voicemail            | S (?)  | machine_detection callback + our classifier.
  bridge_transfer (patch-in) | D (?)  | ON: Vobiz supports transfer (verified); our request
                             |        | shape is Plivo-style and unverified. It is a
                             |        | TRANSFER, not a 3-way. If the REST call fails the
                             |        | runner keeps the call and the policy ends it with a
                             |        | call-back pack. Kill switch: ``disable={"bridge_transfer"}``
                             |        | (Settings.sarvam_disabled_capabilities) -> BRIDGE_USER
                             |        | is refused, NEEDS_USER_VERIFICATION + call-back pack.
  bridge_conference / 3-way  | U      | no monitoring after a transfer; same degrade path.
  concurrency                | ?      | our limiters: slot("telephony") + slot("sarvam")
                             |        | (Settings.provider_concurrency); real account limit
                             |        | unknown (question 6).
  custom_llm_turns (mode b)  | U      | not built (see above).

Config (core Settings): sarvam_telephony_auth_id / _auth_token / _base_url (default
https://api.vobiz.ai/api/v1, verified), sarvam_caller_ids (sticky per business).
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
from friday.voice.audio import dtmf_pcm16, pcm16_to_ulaw, resample_pcm16, ulaw_to_pcm16
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
UNVERIFIED_CAPABILITIES: frozenset[str] = frozenset()  # nothing is gated on a flag any more
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
    # VERIFIED (vobiz.ai/docs/concepts/streaming-websockets, /docs/xml/stream/audio-formats):
    # bidirectional="true" is required for playAudio / checkpoint / clearAudio; the <Stream>
    # contentType sets the INBOUND format - L16 at 8 or 16 kHz is supported (24 kHz inbound
    # does not connect). TODO(unverified): keepCallAlive attribute and mu-law inbound.
    return (
        f'<Response>{extra}<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-l16;rate=8000">{escape(ws_url)}</Stream></Response>'
    )


class SarvamCallLeg(TwilioCallLeg):
    """Same VAD -> STT -> classifier pipeline; Plivo/Vobiz stream framing + REST."""

    provider = "sarvam"

    def __init__(self, tel: SarvamTelephony, **kw: Any) -> None:
        super().__init__(tel, **kw)  # type: ignore[arg-type]
        self.tel_s = tel
        self._close: Callable[[], Awaitable[None]] | None = None

    in_encoding = "audio/x-l16"
    in_rate = 8000

    def set_media_format(self, fmt: Mapping[str, Any] | None) -> None:
        """``start.mediaFormat`` {"encoding": "audio/x-l16", "sampleRate": 8000}."""
        if not fmt:
            return
        enc = str(fmt.get("encoding") or fmt.get("contentType") or self.in_encoding).lower()
        self.in_encoding = "audio/x-mulaw" if "mulaw" in enc or "ulaw" in enc else "audio/x-l16"
        with contextlib.suppress(TypeError, ValueError):
            self.in_rate = int(fmt.get("sampleRate") or self.in_rate)

    def on_media(self, payload_b64: str) -> None:
        if self.ended or self.left:
            return
        raw = base64.b64decode(payload_b64)
        if self.in_encoding == "audio/x-mulaw":
            pcm = ulaw_to_pcm16(raw)
            rate = 8000
        else:  # L16 (little-endian signed 16-bit; TODO(vobiz docs): confirm byte order)
            pcm, rate = raw, self.in_rate
        if rate != 8000:
            pcm = resample_pcm16(pcm, rate, 8000)
        for i in range(0, len(pcm) - 319, 320):  # 20 ms frames for the VAD
            for seg in self._segmenter.feed_pcm16(pcm[i : i + 320]):
                self._segments.put_nowait(seg)

    async def clear_audio(self) -> None:
        """Barge-in: drop queued playback (``clearAudio``; Vobiz answers ``clearedAudio``)."""
        if self._send is not None and self.stream_sid:
            await self._send(json.dumps({"event": "clearAudio", "streamId": self.stream_sid}))

    async def _play(self, ulaw: bytes) -> None:
        assert self._send is not None
        for i in range(0, len(ulaw), FRAME_BYTES * 10):
            await self._send(
                json.dumps(
                    {
                        "event": "playAudio",
                        "streamId": self.stream_sid,
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
        try:
            await self.tel_s.rest(
                "POST", f"/Call/{self.provider_call_id}/DTMF/", {"digits": digits}
            )
        except ProviderError as e:
            # Degrade: in-band DTMF tones over the bidirectional stream.
            if self._send is None:
                raise
            log.info("sarvam REST DTMF failed (%s); sending in-band tones", type(e).__name__)
            await self._play(pcm16_to_ulaw(dtmf_pcm16(digits, 8000)))

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
        enable: frozenset[str] | set[str] = frozenset(),
        disable: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        self.enabled = frozenset(enable) & UNVERIFIED_CAPABILITIES
        self.disabled = frozenset(disable)  # ops kill switch, e.g. {"bridge_transfer"}
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
        self.worker_id: str | None = None  # S-9 call pinning
        self.legs: dict[str, SarvamCallLeg] = {}
        self.by_sid: dict[str, SarvamCallLeg] = {}
        self.inbound_legs: dict[str, SarvamCallLeg] = {}
        # VERIFIED (Vobiz API skills / Sarvam Vobiz guide): every request carries the
        # Auth ID and Auth Token (Vobiz console -> Voice -> Voice Applications -> Overview)
        # as X-Auth-ID / X-Auth-Token headers (not HTTP Basic).
        self._http = VendorHTTP(
            "sarvam",
            base_url=base_url.rstrip("/"),
            headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token},
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
        return (CAPABILITIES | self.enabled) - self.disabled

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
        pin = f"&w={self.worker_id}" if self.worker_id else ""
        return f"{base}/voice/sarvam/media?key={key}&token={self.token(f'media:{key}')}{pin}"

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
                "from": from_number,  # E.164; must be a Vobiz number we own / verified caller ID
                "to": request.to_phone,  # E.164, e.g. +91...
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
        sid = body.get("call_uuid") or body.get("request_uuid") or body.get("CallUUID")
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
            leg.set_media_format(start.get("mediaFormat") or msg.get("mediaFormat"))
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
        disable=frozenset(getattr(s, "sarvam_disabled_capabilities", None) or ()),
    )
