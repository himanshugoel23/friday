"""ElevenLabs realtime speech-to-text (Scribe v2 realtime) for live calls.

``wss://api.elevenlabs.io/v1/speech-to-text/realtime`` with ``audio_format=ulaw_8000`` (the phone's
own format, no conversion), ``language_code=hi``, ``commit_strategy=vad``. Client sends
``{"message_type":"input_audio_chunk","audio_base_64":...,"sample_rate":8000}``; server sends
``session_started``, ``partial_transcript`` (text so far), ``committed_transcript`` (final for the
segment). Measured 2026-10-12 (docs/LATENCY.md): committed 620-880 ms after the caller stops
(vad silence 0.3 s), and the partials are stable (they do not drift while the caller is silent), so
the call leg can act on an unchanged partial of a short answer well before the commit.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

from friday.core.logging import get_logger
from friday.voice.stt.sarvam_stream import BaseStreamSTT

log = get_logger(__name__)

DEFAULT_URL = "wss://api.elevenlabs.io"


class ElevenLabsStreamSTT(BaseStreamSTT):
    name = "elevenlabs"

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._idx = 0  # the service has no utterance index: one per committed transcript

    def url(self) -> str:
        c = self.cfg
        q = {
            "model_id": "scribe_v2_realtime", "audio_format": "ulaw_8000",
            "language_code": c.language_code.split("-")[0].lower(),
            "commit_strategy": "vad", "vad_silence_threshold_secs": f"{c.silence_ms / 1000:.2f}",
        }
        return f"{c.url or DEFAULT_URL}/v1/speech-to-text/realtime?{urlencode(q)}"

    def headers(self) -> dict[str, str]:
        return {"xi-api-key": self.cfg.api_key}

    def audio_message(self, frame: bytes) -> str:
        return json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(frame).decode(),
            "sample_rate": 8000,
        })

    def is_ready(self, first: dict[str, Any]) -> bool:
        return first.get("message_type") == "session_started"

    def end_message(self) -> str:
        return ""  # closing the socket is enough

    def handle(self, m: dict[str, Any]) -> None:
        t = str(m.get("message_type") or "")
        try:
            if t == "partial_transcript" and self.on_partial:
                self.on_partial(str(m.get("text") or ""), None, self._idx)
            elif t == "committed_transcript":
                idx = self._idx
                self._idx += 1
                if self.on_final:
                    self.on_final(str(m.get("text") or ""), None, None, idx)
            elif t.endswith("error") or t in ("quota_exceeded", "rate_limited", "unauthorized"):
                log.warning("elevenlabs stt %s: %s", t, str(m.get("error") or m)[:120])
                self._fail(t)
        except Exception:  # noqa: BLE001 - a callback bug must not kill the stream
            log.exception("elevenlabs stt callback failed")
