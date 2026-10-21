"""The voice-activity interface and the default (energy) backend.

``VadModel.process(pcm16, sample_rate)`` is called once per audio frame (the call leg feeds 20 ms
frames) and answers a ``VadFrame``: is there speech in it, how likely (a neural backend), and the
loudness. The segmenter (``friday/voice/telephony/media.py``) owns everything after that: the
start / stop counts, the end-of-speech wait, the padding. A backend only decides "speech or not" for
a frame, so the energy rule and a trained model are interchangeable.

The ``EnergyVad`` is the rule the product has always used, moved here unchanged: a frame is speech
when its RMS is at least ``max(min_threshold, noise_floor * noise_multiplier)``, and the noise floor
adapts slowly to the line while nothing is being said.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from friday.voice.audio import rms


@dataclass(frozen=True)
class VadFrame:
    speech: bool  # the backend's decision for this frame (after its own hysteresis)
    prob: float | None  # speech probability 0..1 (None for the energy rule)
    level: float  # RMS of the frame, PCM16 units


class VadModel(ABC):
    """One instance per call: a neural backend carries recurrent state between frames."""

    name = "base"

    @abstractmethod
    def process(self, pcm16: bytes, sample_rate: int = 8000) -> VadFrame: ...

    def reset(self) -> None:  # noqa: B027 - optional hook
        """Forget recurrent state (a new utterance, or her own voice was just playing)."""

    # extra frames of audio kept BEFORE the first speech frame, on top of the segmenter's own
    pre_roll_frames = 0


class EnergyVad(VadModel):
    """The loudness rule (default). Identical numbers to the pre-VAD-interface segmenter."""

    name = "energy"

    def __init__(
        self, min_threshold: float = 450.0, noise_multiplier: float = 3.0,
        noise_floor: float = 200.0,
    ) -> None:
        self.min_threshold = min_threshold
        self.noise_multiplier = noise_multiplier
        self.noise_floor = noise_floor

    @property
    def threshold(self) -> float:
        return max(self.min_threshold, self.noise_floor * self.noise_multiplier)

    def process(self, pcm16: bytes, sample_rate: int = 8000) -> VadFrame:
        level = rms(pcm16)
        return VadFrame(level >= self.threshold, None, level)

    def adapt(self, level: float) -> None:
        """The line is quiet and no utterance is open: follow its noise level slowly."""
        self.noise_floor = 0.95 * self.noise_floor + 0.05 * level
