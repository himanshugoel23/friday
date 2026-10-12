"""Sarvam realtime streaming speech-to-text (``wss://api.sarvam.ai/speech-to-text-realtime/ws``).

Why: the REST path sends one clip after the caller has stopped, so the caller waits for the
upload, the finaliser and the network. Streaming sends the audio while they speak, and the
words arrive as partials (measured 2026-10-12: the full sentence is in the partials ~250 ms after
the caller stops; the server's own ``transcript.final`` comes ~900 ms after, so Friday acts on a
stable partial for short answers and on the final otherwise).

Protocol (docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws): query params
``language_code, model, stream_type, encoding=mulaw, sample_rate=8000, silence_duration_ms``,
header ``Api-Subscription-Key``; client sends ``{"event":"audio_input","audio":<base64>}``; server
sends ``session.begin``, ``vad.speech_start|end``, ``transcript.partial|final`` (``text``,
``utterance_idx``, ``language``), ``error``, ``session.end``.

This class only speaks the protocol and calls back; the call leg decides what to do with the text.
It never raises into the call: when anything fails ``healthy`` turns False and the leg falls back
to the REST path. Telephony audio is mu-law 8 kHz, sent as it arrives (no resampling).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from friday.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"


@dataclass(frozen=True)
class StreamSTTConfig:
    api_key: str
    provider: str = "sarvam"  # sarvam | elevenlabs (see stt/stream.py)
    model: str = "saaras:v3-realtime"  # measured fastest with accurate Hindi partials
    language_code: str = "hi-IN"  # NOT "auto": auto-detect turns Hindi partials into English
    stream_type: str = "fast"  # partials at low latency
    silence_ms: int = 300  # the server's own end-of-speech wait
    stable_ms: int = 220  # a partial unchanged this long may be acted on (short answers)
    max_words: int = 6  # ...only for answers this short
    url: str = ""  # "" = the vendor default
    connect_timeout_s: float = 3.0
    queue_max: int = 400  # ~8 s of 20 ms frames; beyond this audio is dropped (never blocks)


class BaseStreamSTT:
    """Shared plumbing for a realtime speech-to-text WebSocket (a vendor subclass supplies the
    wire format). Never raises into the call; ``healthy`` False means: use the REST path."""

    name = "base"

    def __init__(
        self,
        cfg: StreamSTTConfig,
        *,
        on_partial: Callable[[str, str | None, int], None] | None = None,
        on_final: Callable[[str, str | None, float | None, int], None] | None = None,
        on_speech_start: Callable[[int], None] | None = None,
        on_speech_end: Callable[[int], None] | None = None,
        connect: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self._connect = connect
        self._ws: Any = None
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=cfg.queue_max)
        self._tasks: list[asyncio.Task] = []
        self.healthy = False
        self.dropped_frames = 0
        self.request_id: str | None = None

    # -- vendor hooks ----------------------------------------------------------------------
    def url(self) -> str:
        raise NotImplementedError

    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    def audio_message(self, frame: bytes) -> str:
        raise NotImplementedError

    def is_ready(self, first: dict[str, Any]) -> bool:
        raise NotImplementedError

    def handle(self, m: dict[str, Any]) -> None:
        raise NotImplementedError

    def end_message(self) -> str:
        return json.dumps({"event": "end"})

    async def start(self) -> bool:
        """Connect and wait for ``session.begin``. True when ready; never raises."""
        try:
            connect = self._connect
            if connect is None:
                import websockets

                connect = websockets.connect
            self._ws = await asyncio.wait_for(
                connect(
                    self.url(),
                    additional_headers=self.headers(),
                    max_size=None,
                ),
                self.cfg.connect_timeout_s,
            )
            first = json.loads(
                await asyncio.wait_for(self._ws.recv(), self.cfg.connect_timeout_s)
            )
            if not self.is_ready(first):
                raise ValueError("unexpected first message from the speech-to-text service")
            self.request_id = first.get("request_id") or first.get("session_id")
        except Exception as e:  # noqa: BLE001 - the call must go on without streaming
            log.warning("stream stt: could not start (%s)", type(e).__name__)
            await self._shutdown()
            return False
        self.healthy = True
        self._tasks = [asyncio.ensure_future(self._reader()), asyncio.ensure_future(self._writer())]
        return True

    def feed(self, ulaw: bytes) -> None:
        """Queue one audio frame (mu-law, 8 kHz). Cheap and non-blocking."""
        if not self.healthy:
            return
        try:
            self._q.put_nowait(ulaw)
        except asyncio.QueueFull:
            self.dropped_frames += 1

    async def _writer(self) -> None:
        try:
            while True:
                frame = await self._q.get()
                if frame is None:
                    return
                await self._ws.send(self.audio_message(frame))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._fail(f"send failed: {type(e).__name__}")

    async def _reader(self) -> None:
        try:
            async for raw in self._ws:
                self.handle(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._fail(f"receive failed: {type(e).__name__}")
            return
        self._fail("closed by the server")

    def _fail(self, why: str) -> None:
        if self.healthy:
            log.warning("stream stt stopped (%s): back to per-utterance speech-to-text", why)
        self.healthy = False

    async def _shutdown(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def aclose(self) -> None:
        self.healthy = False
        with contextlib.suppress(asyncio.QueueFull):
            self._q.put_nowait(None)
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        ws = self._ws
        end = self.end_message()
        if ws is not None and end:
            with contextlib.suppress(Exception):
                await ws.send(end)
        await self._shutdown()


class SarvamStreamSTT(BaseStreamSTT):
    name = "sarvam"

    def url(self) -> str:
        c = self.cfg
        q = {
            "language_code": c.language_code, "model": c.model, "stream_type": c.stream_type,
            "encoding": "mulaw", "sample_rate": "8000", "mode": "transcribe",
            "silence_duration_ms": str(c.silence_ms),
        }
        return f"{c.url or DEFAULT_URL}?{urlencode(q)}"

    def headers(self) -> dict[str, str]:
        return {"Api-Subscription-Key": self.cfg.api_key}

    def audio_message(self, frame: bytes) -> str:
        return json.dumps({"event": "audio_input", "audio": base64.b64encode(frame).decode()})

    def is_ready(self, first: dict[str, Any]) -> bool:
        return first.get("event") == "session.begin"

    def handle(self, m: dict[str, Any]) -> None:
        ev = m.get("event")
        idx = int(m.get("utterance_idx") or 0)
        try:
            if ev == "transcript.partial" and self.on_partial:
                self.on_partial(str(m.get("text") or ""), m.get("language"), idx)
            elif ev == "transcript.final" and self.on_final:
                conf = m.get("language_confidence")
                self.on_final(
                    str(m.get("text") or ""), m.get("language"),
                    float(conf) if conf is not None else None, idx,
                )
            elif ev == "vad.speech_start" and self.on_speech_start:
                self.on_speech_start(idx)
            elif ev == "vad.speech_end" and self.on_speech_end:
                self.on_speech_end(idx)
            elif ev == "error":
                log.warning("stream stt error %s: %s", m.get("code"), str(m.get("message"))[:120])
                if m.get("is_fatal"):
                    self._fail(f"fatal {m.get('code')}")
        except Exception:  # noqa: BLE001 - a callback bug must not kill the stream
            log.exception("stream stt callback failed")
