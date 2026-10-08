"""Twilio telephony (V-4): REST call control + bidirectional Media Streams.

Outbound::

    place_call -> POST /Calls.json (Twiml = <Connect><Stream url=wss://.../voice/twilio/media>,
                  StatusCallback, Record, MachineDetection) -> TwilioCallLeg
    wait_for_answer  <- status callbacks (+ AnsweredBy machine_* -> VOICEMAIL)
    speak            -> TTS -> 8 kHz mu-law frames on the WebSocket + a "mark"; returns when
                        Twilio echoes the mark (playback finished)
    listen           <- inbound frames -> VAD segments -> STT (+ AudioClassifier) -> queue
    send_dtmf        -> in-band DTMF tones over the same stream (keeps the stream alive)
    add_participant  -> conference upgrade: the callee's call is moved into a conference
                        (with a listen-only <Start><Stream> fork), the user is dialled into
                        the same room after a <Say> whisper; Friday can monitor or leave
    leave / hangup   -> stop monitoring / complete the calls

Inbound (BRIEF E30-35): ``/voice/twilio/inbound`` answers with <Connect><Stream>; when the
stream starts, the leg is parked and ``InboundCallReceived`` published; a final status
without a stream is a ``MissedCallReceived``. Unclaimed answered calls get the fixed P1
message after ``inbound_claim_timeout_s`` (US-16).

Caller ID is sticky per business (``friday.voice.callerid``). All webhooks are signature
checked in ``friday.voice.http`` (``validate_twilio_signature``).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlencode, urlparse
from xml.sax.saxutils import escape, quoteattr

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
from friday.core.models import (
    AudioClass,
    AudioClip,
    DialStatus,
    Language,
    OutboundCallRequest,
    Transcription,
    new_id,
)
from friday.voice._http import VendorHTTP
from friday.voice.audio import (
    clip_to_pcm16,
    dtmf_pcm16,
    pcm16_to_ulaw,
    pcm16_to_wav,
    resample_pcm16,
)
from friday.voice.callerid import CallerIdSelector, choose_from_number, number_pool
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.signals import block_signal
from friday.voice.events import InboundCallReceived, MissedCallReceived
from friday.voice.telephony.media import Segment, UtteranceSegmenter
from friday.voice.tts.cache import cached

log = get_logger(__name__)

TWILIO_API = "https://api.twilio.com"
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}
FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law
INBOUND_MESSAGE = (
    "This is Friday, an AI assistant. I called you on behalf of a customer. "
    "I'll call you back shortly. Thank you."
)
_FINAL = {"completed", "busy", "no-answer", "failed", "canceled"}
_DIAL = {
    "busy": DialStatus.BUSY,
    "no-answer": DialStatus.NO_ANSWER,
    "failed": DialStatus.FAILED,
    "canceled": DialStatus.FAILED,
}

SendText = Callable[[str], Awaitable[None]]


# =============================================================================== helpers


def validate_twilio_signature(
    auth_token: str, url: str, params: Mapping[str, Any], signature: str | None
) -> bool:
    """X-Twilio-Signature = base64(HMAC-SHA1(token, url + sorted(key+value...)))."""
    if not signature:
        return False
    payload = url
    for key in sorted(params):
        values = params[key]
        if isinstance(values, (list, tuple)):
            for v in values:
                payload += f"{key}{v}"
        else:
            payload += f"{key}{values}"
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def sign_twilio(auth_token: str, url: str, params: Mapping[str, Any]) -> str:
    """Compute the signature Twilio would send (tests, local tooling)."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


def _ws_url(base: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


def stream_twiml(ws_url: str, params: dict[str, str], *, pause_s: int = 0) -> str:
    p = "".join(f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>" for k, v in params.items())
    pause = f'<Pause length="{pause_s}"/>' if pause_s else ""
    stream = f"<Stream url={quoteattr(ws_url)}>{p}</Stream>"
    return f"<Response>{pause}<Connect>{stream}</Connect></Response>"


def conference_twiml(
    room: str,
    *,
    monitor_ws: str | None = None,
    monitor_params: dict[str, str] | None = None,
    say: str | None = None,
    end_on_exit: bool = False,
) -> str:
    start = ""
    if monitor_ws:
        p = "".join(
            f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>"
            for k, v in (monitor_params or {}).items()
        )
        start = (
            f'<Start><Stream url={quoteattr(monitor_ws)} track="inbound_track">{p}</Stream></Start>'
        )
    whisper = f'<Say voice="Polly.Kajal-Neural" language="en-IN">{escape(say)}</Say>' if say else ""
    end = "true" if end_on_exit else "false"
    return (
        f'<Response>{start}{whisper}<Dial><Conference beep="false" startConferenceOnEnter="true" '
        f'endConferenceOnExit="{end}">{escape(room)}</Conference></Dial></Response>'
    )


def say_hangup_twiml(text: str) -> str:
    say = f'<Say voice="Polly.Kajal-Neural" language="en-IN">{escape(text)}</Say>'
    return f"<Response>{say}<Hangup/></Response>"


# =============================================================================== leg


class TwilioCallLeg:
    provider = "twilio"

    def __init__(
        self,
        tel: TwilioTelephony,
        *,
        key: str,
        to_phone: str,
        from_number: str | None,
        language: Language = Language.HINGLISH,
        inbound: bool = False,
        listen_only: bool = False,
    ) -> None:
        self.tel = tel
        self.key = key
        self.to_phone = to_phone
        self.from_number = from_number
        self.language = language
        self.inbound = inbound
        self.listen_only = listen_only
        self.provider_call_id: str | None = None
        self.status: DialStatus | None = None
        self.call_status: str | None = None
        self.answered_by: str | None = None
        self.stream_sid: str | None = None
        self.ended = False
        self.left = False
        self.bridged = False
        self.claimed = not inbound
        self.recording: str | None = None
        self.last_stt_ms: float | None = None
        self.last_tts_ms: float | None = None
        self.children: list[TwilioCallLeg] = []
        self._send: SendText | None = None
        self._status_event = asyncio.Event()
        self._stream_event = asyncio.Event()
        self._utterances: asyncio.Queue[Transcription | None] = asyncio.Queue()
        self._segments: asyncio.Queue[Segment | None] = asyncio.Queue()
        self._marks: dict[str, asyncio.Event] = {}
        self._segmenter = UtteranceSegmenter()
        self._worker: asyncio.Task | None = None
        self._stream_started_at: float | None = None
        self.hold_mode = False
        self.block_signal: str | None = None
        self.record_expected = False
        self._recording_event = asyncio.Event()
        self._announcements: dict[str, _SegTranscription] = {}
        self.stt_seconds = 0.0  # audio actually sent to STT (cost ledger)
        self.tts_billed_chars = 0  # TTS characters not served from the cache

    # ------------------------------------------------------------------ webhook side
    def on_status(self, params: Mapping[str, str]) -> None:
        status = params.get("CallStatus", "")
        self.call_status = status
        self.provider_call_id = self.provider_call_id or params.get("CallSid")
        self.answered_by = params.get("AnsweredBy") or self.answered_by
        if status == "in-progress" and self.status is None:
            machine = (self.answered_by or "").startswith("machine") or self.answered_by == "fax"
            self.status = DialStatus.VOICEMAIL if machine else DialStatus.ANSWERED
            self._status_event.set()
        elif status in _FINAL:
            if self.status is None:
                self.block_signal = block_signal(
                    params.get("SipResponseCode"), params.get("ErrorMessage")
                )
                self.status = _DIAL.get(
                    status, DialStatus.NO_ANSWER if status == "completed" else DialStatus.FAILED
                )
                if self.block_signal:
                    self.status = DialStatus.FAILED
            self._end()
            self._status_event.set()

    def attach_stream(self, stream_sid: str, send: SendText) -> None:
        self.stream_sid = stream_sid
        self._send = send
        self._stream_started_at = time.perf_counter()
        if self.status is None:
            self.status = DialStatus.ANSWERED
            self._status_event.set()
        self._stream_event.set()
        if self._worker is None:
            self._worker = asyncio.ensure_future(self._transcribe_worker())

    def attach_monitor(self, stream_sid: str) -> None:
        self.stream_sid = stream_sid
        self._send = None
        self._stream_event.set()
        if self._worker is None:
            self._worker = asyncio.ensure_future(self._transcribe_worker())

    def on_media(self, payload_b64: str) -> None:
        if self.ended or self.left:
            return
        for seg in self._segmenter.feed_ulaw(base64.b64decode(payload_b64)):
            self._segments.put_nowait(seg)

    def on_mark(self, name: str) -> None:
        ev = self._marks.pop(name, None)
        if ev:
            ev.set()

    def on_stream_stop(self) -> None:
        for seg in self._segmenter.flush():
            self._segments.put_nowait(seg)
        self._send = None
        if not self.bridged:
            self._end()

    def _end(self) -> None:
        if self.ended:
            return
        self.ended = True
        self._utterances.put_nowait(None)
        self._segments.put_nowait(None)
        for ev in self._marks.values():
            ev.set()

    async def _transcribe_worker(self) -> None:
        while True:
            seg = await self._segments.get()
            if seg is None:
                return
            try:
                t = await self._transcribe(seg)
            except Exception as e:  # noqa: BLE001 - STT hiccup: drop this chunk
                log.warning("twilio leg STT failed: %r", e)
                continue
            if t is not None:
                self._utterances.put_nowait(t)

    async def _transcribe(self, seg: Segment) -> Transcription | None:
        clip = AudioClip(
            data=pcm16_to_wav(seg.pcm16, seg.sample_rate),
            mime="audio/wav",
            sample_rate=seg.sample_rate,
        )
        t0 = time.perf_counter()
        if seg.forced_cut or self.hold_mode:  # classify locally first; never STT music
            cls = await self.tel.classifier.classify(clip)
            # on hold only speech-like audio may reach STT (a human / announcement)
            non_speech = cls.audio_class != AudioClass.HUMAN and (
                self.hold_mode or cls.audio_class in (AudioClass.HOLD_MUSIC, AudioClass.SILENCE)
            )
            if non_speech:
                kind = (
                    AudioClass.SILENCE
                    if cls.audio_class == AudioClass.SILENCE
                    else AudioClass.HOLD_MUSIC
                )
                return _SegTranscription(text="", audio_class=kind, duration_s=seg.duration_s)
        fp = _fingerprint(seg.pcm16) if self.hold_mode else None
        if fp is not None and fp in self._announcements:  # looping queue message
            return self._announcements[fp].model_copy(update={"duration_s": seg.duration_s})
        stt = await self.tel.stt.transcribe(clip, language_hint=self.language)
        self.stt_seconds += seg.duration_s
        self.last_stt_ms = (time.perf_counter() - t0) * 1000
        combine = getattr(self.tel.classifier, "combine", None)
        if combine is not None:
            cls = await combine(clip, stt.text)
        else:
            cls = await self.tel.classifier.classify(clip)
        if not stt.text and cls.audio_class in (AudioClass.SILENCE, AudioClass.UNKNOWN):
            return None
        out = _SegTranscription(
            text=stt.text,
            language=stt.language,
            confidence=stt.confidence,
            audio_class=cls.audio_class,
            duration_s=seg.duration_s,
        )
        if fp is not None and cls.audio_class == AudioClass.QUEUE_ANNOUNCEMENT:
            self._announcements[fp] = out
        return out

    # ------------------------------------------------------------------ CallLeg
    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        try:
            await asyncio.wait_for(self._status_event.wait(), timeout=timeout_s + 10)
        except TimeoutError:
            await self._complete_call()
            self.status = DialStatus.NO_ANSWER
            self._end()
            return self.status
        if self.status == DialStatus.ANSWERED:
            try:
                await asyncio.wait_for(self._stream_event.wait(), timeout=10)
            except TimeoutError:
                log.warning("twilio media stream never connected for %s", self.key)
                await self._complete_call()
                self.status = DialStatus.FAILED
                self._end()
        elif self.status == DialStatus.VOICEMAIL:
            await self._complete_call()
        return self.status or DialStatus.FAILED

    def _check_live(self) -> None:
        if self.ended or self.left:
            raise CallEnded()

    async def speak(self, text: str, language: Language) -> None:
        self._check_live()
        if self.listen_only or self.bridged or self._send is None:
            raise ProviderError("twilio", "this leg cannot play audio (bridged / listen-only)")
        pcm = await self._synth(text, language)
        await self._play(pcm16_to_ulaw(pcm))

    async def _synth(self, text: str, language: Language) -> bytes:
        """TTS (through the pre-render cache when present) -> 8 kHz PCM16."""
        tts = self.tel.tts
        t0 = time.perf_counter()
        voice = tts.voice_for(language)
        cached = getattr(tts, "synthesize_cached", None)
        if cached is not None:
            clip, hit = await cached(text, language, voice=voice)
        else:
            clip, hit = await tts.synthesize(text, language, voice=voice), False
        if not hit:
            self.tts_billed_chars += len(text)
        self.last_tts_ms = (time.perf_counter() - t0) * 1000
        decoded = clip_to_pcm16(clip)
        if decoded is None:
            raise ProviderError(self.provider, f"TTS returned unsupported audio ({clip.mime})")
        pcm, rate = decoded
        return resample_pcm16(pcm, rate, 8000)

    def set_hold_mode(self, on: bool) -> None:
        """Hold-listening: no STT on music; repeated announcements reuse a cached result."""
        self.hold_mode = on

    async def _play(self, ulaw: bytes) -> None:
        assert self._send is not None
        for i in range(0, len(ulaw), FRAME_BYTES):
            payload = base64.b64encode(ulaw[i : i + FRAME_BYTES]).decode()
            await self._send(
                json.dumps(
                    {"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}
                )
            )
        name = f"m{new_id()[:10]}"
        ev = asyncio.Event()
        self._marks[name] = ev
        await self._send(
            json.dumps({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
        )
        try:
            await asyncio.wait_for(ev.wait(), timeout=len(ulaw) / 8000 + 5)
        except TimeoutError:
            self._marks.pop(name, None)
        self._check_live()

    async def listen(self, timeout_s: float) -> Transcription | None:
        if self.ended and self._utterances.empty():
            raise CallEnded()
        if self.left:
            raise CallEnded()
        try:
            item = await asyncio.wait_for(self._utterances.get(), timeout=timeout_s)
        except TimeoutError:
            return None
        if item is None:
            raise CallEnded()
        return item

    async def send_dtmf(self, digits: str) -> None:
        self._check_live()
        if self._send is None or self.bridged:
            raise ProviderError("twilio", "cannot send DTMF without an active media stream")
        await self._play(pcm16_to_ulaw(dtmf_pcm16(digits, 8000)))

    async def add_participant(self, phone: str, *, announce: str | None = None) -> TwilioCallLeg:
        self._check_live()
        if not self.provider_call_id:
            raise ProviderError("twilio", "call has no CallSid yet")
        room = f"friday-{self.key}"
        ws = self.tel.media_ws_url
        # 1) move the callee into the conference, keep a listen-only fork for monitoring
        self.bridged = True
        self._send = None
        await self.tel.update_call(
            self.provider_call_id,
            conference_twiml(
                room, monitor_ws=ws, monitor_params=self.tel.stream_params(self.key, role="monitor")
            ),
        )
        # 2) dial the user into the same room (whisper first, US-26.2)
        user_key = new_id()
        user = TwilioCallLeg(
            self.tel, key=user_key, to_phone=phone, from_number=self.from_number, listen_only=True
        )
        self.tel.legs[user_key] = user
        self.children.append(user)
        twiml = conference_twiml(
            room,
            monitor_ws=ws,
            monitor_params=self.tel.stream_params(user_key, role="monitor"),
            say=announce,
            end_on_exit=True,
        )
        sid = await self.tel.create_call(
            to=phone,
            from_=self.from_number,
            twiml=twiml,
            key=user_key,
            ring_s=25,
            record=False,
            amd=False,
        )
        user.provider_call_id = sid
        self.tel.by_sid[sid] = user
        return user

    async def leave(self) -> None:
        if not self.bridged:
            await self.hangup()
            return
        self.left = True  # calls stay in the conference; we stop listening
        self._end()

    async def hangup(self) -> None:
        if self.ended and not self.bridged:
            return
        await self._complete_call()
        for child in self.children:
            await child._complete_call()
            child._end()
        self._end()

    async def _complete_call(self) -> None:
        if self.provider_call_id:
            try:
                await self.tel.update_call(self.provider_call_id, status="completed")
            except ProviderError as e:
                log.debug("complete call failed: %s", e)

    async def recording_url(self) -> str | None:
        return self.recording

    async def wait_recording(self, timeout_s: float) -> None:
        """The recording callback usually arrives a few seconds after hang-up."""
        if self.record_expected and self.recording is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._recording_event.wait(), timeout=timeout_s)

    async def fetch_recording(self, url: str) -> bytes | None:
        return await self.tel.fetch_recording(url)

    # inbound helpers
    async def play_fixed_message_and_hangup(self, text: str = INBOUND_MESSAGE) -> None:
        if self.provider_call_id:
            await self.tel.update_call(self.provider_call_id, say_hangup_twiml(text))
        self._end()


class _SegTranscription(Transcription):
    duration_s: float | None = None


def _fingerprint(pcm16: bytes, bucket_ms: int = 100) -> str:
    """Coarse loudness envelope -> identical looping recordings hash the same."""
    from friday.voice.audio import frame_features

    feats = frame_features(pcm16, 8000, bucket_ms)
    env = "".join(chr(48 + min(9, int(e // 1500))) for e, _ in feats)
    return f"{len(feats) // 5}:{env[:60]}"


# =============================================================================== provider


class TwilioTelephony:
    name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str | None,
        public_base_url: str,
        stt: STTProvider,
        tts: TTSProvider,
        classifier: AudioClassifier | None = None,
        bus: EventBus | None = None,
        clock: Clock | None = None,
        friday_numbers: list[str] | None = None,
        record: bool = True,
        inbound_claim_timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.public_base_url = public_base_url.rstrip("/")
        self.stt = stt
        self.tts = tts
        self.classifier = classifier or HeuristicAudioClassifier()
        self.bus = bus
        self.clock = clock
        self.friday_numbers = friday_numbers or ([from_number] if from_number else [])
        self.record = record
        self.inbound_claim_timeout_s = inbound_claim_timeout_s
        self.caller_id_selector: CallerIdSelector | None = None
        self.legs: dict[str, TwilioCallLeg] = {}
        self.by_sid: dict[str, TwilioCallLeg] = {}
        self.inbound_legs: dict[str, TwilioCallLeg] = {}
        auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        self._http = VendorHTTP(
            "twilio",
            base_url=TWILIO_API,
            headers={"Authorization": f"Basic {auth}"},
            transport=transport,
        )

    # ------------------------------------------------------------------ urls
    @property
    def media_ws_url(self) -> str:
        return _ws_url(self.public_base_url) + "/voice/twilio/media"

    def _cb(self, path: str, key: str) -> str:
        return f"{self.public_base_url}/voice/twilio/{path}?key={key}"

    # ------------------------------------------------------------------ REST
    async def create_call(
        self,
        *,
        to: str,
        from_: str | None,
        twiml: str,
        key: str,
        ring_s: int = 30,
        record: bool = True,
        amd: bool = True,
    ) -> str:
        if not from_:
            raise ProviderError("twilio", "no Friday caller ID configured (TWILIO_FROM_NUMBER)")
        data: list[tuple[str, str]] = [
            ("To", to),
            ("From", from_),
            ("Twiml", twiml),
            ("Timeout", str(ring_s)),
            ("StatusCallback", self._cb("status", key)),
            ("StatusCallbackMethod", "POST"),
        ]
        data += [
            ("StatusCallbackEvent", e) for e in ("initiated", "ringing", "answered", "completed")
        ]
        if record:
            data += [
                ("Record", "true"),
                ("RecordingStatusCallback", self._cb("recording", key)),
                ("RecordingStatusCallbackMethod", "POST"),
            ]
        if amd:
            data += [("MachineDetection", "Enable")]
        resp = await self._http.request(
            "POST",
            f"/2010-04-01/Accounts/{self.account_sid}/Calls.json",
            content=urlencode(data),
            headers=_FORM,
        )
        sid = resp.json().get("sid")
        if not sid:
            raise ProviderError("twilio", "no call sid in response")
        return sid

    async def update_call(
        self, sid: str, twiml: str | None = None, *, status: str | None = None
    ) -> None:
        data: dict[str, str] = {}
        if twiml:
            data["Twiml"] = twiml
        if status:
            data["Status"] = status
        await self._http.request(
            "POST",
            f"/2010-04-01/Accounts/{self.account_sid}/Calls/{sid}.json",
            content=urlencode(data),
            headers=_FORM,
        )

    # ------------------------------------------------------------------ TelephonyProvider
    async def place_call(self, request: OutboundCallRequest) -> TwilioCallLeg:
        from_number = choose_from_number(request, self.friday_numbers, self.caller_id_selector)
        key = new_id()
        leg = TwilioCallLeg(
            self,
            key=key,
            to_phone=request.to_phone,
            from_number=from_number,
            language=request.language,
        )
        self.legs[key] = leg
        twiml = stream_twiml(self.media_ws_url, self.stream_params(key, direction="outbound"))
        sid = await self.create_call(
            to=request.to_phone,
            from_=from_number,
            twiml=twiml,
            key=key,
            ring_s=request.ring_timeout_s,
            record=request.record and self.record,
            amd=request.metadata.get("role") != "user",
        )
        leg.provider_call_id = sid
        leg.record_expected = request.record and self.record
        self.by_sid[sid] = leg
        log.info(
            "twilio call %s -> %s from %s",
            sid,
            mask_phone(request.to_phone),
            mask_phone(from_number),
        )
        return leg

    # ------------------------------------------------------------------ stream auth
    def stream_token(self, key: str) -> str:
        """SECURITY-18: per-call secret for the Media Streams socket. Only Twilio (via the
        TwiML we returned) and we know ``key``; the token proves it was issued by us."""
        mac = hmac.new(self.auth_token.encode(), f"twilio-stream|{key}".encode(), hashlib.sha256)
        return mac.hexdigest()

    def stream_params(self, key: str, **extra: str) -> dict[str, str]:
        return {"key": key, "token": self.stream_token(key), **extra}

    def _stream_authorised(self, params: Mapping[str, str]) -> TwilioCallLeg | None:
        key = params.get("key") or ""
        token = params.get("token") or ""
        leg = self.legs.get(key)
        if leg is None or not hmac.compare_digest(self.stream_token(key), token):
            return None
        return leg

    # ------------------------------------------------------------------ recordings
    @staticmethod
    def _recording_sid(url: str) -> str | None:
        m = re.search(r"/Recordings/(RE[0-9A-Za-z]+)", url)
        return m.group(1) if m else None

    def _own_recording(self, url: str) -> bool:
        u = urlparse(url)
        return (
            u.scheme == "https"
            and u.hostname == "api.twilio.com"
            and f"/Accounts/{self.account_sid}/" in u.path
        )

    async def fetch_recording(self, url: str) -> bytes | None:
        if not self._own_recording(url):  # never send our credentials anywhere else
            return None
        resp = await self._http.request("GET", url)
        return resp.content

    async def delete_recording(self, url: str) -> None:
        """SECURITY-14: erase a recording at Twilio (already gone == success)."""
        sid = self._recording_sid(url)
        if not sid or not self._own_recording(url):
            raise ProviderError("twilio", "not a Twilio recording of this account")
        try:
            await self._http.request(
                "DELETE", f"/2010-04-01/Accounts/{self.account_sid}/Recordings/{sid}.json"
            )
        except ProviderError as e:
            if "HTTP 404" not in str(e):
                raise

    def capabilities(self) -> frozenset[str]:
        return frozenset({"outbound", "inbound", "missed_call", "media_stream", "dtmf",
                          "recording", "amd", "bridge_transfer", "bridge_conference"})  # fmt: skip

    def take_inbound(self, provider_call_id: str) -> TwilioCallLeg | None:
        leg = self.inbound_legs.pop(provider_call_id, None)
        if leg is not None:
            leg.claimed = True
        return leg

    # ------------------------------------------------------------------ webhooks
    def _leg_for(self, params: Mapping[str, str], key: str | None) -> TwilioCallLeg | None:
        if key and key in self.legs:
            return self.legs[key]
        sid = params.get("CallSid")
        return self.by_sid.get(sid) if sid else None

    async def handle_status(self, params: Mapping[str, str], key: str | None = None) -> None:
        leg = self._leg_for(params, key)
        if leg is None:
            return
        was_streaming = leg.stream_sid is not None
        leg.on_status(params)
        if leg.inbound and params.get("CallStatus") in _FINAL and not was_streaming:
            self.inbound_legs.pop(leg.provider_call_id or "", None)
            await self._publish(
                MissedCallReceived(
                    provider=self.name,
                    provider_call_id=params.get("CallSid"),
                    from_phone=params.get("From", leg.to_phone),
                    to_number=params.get("To"),
                    ring_seconds=float(params.get("CallDuration") or 0),
                    reason="no_answer"
                    if params.get("CallStatus") == "no-answer"
                    else "caller_hung_up",
                )
            )

    async def handle_recording(self, params: Mapping[str, str], key: str | None = None) -> None:
        leg = self._leg_for(params, key)
        url = params.get("RecordingUrl")
        if leg is not None and url and params.get("RecordingStatus", "completed") == "completed":
            leg.recording = url + ".mp3"
            leg._recording_event.set()

    def inbound_twiml(self, params: Mapping[str, str]) -> str:
        """Answer an inbound call on a Friday number: connect the media stream."""
        sid = params.get("CallSid", new_id())
        key = new_id()
        leg = TwilioCallLeg(
            self,
            key=key,
            to_phone=params.get("From", "anonymous"),
            from_number=params.get("To"),
            inbound=True,
        )
        leg.provider_call_id = sid
        self.legs[key] = leg
        self.by_sid[sid] = leg
        return stream_twiml(
            self.media_ws_url, self.stream_params(key, direction="inbound"), pause_s=1
        )

    async def handle_stream_message(self, msg: dict, send: SendText, state: dict) -> None:
        """One Twilio Media Streams WebSocket message (``state`` is per-socket)."""
        event = msg.get("event")
        if event == "start":
            start = msg.get("start", {})
            params = start.get("customParameters", {})
            leg = self._stream_authorised(params)
            if leg is None:  # SECURITY-18: no key/token -> no audio, whatever the callSid
                log.warning("rejected media stream without a valid per-call token")
                return
            if params.get("role") == "monitor":  # listen-only fork after bridging
                state["leg"] = leg
                leg.attach_monitor(msg.get("streamSid") or start.get("streamSid"))
                return
            if leg.stream_sid is not None:  # a second start for an attached leg
                log.warning("rejected a second media stream for an attached call")
                return
            state["leg"] = leg
            leg.attach_stream(msg.get("streamSid") or start.get("streamSid"), send)
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

    async def _claim_guard(self, leg: TwilioCallLeg) -> None:
        await asyncio.sleep(self.inbound_claim_timeout_s)
        if not leg.claimed and not leg.ended:
            self.inbound_legs.pop(leg.provider_call_id or "", None)
            log.info(
                "unclaimed inbound call from %s: playing fixed message", mask_phone(leg.to_phone)
            )
            try:
                await leg.play_fixed_message_and_hangup()
            except ProviderError as e:
                log.warning("could not play inbound message: %s", e)

    async def _publish(self, event) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def aclose(self) -> None:
        await self._http.aclose()


def build_twilio(c: Container) -> Any:
    """Factory for FACTORIES["telephony"]["twilio"]; honours FRIDAY_TELEPHONY_ROUTE."""
    from friday.voice.telephony.routing import build_routed_telephony, route_from_env

    if route_from_env():
        return build_routed_telephony(c)
    return build_twilio_direct(c)


def build_twilio_direct(c: Container) -> TwilioTelephony:
    s = c.settings
    if not (s.twilio_account_sid and s.twilio_auth_token):
        raise ProviderError("twilio", "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")
    try:
        classifier = c.audio_classifier
    except Exception:  # noqa: BLE001
        classifier = HeuristicAudioClassifier()
    return TwilioTelephony(
        account_sid=s.twilio_account_sid,
        auth_token=s.twilio_auth_token.get_secret_value(),
        from_number=s.twilio_from_number,
        public_base_url=s.public_base_url,
        stt=c.stt,
        tts=cached(c.tts, s.media_dir),
        classifier=classifier,
        bus=c.bus,
        clock=c.clock,
        friday_numbers=number_pool(s, [s.twilio_from_number]),
        record=s.call_record,
    )
