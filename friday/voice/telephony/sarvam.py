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

Wire protocol: Vobiz Voice API + Vobiz XML (Plivo-like, but NOT identical: see notes).
Friday talks to Vobiz DIRECTLY with its own Auth ID / Token (the founder's Sarvam-rented
number can only be driven by Sarvam's hosted agent and is out of scope).

VERIFIED against the live docs and OpenAPI (vobiz.ai/docs/*.md, vobiz.ai/openapi.json) on
2026-10-08. Pages cited per item; "live" = checked with read-only calls on the real account.
  * Auth + base (api-reference/authentication; live): ``https://api.vobiz.ai/api/v1``, headers
    ``X-Auth-ID`` / ``X-Auth-Token``; path segments are PascalCase (``/Account/{id}/Call/``,
    a lowercase path is a 401). Live read-only: ``/auth/me``, ``/Account/{id}/balance/INR``,
    ``/Account/{id}/numbers`` (see vobiz_probe.py and ``friday check --live``).
  * Make call (call/make-call): ``POST /Account/{id}/Call/`` {from, to, answer_url,
    answer_method, hangup_url, ring_url, machine_detection*, time_limit, hangup_on_ring} ->
    200 {api_id, message "Call fired", request_uuid}; ``request_uuid`` == ``call_uuid``. 200
    means ACCEPTED/QUEUED, not answered. 402 = balance too low, 429 = CPS or concurrency
    exceeded (trial account: CPS 1, 3 concurrent calls). Answer callback: Event=StartApp,
    CallUUID, From, To, CallStatus=in-progress. Hangup callback: Event=Hangup, CallStatus
    =completed, StartTime/AnswerTime/EndTime, HangupCause / HangupCauseCode / HangupCauseName /
    HangupSource (concepts/callbacks, xml/stream/stream-events, cdr).
  * Hangup causes (cdr): NORMAL_CLEARING, USER_BUSY, NO_ANSWER, ORIGINATOR_CANCEL,
    CALL_REJECTED, REJECTED, INVALID_NUMBER, UNALLOCATED_NUMBER, SERVICE_UNAVAILABLE,
    SERVER_ERROR, MEDIA_TIMEOUT, PROTOCOL_ERROR, NETWORK_OUT_OF_ORDER,
    DESTINATION_OUT_OF_ORDER, NORMAL_TEMPORARY_FAILURE, SWITCH_CONGESTION, UNKNOWN. Code 4000 =
    normal, 4010 = "End Of XML Instructions", 6010 = ring timeout (xml/dial).
  * Stream (xml/stream, concepts/streaming-websockets, xml/stream/stream-events):
    ``<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">``.
    Vobiz -> us: ``start`` {start:{callId, streamId, tracks, mediaFormat}}, ``media``
    (20 ms, base64), ``playedStream`` {name}, ``clearedAudio`` {streamId}. There is NO inbound
    ``stop`` and NO ``dtmf`` event: the WebSocket CLOSE is the end of stream (the Hangup
    callback is authoritative). Us -> Vobiz: ``playAudio`` {streamId, media{contentType,
    sampleRate, payload}} (raw mono, no container; L16 at 8/16/24 kHz or mu-law 8 kHz),
    ``checkpoint`` {streamId, name}, ``clearAudio`` {streamId}, ``stop`` {streamId}.
    ``playedStream`` is NOT sent if playback was cleared or failed, so every checkpoint wait has
    a timeout. Inbound formats: L16 8/16 kHz or mu-law 8 kHz (24 kHz inbound does not connect).
    We choose mu-law 8 kHz both ways: the docs do not state the L16 byte order, so mu-law avoids
    the question entirely; ``playAudio`` chunks of 20-60 ms recommended.
  * DTMF send (call/dtmf/send-digits): ``POST /Call/{uuid}/DTMF/`` {digits "0-9*#wW", leg
    "aleg"|"bleg"|"both" (default aleg)} -> 202 "digits sent". On a call Friday placed, the
    called business is the A-leg. DTMF receive: only via the ``<Gather>`` XML verb
    (xml/gather: InputType, Digits, Speech); the media stream carries no DTMF events, so
    Friday cannot hear key presses on the stream (it hears speech via STT).
  * Transfer (call/transfer-call): ``POST /Call/{uuid}/`` {legs "aleg", aleg_url, aleg_method}
    -> 202; the URL returns ``<Dial callerId="+E164 number we own" timeout=..><Number>+E164
    </Number></Dial>`` (xml/dial, xml/dial/number). ``<Dial callbackUrl>`` receives DialAnswer /
    DialConnected / DialHangup events; ``action`` gets DialStatus (completed, busy, failed,
    cancel, timeout, no-answer). It is a TRANSFER: the stream ends when A-leg is redirected.
  * Conference (conference/conference-object, xml/conference): conferences exist only by
    ``<Conference>`` XML on join; REST list/retrieve are known to be unreliable. A 3-way patch
    with Friday monitoring is therefore possible in principle (REST ``POST /Call/{uuid}/Stream/``
    can attach a stream to a leg already in a room, ~2 s after ConferenceEnter) but is NOT
    built; ``bridge_conference`` stays unsupported.
  * Recording (call/record-calls/start-recording, recording): ``POST /Call/{uuid}/Record/``
    {time_limit (DEFAULT 60 s!), file_format mp3|wav, record_channel_type, callback_url} ->
    {recording_id, url}. ``DELETE /Call/{uuid}/Record/`` stops. List/get recordings under
    ``/Recording/``; DELETE ``/Account/{id}/Recording/{recording_id}/`` -> 204 (OpenAPI
    ``delete-recording``). Recording URLs are not public: send X-Auth-ID / X-Auth-Token; hosts
    vary (media/recordings/storage.vobiz.ai) and the real container may differ from the
    extension. Transcription is English only (unused).
  * AMD (call/machine-detection): parameters on make-call, not a separate endpoint.
    ``machine_detection`` "true" (continue) | "hangup", async result to
    ``machine_detection_url`` with Machine (bool), IfMachine, Event=MachineDetection. The
    agent should stay silent during the analysis window (docs warn of misclassification when
    both speak); we use the "Balanced" profile and fall back to "human" when no callback comes.
  * Hang up (call/hangup-call): ``DELETE /Call/{uuid}/`` -> 204; fires hangup_url.
  * Applications (applications): an Application bundles answer_url / hangup_url for a NUMBER;
    needed only for INBOUND calls to a Friday number (point it at /voice/sarvam/inbound and
    /voice/sarvam/hangup). Outbound calls pass per-call answer/hangup URLs.
  * Callbacks (concepts/callbacks): HTTPS only, reply 200 within 3 s, retried up to 3 times
    (handlers are idempotent). Vobiz also signs callbacks (X-Vobiz-Signature-V2/V3, HMAC-SHA256
    with the Auth Token) when credentials are set on the URL; we additionally authenticate with
    our own per-call URL tokens. TODO(optional hardening): verify X-Vobiz-Signature-V3.
  * Account (account/account-object; live): ``features.call_queue`` is TRUE on the founder's
    trial account and must be turned OFF (Vobiz support / console) before real calls; trial
    flag ``is_trial_account``; CPS 1, concurrent calls 3; one shared trial number
    +918065354620; API-streaming rate 0.44 INR/min billed per 60 s; balance INR 25 prepaid.

NOT YET VERIFIED BY A LIVE CALL (needs the founder's go-ahead, see docs/SARVAM_QUESTIONS.md):
the exact answer_url form post fields on a real call, that ``from`` accepts "+91..." vs digits,
whether a trial account may dial arbitrary numbers, STIR/spam labelling of the trial number.

CAPABILITY MATRIX (S = supported, D = degraded, U = unsupported)
Anything D/U has a defined graceful path; the runner reads ``capabilities()`` per call.

  capability                 | status | what we do / degrade to
  ---------------------------|--------|-------------------------------------------------
  brain decides every turn   | S      | we terminate the audio stream; safety + commit gates
                             |        | run in OUR runner whatever the transport.
  DTMF send (IVR)            | S      | REST DTMF; if the REST call fails, in-band tones over the
                             |        | stream. Neither -> IVR task declines before dialling.
  DTMF receive               | U      | no stream event; speech is transcribed instead.
  inbound call-backs         | S      | Application answer_url -> <Stream>; InboundCallReceived.
  missed calls               | S      | Hangup callback without a stream -> MissedCallReceived.
  inbound on retired numbers | S      | any dialled number is accepted and reported.
  many numbers + per-call    | S      | ``from`` per call from the NumberPool; must be a number on
  caller ID                  |        | the account (the probe checks this). Trial: 1 shared number.
  recording                  | S      | REST Record (time_limit set to the call cap) + delete API;
                             |        | a failure leaves recording_url=None, the call goes on.
  amd / voicemail            | S      | async machine_detection_url + our audio classifier.
  bridge_transfer            | S      | REST transfer to <Dial>; Friday leaves the call.
                             |        | Kill switch: ``disable={"bridge_transfer"}``.
  bridge_conference / 3-way  | U      | possible with <Conference> but not built.
  concurrency / CPS          | S      | trial: CPS 1, 3 concurrent; 429 -> retryable error;
                             |        | our limiters: slot("telephony"), slot("sarvam").
  custom_llm_turns (mode b)  | U      | not built.

Config (core Settings): sarvam_telephony_auth_id / _auth_token / _base_url (default
https://api.vobiz.ai/api/v1), sarvam_caller_ids (sticky per business).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
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
from friday.core.models import (
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
    rms,
    ulaw_to_pcm16,
)
from friday.voice.callerid import CallerIdSelector, choose_from_number
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.events import InboundCallReceived, MissedCallReceived
from friday.voice.signals import block_signal
from friday.voice.telephony.exotel import exotel_token as _token
from friday.voice.telephony.media import Segment
from friday.voice.telephony.twilio import FRAME_BYTES, TwilioCallLeg
from friday.voice.text import strip_fillers
from friday.voice.tts.cache import cached_tts

log = get_logger(__name__)

CAPABILITIES = frozenset({
    "outbound", "inbound", "missed_call", "media_stream", "dtmf", "recording", "amd",
    "bridge_transfer",
})  # fmt: skip
UNVERIFIED_CAPABILITIES: frozenset[str] = frozenset()  # nothing is gated on a flag any more
DEFAULT_BASE_URL = "https://api.vobiz.ai/api/v1"  # verified (docs + live)
INBOUND_MESSAGE = (
    "This is Friday, an AI assistant. I called you on behalf of a customer. "
    "I'll call you back shortly. Thank you."
)
# Vobiz CDR hangup causes (vobiz.ai/docs/cdr). Anything else on an unanswered call = no answer.
_HANGUP = {
    "USER_BUSY": DialStatus.BUSY,
    "BUSY": DialStatus.BUSY,
    "NO_ANSWER": DialStatus.NO_ANSWER,
    "NO_USER_RESPONSE": DialStatus.NO_ANSWER,
    "ORIGINATOR_CANCEL": DialStatus.NO_ANSWER,
    "UNALLOCATED_NUMBER": DialStatus.FAILED,
    "INVALID_NUMBER": DialStatus.FAILED,
    "REJECTED": DialStatus.FAILED,
    "CALL_REJECTED": DialStatus.FAILED,
    "SERVICE_UNAVAILABLE": DialStatus.FAILED,
    "SERVER_ERROR": DialStatus.FAILED,
    "DESTINATION_OUT_OF_ORDER": DialStatus.FAILED,
    "NETWORK_OUT_OF_ORDER": DialStatus.FAILED,
    "NORMAL_TEMPORARY_FAILURE": DialStatus.FAILED,
    "SWITCH_CONGESTION": DialStatus.FAILED,
    "MEDIA_TIMEOUT": DialStatus.FAILED,
    "PROTOCOL_ERROR": DialStatus.FAILED,
}
# Balanced AMD profile for AI callers (call/machine-detection).
_AMD_PROFILE = {
    "machine_detection_time": 4000,
    "machine_detection_initial_silence": 4000,
    "machine_detection_initial_greeting": 2500,
    "machine_detection_maximum_words": 5,
    "machine_detection_maximum_speech_length": 4000,
}
_DTMF_OK = re.compile(r"^[0-9*#wW]+$")
SendText = Callable[[str], Awaitable[None]]


_SENTENCE_END = re.compile(r"(?<=[.?!।])\s+")


def split_sentences(text: str, *, min_chars: int = 25, max_parts: int = 4) -> list[str]:
    """Split a reply into a few speakable chunks (tiny pieces merge into the next)."""
    parts: list[str] = []
    for piece in _SENTENCE_END.split(text.strip()):
        if parts and len(parts[-1]) < min_chars:
            parts[-1] = f"{parts[-1]} {piece}"
        else:
            parts.append(piece)
    while len(parts) > max_parts:  # never more vendor calls than needed
        parts[-2] = f"{parts[-2]} {parts[-1]}"
        parts.pop()
    return [p for p in parts if p.strip()]


def sarvam_token(secret: str, scope: str) -> str:
    return _token(secret, f"sarvam:{scope}")


def stream_xml(ws_url: str, *, extra: str = "") -> str:
    # VERIFIED (vobiz.ai/docs/xml/stream, /concepts/streaming-websockets): bidirectional="true"
    # is required for playAudio / checkpoint / clearAudio; keepCallAlive="true" holds the call
    # on the stream; contentType sets the INBOUND format (mu-law 8 kHz, L16 8/16 kHz; never
    # 24 kHz). Mu-law avoids the undocumented L16 byte order.
    return (
        f'<Response>{extra}<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-mulaw;rate=8000">{escape(ws_url)}</Stream></Response>'
    )


def _ring_seconds(params: Mapping[str, str]) -> float:
    """Ring time of an unanswered inbound call: ``Duration`` if sent, else EndTime - StartTime
    (local ``yyyy-MM-dd HH:mm:ss`` per the hangup callback docs)."""
    if params.get("Duration"):
        with contextlib.suppress(ValueError):
            return float(params["Duration"])
    from datetime import datetime

    with contextlib.suppress(KeyError, ValueError):
        fmt = "%Y-%m-%d %H:%M:%S"
        start = datetime.strptime(params["StartTime"], fmt)
        end = datetime.strptime(params["EndTime"], fmt)
        return max(0.0, (end - start).total_seconds())
    return 0.0


class SarvamCallLeg(TwilioCallLeg):
    """Same VAD -> STT -> classifier pipeline; Plivo/Vobiz stream framing + REST."""

    provider = "sarvam"

    def __init__(self, tel: SarvamTelephony, **kw: Any) -> None:
        super().__init__(tel, **kw)  # type: ignore[arg-type]
        self.tel_s = tel
        self._close: Callable[[], Awaitable[None]] | None = None
        self.max_duration_s = 1800
        # Phone speech has pauses: wait longer before closing an utterance, and do not chop a
        # person mid-sentence (the 6 s cut is only for hold music).
        self._segmenter.end_silence_ms = 900
        self._segmenter.max_continuous_ms = 20000
        self._playing = False  # Friday's voice is on the line
        self._barged = False  # the caller spoke over her: do not speak the rest of the turn
        self._loud_run = 0
        self._spec: asyncio.Future[Any] | None = None  # early speech-to-text

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
        else:  # L16 signed 16-bit; byte order undocumented, so we request mu-law (stream_xml)
            pcm, rate = raw, self.in_rate
        if rate != 8000:
            pcm = resample_pcm16(pcm, rate, 8000)
        for i in range(0, len(pcm) - 319, 320):  # 20 ms frames for the VAD
            frame = pcm[i : i + 320]
            if self._playing:
                if self._spec is not None:  # a guess made before she started talking is stale
                    self._spec.cancel()
                    self._spec = None
                self._watch_for_barge_in(frame)
            else:
                self._watch_for_early_pause(frame)
            for seg in self._segmenter.feed_pcm16(frame):
                if self._playing and not self._barged:
                    continue  # her own voice coming back (echo / speakerphone): not the caller
                self._segments.put_nowait(seg)

    EARLY_STT_SILENCE_MS = 340  # start transcribing this long into a pause, before it is final
    EARLY_STT_MIN_S = 0.5

    def _watch_for_early_pause(self, frame: bytes) -> None:
        """Speculative speech-to-text: when the caller pauses, transcribe what they said so far
        while we wait out the rest of the pause. If they carry on, the guess is thrown away."""
        seg = self._segmenter
        if self.hold_mode or not seg._active:
            return
        if rms(frame) >= seg.threshold:
            if self._spec is not None:
                self._spec.cancel()
                self._spec = None
            return
        if self._spec is not None or seg._silence_ms + 20 < self.EARLY_STT_SILENCE_MS:
            return
        pcm = bytes(seg._buf) + frame
        dur = len(pcm) / 2 / seg.sample_rate
        if dur >= self.EARLY_STT_MIN_S:
            snap = Segment(pcm, seg.sample_rate, dur, False)
            self._spec = asyncio.ensure_future(super()._transcribe(snap))

    async def _transcribe(self, seg: Segment) -> Transcription | None:
        spec, self._spec = self._spec, None
        if spec is not None and not seg.forced_cut and not self.hold_mode:
            try:
                return await spec
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - fall back to a fresh pass
                pass
        elif spec is not None:
            spec.cancel()
        return await super()._transcribe(seg)

    BARGE_IN_FRAMES = 15  # 300 ms of clearly loud speech while she talks
    BARGE_IN_LEVEL = 2.5  # times the normal speech threshold, so echo does not interrupt her

    def _watch_for_barge_in(self, frame: bytes) -> None:
        """The caller talks over Friday: stop her voice at once and listen."""
        if self._barged:
            return
        loud = rms(frame) >= self._segmenter.threshold * self.BARGE_IN_LEVEL
        self._loud_run = self._loud_run + 1 if loud else 0
        if self._loud_run >= self.BARGE_IN_FRAMES:
            self._barged = True
            self._loud_run = 0
            task = asyncio.ensure_future(self.clear_audio())
            self.tel_s._bg.add(task)
            task.add_done_callback(self.tel_s._bg.discard)
            for ev in self._marks.values():  # release the playback wait right away
                ev.set()

    def _is_prerendered(self, text: str, language: Language) -> bool:
        tts = self.tel.tts
        mem = getattr(tts, "_mem", None)
        if mem is None or not hasattr(tts, "_key"):
            return False
        clean = strip_fillers(text)
        return tts._key(clean, language, tts.voice_for(language)) in mem

    def _streaming_on(self) -> bool:
        can = getattr(self.tel.tts, "can_stream", None)
        return bool(can and can())

    async def speak(self, text: str, language: Language) -> None:
        if self._barged and (self._segmenter._active or not self._utterances.empty()):
            return  # she was interrupted and the caller is still talking: do not talk over them
        self._barged = False
        parts = split_sentences(strip_fillers(text))
        streaming = self._streaming_on()
        if self._is_prerendered(text, language) or (len(parts) < 2 and not streaming):
            await super().speak(text, language)
            return
        # Start talking after the FIRST sentence is synthesised, while the rest is still being made.
        self._check_live()
        if self.listen_only or self.bridged or self._send is None:
            raise ProviderError("sarvam", "this leg cannot play audio (bridged / listen-only)")
        if streaming and parts:
            await self._speak_streamed(parts, language)
            return
        t0 = time.perf_counter()
        jobs = [asyncio.ensure_future(self._synth(p, language)) for p in parts]
        self._playing = True
        try:
            for n, job in enumerate(jobs):
                pcm = await job
                if n == 0:
                    self.last_tts_ms = (time.perf_counter() - t0) * 1000
                if self._barged:
                    break
                await self._play_audio(pcm16_to_ulaw(pcm), wait=n == len(jobs) - 1)
        finally:
            for j in jobs:
                j.cancel()
            self._end_playback()

    async def _stream_part(
        self, part: str, language: Language, q: asyncio.Queue[Any]
    ) -> None:
        """Producer for one sentence: cached clip, else Sarvam streaming, else REST fallback.
        Puts PCM pieces on ``q``, then ``None`` (or an exception object). Never raises."""
        tts = self.tel.tts
        t0 = time.perf_counter()
        first_ms: float | None = None
        got = 0
        try:
            voice = tts.voice_for(language)
            hit = await tts.lookup(part, language, voice=voice)
            if hit is not None:
                decoded = clip_to_pcm16(hit)
                if decoded is None:
                    raise ProviderError(self.provider, f"cached TTS unsupported ({hit.mime})")
                q.put_nowait(resample_pcm16(decoded[0], decoded[1], 8000))
                return
            clean = strip_fillers(part)
            self.tts_billed_chars += len(clean)
            pcm_all = bytearray()
            resume: str | None = None
            try:
                async for pcm in tts.synthesize_stream(part, language, voice=voice):
                    if first_ms is None:
                        first_ms = (time.perf_counter() - t0) * 1000
                    got += len(pcm)
                    pcm_all += pcm
                    q.put_nowait(pcm)
            except ProviderError as e:
                resume = getattr(e, "resume_text", None)
                if resume is None:
                    resume = "" if got else part
                log.warning(
                    "tts stream failed (%s) after %d bytes; falling back to REST for %d chars",
                    e, got, len(resume),
                )
            if resume:
                if not got:  # nothing was streamed: only the REST call is billed
                    self.tts_billed_chars -= len(clean)
                q.put_nowait(await self._synth(resume, language))
                return
            if resume is None:  # the whole line streamed: next time it is instant
                clip = AudioClip(data=pcm16_to_wav(bytes(pcm_all), 8000), sample_rate=8000)
                await tts.remember(part, language, clip, voice=voice)
                total = (time.perf_counter() - t0) * 1000
                log.info(
                    "tts stream first-audio %.0f ms, total %.0f ms, chars %d, cached=False",
                    first_ms or total, total, len(clean),
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - the consumer decides; the call must not die here
            q.put_nowait(e)
        finally:
            q.put_nowait(None)

    async def _speak_streamed(self, parts: list[str], language: Language) -> None:
        t0 = time.perf_counter()
        queues: list[asyncio.Queue[Any]] = [asyncio.Queue() for _ in parts]
        tasks = [
            asyncio.ensure_future(self._stream_part(p, language, q))
            for p, q in zip(parts, queues, strict=True)
        ]
        self._playing = True
        sent = 0
        first = True
        try:
            for q in queues:
                while True:
                    if self._barged:
                        return
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=0.1)
                    except TimeoutError:
                        continue
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    if self._barged:
                        return
                    if first:
                        first = False
                        self.last_tts_ms = (time.perf_counter() - t0) * 1000
                    ulaw = pcm16_to_ulaw(item)
                    sent += len(ulaw)
                    await self._play_audio(ulaw, wait=False)
            if sent:
                await self._await_checkpoint(sent)
        finally:
            for t in tasks:
                t.cancel()  # also closes any open Sarvam HTTP stream
            self._end_playback()

    async def listen(self, timeout_s: float) -> Transcription | None:
        t = await super().listen(timeout_s)
        self._barged = False
        return t

    def set_hold_mode(self, on: bool) -> None:
        super().set_hold_mode(on)
        self._segmenter.max_continuous_ms = 6000 if on else 20000

    async def clear_audio(self) -> None:
        """Barge-in: drop queued playback (``clearAudio``; Vobiz answers ``clearedAudio``)."""
        if self._send is not None and self.stream_sid:
            await self._send(json.dumps({"event": "clearAudio", "streamId": self.stream_sid}))

    async def _play(self, ulaw: bytes) -> None:
        self._playing = True
        try:
            await self._play_audio(ulaw)
        finally:
            self._end_playback()

    def _end_playback(self) -> None:
        self._playing = False
        self._loud_run = 0
        if not self._barged:  # drop what the line picked up of her own voice
            seg = self._segmenter
            seg._buf = bytearray()
            seg._active = False
            seg._voiced_run = 0
            seg._silence_ms = 0
            seg._pre = []

    async def _play_audio(self, ulaw: bytes, wait: bool = True) -> None:
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
        if not wait:  # more of the same reply follows: keep the audio queue full
            return
        await self._await_checkpoint(len(ulaw))

    async def _await_checkpoint(self, ulaw_len: int) -> None:
        """Ask Vobiz to tell us when everything queued so far has been played."""
        name = f"cp{new_id()[:10]}"
        ev = asyncio.Event()
        self._marks[name] = ev
        await self._send(
            json.dumps({"event": "checkpoint", "streamId": self.stream_sid, "name": name})
        )
        try:
            await asyncio.wait_for(ev.wait(), timeout=ulaw_len / 8000 + 5)
        except TimeoutError:
            self._marks.pop(name, None)
        self._check_live()

    async def send_dtmf(self, digits: str) -> None:
        self._check_live()
        if not self.provider_call_id:
            raise ProviderError("sarvam", "no call id for DTMF")
        if not digits or not _DTMF_OK.match(digits):
            raise ProviderError("sarvam", "DTMF digits must be 0-9 * # w W")
        try:
            # call/dtmf/send-digits: leg aleg = the party Friday dialled (the business).
            await self.tel_s.rest(
                "POST", f"/Call/{self.provider_call_id}/DTMF/", {"digits": digits, "leg": "aleg"}
            )
        except ProviderError as e:
            # Degrade: in-band DTMF tones over the bidirectional stream.
            if self._send is None:
                raise
            log.info("sarvam REST DTMF failed (%s); sending in-band tones", type(e).__name__)
            await self._play(pcm16_to_ulaw(dtmf_pcm16(digits, 8000)))

    async def add_participant(self, phone: str, *, announce: str | None = None) -> SarvamCallLeg:
        """Transfer (no conference): the business leg (A-leg) is redirected to XML that dials
        the user from the same number (call/transfer-call: legs=aleg + aleg_url). Friday cannot
        monitor afterwards."""
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
        self._bg: set[asyncio.Future[Any]] = set()
        self._recording_ids: dict[str, str] = {}  # recording url -> Vobiz recording_id
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
        """Recording hosts vary (media / recordings / storage .vobiz.ai, vobiz.ai/docs/recording/
        download-recording); credentials only ever go to https hosts under the API's own domain."""
        base = urlparse(self._http._client.base_url.__str__())
        u = urlparse(url)
        host = (u.hostname or "").lower()
        root = ".".join((base.hostname or "").lower().split(".")[-2:])
        return (
            u.scheme == "https"
            and bool(host)
            and (
                host == base.hostname
                or (bool(root) and (host == root or host.endswith("." + root)))
            )
        )

    async def fetch_recording(self, url: str) -> bytes | None:
        if not self._own_recording(url):  # never send our credentials to another host
            return None
        return (await self._http.request("GET", url)).content

    async def delete_recording(self, url: str) -> None:
        """SECURITY-14. VERIFIED (openapi ``delete-recording``): ``DELETE /Account/{id}/
        Recording/{recording_id}/`` -> 204. The id comes from the Record response
        (``recording_id``), else from a ``/Recording/{id}`` URL, else from a UUID file name."""
        if not self._own_recording(url):
            raise ProviderError("sarvam", "not a recording of this account")
        rid = self._recording_ids.get(url)
        if not rid:
            m = re.search(r"/Recording/([0-9A-Za-z\-]+)", url) or re.search(
                r"/([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})(?:\.\w+)?(?:\?|$)", url
            )
            rid = m.group(1) if m else None
        if not rid:
            raise ProviderError("sarvam", "cannot tell the recording id from its URL")
        try:
            await self.rest("DELETE", f"/Recording/{rid}/", None)
        except ProviderError as e:
            if "HTTP 404" not in str(e):  # already gone = erased
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
        leg.max_duration_s = request.max_duration_s
        # VERIFIED (call/make-call). 200 = accepted and queued, not answered. ``ring_timeout``
        # appears in the docs' request example; ``hangup_on_ring`` is the documented field.
        body = await self.rest(
            "POST",
            "/Call/",
            {
                "from": from_number,  # E.164; must be a number on this Vobiz account
                "to": request.to_phone,  # E.164 (single destination; "<" separates bulk)
                "answer_url": self.url("answer", key),
                "answer_method": "POST",
                "hangup_url": self.url("hangup", key),
                "hangup_method": "POST",
                "ring_timeout": request.ring_timeout_s,
                "hangup_on_ring": request.ring_timeout_s,
                "time_limit": request.max_duration_s + 1800,  # safety cap after answer
                "machine_detection": "true" if request.metadata.get("role") != "user" else "false",
                "machine_detection_url": self.url("machine", key),
                "machine_detection_method": "POST",
                **_AMD_PROFILE,
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
            # VERIFIED (call/record-calls/start-recording): time_limit defaults to 60 s, so set
            # it to the call cap; response has recording_id + url (auth needed to download).
            body = await self.rest(
                "POST",
                f"/Call/{leg.provider_call_id}/Record/",
                {"time_limit": leg.max_duration_s + 60, "file_format": "mp3"},
            )
            leg.recording = body.get("url") or body.get("recording_url")
            if leg.recording and body.get("recording_id"):
                self._recording_ids[leg.recording] = str(body["recording_id"])
            leg.record_expected = True
            if leg.recording:
                leg._recording_event.set()
        except ProviderError as e:
            log.warning("sarvam recording not started: %s", e)

    async def handle_machine(self, params: Mapping[str, str], key: str | None) -> None:
        leg = self._leg(params, key)
        if (
            leg is not None
            and str(params.get("Machine", "")).lower() == "true"  # Event=MachineDetection
            and leg.status is None
        ):
            leg.status = DialStatus.VOICEMAIL
            leg._status_event.set()

    async def handle_hangup(self, params: Mapping[str, str], key: str | None) -> None:
        """hangup_url: Event=Hangup (the authoritative end-of-call signal; StopStream is not
        sent on caller hangup). Fields: HangupCause(+Code/Name/Source), StartTime, AnswerTime,
        EndTime (call/make-call, concepts/callbacks)."""
        leg = self._leg(params, key)
        if leg is None:
            return
        cause = str(params.get("HangupCause") or params.get("HangupCauseName") or "").upper()
        cause = cause.replace(" ", "_")
        streamed = leg.stream_sid is not None
        answered = streamed or bool(params.get("AnswerTime"))
        if leg.status is None:
            leg.block_signal = block_signal(
                params.get("SipResponseCode"), cause.replace("_", " ")
            ) or ("rejected" if cause in ("CALL_REJECTED", "REJECTED") else None)
            if leg.block_signal:
                leg.status = DialStatus.FAILED
            elif leg.listen_only and cause == "NORMAL_CLEARING":
                leg.status = DialStatus.ANSWERED
            elif cause in _HANGUP:
                leg.status = _HANGUP[cause]
            else:  # NORMAL_CLEARING / 4010 / UNKNOWN: it was a call iff someone answered
                leg.status = DialStatus.ANSWERED if answered else DialStatus.NO_ANSWER
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
                    ring_seconds=_ring_seconds(params),
                    reason="short_ring",
                )
            )

    def transfer_xml(self, params: Mapping[str, str]) -> str:
        """XML the A-leg is redirected to (xml/dial, xml/dial/number). ``callerId`` must be a
        number we own; ``callbackUrl`` reports DialAnswer / DialConnected / DialHangup."""
        to, caller, say = params.get("to", ""), params.get("caller", ""), params.get("say", "")
        key = params.get("key", "")
        speak = f'<Speak voice="WOMAN">{escape(say)}</Speak>' if say else ""
        events = (
            f' callbackUrl={quoteattr(self.url("transfer_events", key))} callbackMethod="POST"'
            if key
            else ""
        )
        return (
            f'<Response>{speak}<Dial callerId={quoteattr(caller)} timeout="45"{events}>'
            f"<Number>{escape(to if to.startswith('+') else '+' + to)}</Number></Dial></Response>"
        )

    async def handle_transfer_status(self, params: Mapping[str, str], key: str | None) -> None:
        """``<Dial callbackUrl>`` events: DialAnswer / DialConnected -> the user picked up;
        DialHangup / action DialStatus busy|failed|no-answer|timeout|cancel -> they did not."""
        leg = self.legs.get(key or "")
        if leg is None or leg.status is not None:
            return
        event = str(params.get("Event", ""))
        dial = str(params.get("DialStatus", "")).lower()
        if event in ("", "DialAnswer", "DialConnected") or dial == "completed":
            leg.status = DialStatus.ANSWERED
        elif dial == "busy":
            leg.status = DialStatus.BUSY
        elif dial in ("no-answer", "timeout", "cancel"):
            leg.status = DialStatus.NO_ANSWER
        elif dial == "failed":
            leg.status = DialStatus.FAILED
        else:
            return  # e.g. a DialHangup after an answer: nothing to change
        leg._status_event.set()

    async def handle_stream_message(
        self,
        msg: dict,
        send: SendText,
        state: dict,
        key: str | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        # VERIFIED event names: start / media / playedStream / clearedAudio (no stop, no dtmf).
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
                # The handler of this event runs the WHOLE call (front door / call-back), so it
                # must not block this receive loop: Vobiz media frames keep arriving meanwhile.
                self._spawn(
                    self._publish(
                        InboundCallReceived(
                            provider=self.name,
                            provider_call_id=leg.provider_call_id,
                            from_phone=leg.to_phone,
                            to_number=leg.from_number,
                        )
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
        elif event == "stop":  # not sent by Vobiz (the WS close is); harmless if it ever is
            leg.on_stream_stop()

    def _spawn(self, coro: Awaitable[Any]) -> None:
        """Run ``coro`` in the background, keeping a reference so it is not garbage collected."""
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _claim_guard(self, leg: SarvamCallLeg) -> None:
        await asyncio.sleep(self.inbound_claim_timeout_s)
        if not leg.claimed and not leg.ended:
            self.inbound_legs.pop(leg.provider_call_id or "", None)
            await leg.play_fixed_message_and_hangup()

    async def _publish(self, event: Any) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def aclose(self) -> None:
        for task in list(self._bg):
            task.cancel()
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
