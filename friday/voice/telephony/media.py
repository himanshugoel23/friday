"""Energy-based VAD that turns a stream of 20 ms mu-law frames into utterances.

Speech: >= ``start_frames`` loud frames open a segment; ``end_silence_ms`` of quiet
closes it. Sustained audio without pauses (hold music, tones) is cut every
``max_continuous_ms`` so the classifier can label it while the line is on hold.
The noise floor adapts slowly to the line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.voice.audio import rms, ulaw_to_pcm16

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
    max_continuous_ms: int = 6000
    noise_floor: float = 200.0
    _buf: bytearray = field(default_factory=bytearray)
    _voiced_run: int = 0
    _silence_ms: int = 0
    _active: bool = False
    _pre: list[bytes] = field(default_factory=list)

    @property
    def threshold(self) -> float:
        return max(self.min_threshold, self.noise_floor * self.noise_multiplier)

    def feed_ulaw(self, frame: bytes) -> list[Segment]:
        return self.feed_pcm16(ulaw_to_pcm16(frame))

    def feed_pcm16(self, pcm: bytes) -> list[Segment]:
        out: list[Segment] = []
        level = rms(pcm)
        loud = level >= self.threshold
        if not loud and not self._active:
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * level
        if not self._active:
            self._pre = (self._pre + [pcm])[-self.start_frames :]
            self._voiced_run = self._voiced_run + 1 if loud else 0
            if self._voiced_run >= self.start_frames:
                self._active = True
                self._buf = bytearray(b"".join(self._pre))
                self._silence_ms = 0
            return out
        self._buf += pcm
        self._silence_ms = 0 if loud else self._silence_ms + FRAME_MS
        dur_ms = len(self._buf) // 2 * 1000 // self.sample_rate
        if self._silence_ms >= self.end_silence_ms:
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
        return Segment(pcm, self.sample_rate, len(pcm) / 2 / self.sample_rate, forced)
