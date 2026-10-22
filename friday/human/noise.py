# ruff: noqa: E501
"""Noise handling: estimate the line's background noise and adapt the voice detector.

``NoiseTracker`` is fed one RMS level per 20 ms frame (plus the detector's speech flag, and whether
Friday herself is talking, in which case the frame is ignored so her echo never counts as noise).
Noise floor = a slow average of non-speech frames; speech level = average of speech frames; the
difference is the SNR in dB. ``params_for`` maps the noise class to safer thresholds: a stricter
speech-start probability, a longer end-of-speech wait, a less touchy barge-in. ``NoiseGate`` decides
whether a transcript is pure noise (do not answer it), asks for a repeat with the EXISTING line
"Sorry, ek baar phir?", and after 2 failed attempts gives up with the existing safe-exit line.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

CLASSES = ("clean", "moderate", "noisy", "very_noisy")


@dataclass(frozen=True)
class NoiseParams:
    klass: str
    start_prob_delta: float
    end_silence_ms: int
    barge_level: float  # times the speech threshold
    barge_frames: int  # loud frames needed in the 12-frame window


_PARAMS = {
    "clean": NoiseParams("clean", 0.0, 900, 1.6, 7),
    "moderate": NoiseParams("moderate", 0.05, 1000, 1.9, 7),
    "noisy": NoiseParams("noisy", 0.12, 1150, 2.3, 8),
    "very_noisy": NoiseParams("very_noisy", 0.2, 1300, 2.8, 9),
}


def params_for(klass: str) -> NoiseParams:
    return _PARAMS.get(klass, _PARAMS["clean"])


def classify_snr(snr_db: float | None) -> str:
    if snr_db is None or snr_db >= 25:
        return "clean"
    if snr_db >= 16:
        return "moderate"
    if snr_db >= 9:
        return "noisy"
    return "very_noisy"


class NoiseTracker:
    def __init__(self) -> None:
        self.noise = 0.0
        self.speech = 0.0
        self.n_noise = 0
        self.n_speech = 0
        self.history: list[float] = []

    def feed(self, level: float, speech: bool, *, friday_talking: bool = False) -> None:
        if friday_talking:
            return
        if speech:
            self.speech = level if self.n_speech == 0 else 0.97 * self.speech + 0.03 * level
            self.n_speech += 1
        else:
            self.noise = level if self.n_noise == 0 else 0.98 * self.noise + 0.02 * level
            self.n_noise += 1

    @property
    def snr_db(self) -> float | None:
        if self.n_noise < 25 or self.n_speech < 10 or self.noise <= 0:
            return None
        return 20 * math.log10(max(self.speech, 1.0) / max(self.noise, 1.0))

    @property
    def klass(self) -> str:
        """Noise alone (no speech yet) can still be loud: absolute level counts too."""
        c = classify_snr(self.snr_db)
        if self.n_noise >= 25 and self.noise > 1800:
            c = "very_noisy"
        elif self.n_noise >= 25 and self.noise > 1000 and c == "clean":
            c = "noisy"
        return c

    def sample(self) -> None:
        if self.snr_db is not None:
            self.history.append(self.snr_db)

    def summary(self) -> dict[str, float | str | None]:
        snr = self.snr_db
        return {
            "noise_rms": round(self.noise, 1), "speech_rms": round(self.speech, 1),
            "snr_db": None if snr is None else round(snr, 1), "noise_class": self.klass,
        }


_NONWORD = re.compile(r"^[\W_\d]*$")
_FILLER_ONLY = {"hmm", "hm", "mm", "uh", "um", "ah", "oh", "haan", "ha"}


def looks_like_noise(text: str | None, confidence: float | None = None, speech_s: float | None = None) -> bool:
    """A transcript that is empty, symbols only, a lone filler, or very low confidence."""
    t = (text or "").strip().lower()
    if not t or _NONWORD.match(t):
        return True
    if confidence is not None and confidence < 0.35:
        return True
    words = t.split()
    return bool(len(words) == 1 and words[0].strip(".,!?") in _FILLER_ONLY and (speech_s or 0) < 0.5)


class NoiseGate:
    """ignore | ask_repeat | give_up for each transcript, in a noisy call."""

    MAX_FAILS = 2

    def __init__(self) -> None:
        self.fails = 0
        self.asked = 0
        self.ignored = 0

    def decide(self, text: str | None, *, confidence: float | None = None,
               speech_s: float | None = None, noisy: bool = True) -> str:
        if not noisy or not looks_like_noise(text, confidence, speech_s):
            self.fails = 0
            return "answer"
        if not (text or "").strip() and (speech_s or 0) < 0.6:
            self.ignored += 1
            return "ignore"  # a click or a rustle: pure noise, say nothing
        self.fails += 1
        if self.fails > self.MAX_FAILS:
            return "give_up"
        self.asked += 1
        return "ask_repeat"
