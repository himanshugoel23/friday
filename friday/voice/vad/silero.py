# ruff: noqa: E501
"""Silero VAD (trained neural voice-activity model) through onnxruntime. Optional, default OFF.

* Model: Silero VAD v5.1.2, ``silero_vad.onnx`` (MIT licence, Copyright (c) 2020-present Silero Team;
  the licence text is next to the file, provenance and hash below and in docs/LATENCY.md).
* Runtime: ``onnxruntime`` + ``numpy`` from the optional extra ``vad`` (``uv sync --extra vad``).
  Without them, or if the model file is missing / its hash differs / it fails to run, ``build_vad``
  returns None and the segmenter keeps using the energy rule; one WARNING is logged and the call goes on.
* Audio: 8 kHz (telephony) uses 256-sample windows (32 ms) with a 32-sample context, 16 kHz 512 with 64
  (the model's own contract). The call leg gives 20 ms frames of 160 samples; the backend buffers them
  into windows and answers every frame with the probability of the newest completed window (at most
  32 ms stale). mu-law is decoded to PCM16 by the leg before it gets here.
* Decision per frame: hysteresis. Speech turns ON at ``start_prob`` and OFF below ``stop_prob``; the
  segmenter then applies its own minimum-speech frames, end-of-speech wait and padding.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.voice.audio import rms
from friday.voice.vad.base import VadFrame, VadModel

log = get_logger(__name__)

MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx"
)
MODEL_SHA256 = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
MODEL_PATH = Path(__file__).resolve().parent / "silero_vad.onnx"
WINDOW = {8000: 256, 16000: 512}
CONTEXT = {8000: 32, 16000: 64}

_lock = threading.Lock()
_session: Any = None
_failed: str | None = None


def available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def file_ok(path: Path = MODEL_PATH) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256
    except OSError:
        return False


def load_session(path: Path = MODEL_PATH) -> Any:
    """The shared onnxruntime session (one per process, one thread: the box has 1 vCPU)."""
    global _session, _failed
    with _lock:
        if _session is not None:
            return _session
        if _failed is not None:
            raise RuntimeError(_failed)
        try:
            if not available():
                raise RuntimeError("onnxruntime / numpy not installed (uv sync --extra vad)")
            if not file_ok(path):
                raise RuntimeError(f"{path.name} missing or its sha256 differs from the pinned hash")
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            _session = ort.InferenceSession(
                str(path), sess_options=opts, providers=["CPUExecutionProvider"]
            )
        except Exception as e:  # noqa: BLE001 - any failure means "use the energy rule"
            _failed = f"{type(e).__name__}: {e}"
            raise RuntimeError(_failed) from e
        return _session


def _reset_for_tests() -> None:
    global _session, _failed
    with _lock:
        _session, _failed = None, None


class SileroVad(VadModel):
    name = "silero"
    pre_roll_frames = 8  # 160 ms: the model needs a moment to be sure, keep the first syllable

    def __init__(
        self, *, sample_rate: int = 8000, start_prob: float = 0.5, stop_prob: float = 0.35,
        session: Any = None,
    ) -> None:
        if sample_rate not in WINDOW:
            raise ValueError("Silero VAD supports 8000 and 16000 Hz only")
        import numpy as np

        self._np = np
        self.sample_rate = sample_rate
        self.start_prob = start_prob
        self.stop_prob = min(stop_prob, start_prob)
        self._session = session or load_session()
        self._window = WINDOW[sample_rate]
        self._ctx_n = CONTEXT[sample_rate]
        self._sr = np.array(sample_rate, dtype=np.int64)
        self.reset()
        self.runs = 0

    def reset(self) -> None:
        np = self._np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self._ctx_n), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._prob = 0.0
        self._on = False

    def _run(self, window: Any) -> float:
        np = self._np
        x = np.concatenate([self._context, window[None, :]], axis=1)
        out, self._state = self._session.run(
            None, {"input": x, "state": self._state, "sr": self._sr}
        )
        self._context = x[:, -self._ctx_n :]
        self.runs += 1
        return float(out[0][0])

    def process(self, pcm16: bytes, sample_rate: int = 8000) -> VadFrame:
        if sample_rate != self.sample_rate:
            raise ValueError(f"this VAD runs at {self.sample_rate} Hz, got {sample_rate}")
        np = self._np
        usable = len(pcm16) - (len(pcm16) % 2)
        if usable:
            pcm = np.frombuffer(pcm16[:usable], dtype="<i2").astype(np.float32) / 32768.0
            self._pending = np.concatenate([self._pending, pcm]) if self._pending.size else pcm
        w = self._window
        while self._pending.size >= w:
            self._prob = self._run(self._pending[:w])
            self._pending = self._pending[w:]
        if self._on:
            self._on = self._prob >= self.stop_prob
        else:
            self._on = self._prob >= self.start_prob
        return VadFrame(self._on, self._prob, rms(pcm16))


def build_vad(
    backend: str = "energy", *, sample_rate: int = 8000, start_prob: float = 0.5,
    stop_prob: float = 0.35,
) -> VadModel | None:
    """The per-call VAD for ``FRIDAY_VOICE_VAD_BACKEND``. None = keep the segmenter's energy rule
    (the default, and the automatic fallback when the model cannot be loaded)."""
    if backend != "silero":
        return None
    try:
        return SileroVad(sample_rate=sample_rate, start_prob=start_prob, stop_prob=stop_prob)
    except Exception as e:  # noqa: BLE001
        log.warning("silero VAD unavailable (%s); using the energy rule", e)
        return None
