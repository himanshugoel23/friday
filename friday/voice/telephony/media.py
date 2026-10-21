"""Voice-activity segmenter: turns a stream of 20 ms frames into utterances.

Speech: >= ``start_frames`` speech frames open a segment; ``end_silence_ms`` of quiet
closes it. Sustained audio without pauses (hold music, tones) is cut every
``max_continuous_ms`` so the classifier can label it while the line is on hold.

Which frames count as speech is decided by a ``VadModel`` (``friday/voice/vad``): by default the
energy rule (RMS above an adaptive noise floor, the noise floor adapts slowly to the line); with
``FRIDAY_VOICE_VAD_BACKEND=silero`` a trained neural model supplies a speech probability and the
decision, with automatic fallback to the energy rule if it fails. Everything after that decision
(start frames, end-of-speech wait, padding) is this class, the same for both.

Semantic end-of-turn (default off) can lengthen the wait of ONE pause (``extend_wait``) or hold the
close while the early transcript is being judged (``hold_close``); both are cleared by new speech.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.voice.audio import ulaw_to_pcm16
from friday.voice.vad.base import EnergyVad, VadFrame

log = get_logger(__name__)

FRAME_MS = 20


@dataclass
class Segment:
    pcm16: bytes
    sample_rate: int
    duration_s: float
    forced_cut: bool  # True: no pause found (likely music / continuous tone)


@dataclass
class UtteranceSegmenter:
    sample_rate: int = 8000
    min_threshold: float = 450.0
    noise_multiplier: float = 3.0
    start_frames: int = 3
    end_silence_ms: int = 700
    # Short answers ("haan ji", "nahi") close sooner: saves ~250 ms on every yes/no turn.
    short_end_silence_ms: int = 0  # 0 = off
    short_utterance_ms: int = 1500
    max_continuous_ms: int = 6000
    noise_floor: float = 200.0
    # a trained backend (None = the energy rule above, the default)
    vad: Any = None
    # semantic end-of-turn: the longest a pause may be lengthened / the close held (ms)
    max_extra_wait_ms: int = 1500
    max_hold_ms: int = 800
    _buf: bytearray = field(default_factory=bytearray)
    _voiced_run: int = 0
    _silence_ms: int = 0
    _active: bool = False
    _pre: list[bytes] = field(default_factory=list)
    _extra_wait_ms: int = 0
    _hold_close: bool = False
    _hold_ms: int = 0
    _energy: EnergyVad = field(init=False, repr=False)
    _vad_failed: bool = False

    def __post_init__(self) -> None:
        # the energy rule always runs its noise-floor tracking: it is the default decision, the
        # fallback, and the loudness gate that barge-in uses to ignore her own echo
        self._energy = EnergyVad(self.min_threshold, self.noise_multiplier, self.noise_floor)

    @property
    def threshold(self) -> float:
        """The loudness (RMS) a frame needs to count as speech under the energy rule."""
        return self._energy.threshold

    @property
    def backend(self) -> str:
        return self.vad.name if self.vad is not None else "energy"

    def analyse(self, pcm: bytes) -> VadFrame:
        """Decide speech / not for one frame. Call it ONCE per frame (a neural backend is
        stateful); pass the result to ``feed_pcm16``. Falls back to the energy rule for good if the
        backend raises."""
        vad = self.vad
        if vad is not None:
            try:
                return vad.process(pcm, self.sample_rate)
            except Exception as e:  # noqa: BLE001 - never lose a call over the VAD
                self.vad = None
                self._vad_failed = True
                log.warning("VAD backend %s failed (%s: %s); using the energy rule",
                            vad.name, type(e).__name__, e)
        return self._energy.process(pcm, self.sample_rate)

    def reset_vad(self) -> None:
        if self.vad is not None:
            self.vad.reset()

    # ------------------------------------------------------------ semantic end-of-turn
    def extend_wait(self, ms: int) -> bool:
        """Wait ``ms`` longer than usual before closing the CURRENT pause (not stacking, capped).
        False when no utterance is open. Cleared by the next speech frame and when it closes."""
        if not self._active or ms <= 0:
            return False
        self._extra_wait_ms = min(max(self._extra_wait_ms, ms), self.max_extra_wait_ms)
        return True

    def hold_close(self, on: bool) -> None:
        """While True the utterance is not closed (at most ``max_hold_ms``): the early transcript
        is being judged. Costs nothing for a finished answer (it waits for its transcript)."""
        self._hold_close = bool(on and self._active)
        if not on:
            self._hold_ms = 0

    def feed_ulaw(self, frame: bytes) -> list[Segment]:
        return self.feed_pcm16(ulaw_to_pcm16(frame))

    def feed_pcm16(self, pcm: bytes, frame: VadFrame | None = None) -> list[Segment]:
        out: list[Segment] = []
        fr = frame if frame is not None else self.analyse(pcm)
        level, loud = fr.level, fr.speech
        if not loud and not self._active:
            self._energy.adapt(level)
        if not self._active:
            keep = max(self.start_frames, self.vad.pre_roll_frames if self.vad else 0)
            self._pre = (self._pre + [pcm])[-keep:]
            self._voiced_run = self._voiced_run + 1 if loud else 0
            if self._voiced_run >= self.start_frames:
                self._active = True
                self._buf = bytearray(b"".join(self._pre))
                self._silence_ms = 0
            return out
        self._buf += pcm
        self._silence_ms = 0 if loud else self._silence_ms + FRAME_MS
        if loud:  # new speech: any earlier judgement of the pause is stale
            self._extra_wait_ms = 0
            self._hold_close = False
            self._hold_ms = 0
        dur_ms = len(self._buf) // 2 * 1000 // self.sample_rate
        end_ms = self.end_silence_ms
        if self.short_end_silence_ms and dur_ms - self._silence_ms <= self.short_utterance_ms:
            end_ms = min(end_ms, self.short_end_silence_ms)  # only the speech counts, not the wait
        end_ms += self._extra_wait_ms
        if self._silence_ms >= end_ms and self._hold_close:
            self._hold_ms += FRAME_MS
            if self._hold_ms >= self.max_hold_ms:
                self._hold_close = False
        if self._silence_ms >= end_ms and not self._hold_close:
            out.append(self._emit(forced=False))
        elif dur_ms >= self.max_continuous_ms:
            out.append(self._emit(forced=True))
            self._active = True  # still sounding: keep collecting
        return out

    def flush(self) -> list[Segment]:
        return [self._emit(forced=False)] if self._active and self._buf else []

    def _emit(self, *, forced: bool) -> Segment:
        pcm = bytes(self._buf)
        self._buf = bytearray()
        self._active = forced
        self._voiced_run = 0
        self._silence_ms = 0
        self._pre = []
        self._extra_wait_ms = 0
        self._hold_close = False
        self._hold_ms = 0
        self.reset_vad()
        return Segment(pcm, self.sample_rate, len(pcm) / 2 / self.sample_rate, forced)
