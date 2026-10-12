"""Pick the realtime speech-to-text client for a call (provider-agnostic call leg)."""

from __future__ import annotations

from typing import Any

from friday.voice.stt.sarvam_stream import BaseStreamSTT, SarvamStreamSTT, StreamSTTConfig


def make_stream_stt(cfg: StreamSTTConfig, **callbacks: Any) -> BaseStreamSTT:
    if cfg.provider == "elevenlabs":
        from friday.voice.stt.elevenlabs_stream import ElevenLabsStreamSTT

        return ElevenLabsStreamSTT(cfg, **callbacks)
    return SarvamStreamSTT(cfg, **callbacks)
