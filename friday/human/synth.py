# ruff: noqa: E501
"""Synthetic audio for offline noise tests and the selftest: speech-like bursts plus noise at a chosen SNR.

Deterministic (seeded). NOT speech: a voiced-like carrier (harmonics, 4 Hz syllable envelope) is enough
to exercise the level tracking and the detector thresholds. Real noisy phone audio is still UNVERIFIED.
"""

from __future__ import annotations

import math
import random
from array import array

RATE = 8000
FRAME = 160  # 20 ms


def _frames(samples: list[float]) -> list[bytes]:
    out = []
    for i in range(0, len(samples) - FRAME + 1, FRAME):
        a = array("h", (max(-32768, min(32767, int(v))) for v in samples[i : i + FRAME]))
        out.append(a.tobytes())
    return out


def noise(seconds: float, rms: float, seed: int = 1) -> list[float]:
    r = random.Random(seed)
    return [r.gauss(0, rms) for _ in range(int(seconds * RATE))]


def speech_like(seconds: float, rms: float, seed: int = 2) -> list[float]:
    r = random.Random(seed)
    f0 = 140 + r.random() * 40
    n = int(seconds * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        env = 0.55 + 0.45 * math.sin(2 * math.pi * 4 * t) ** 2
        v = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 8))
        out.append(v * env)
    cur = math.sqrt(sum(x * x for x in out) / max(len(out), 1)) or 1.0
    return [x * rms / cur for x in out]


def mix(speech: list[float], noise_: list[float]) -> list[float]:
    n = max(len(speech), len(noise_))
    s = speech + [0.0] * (n - len(speech))
    z = noise_ + [0.0] * (n - len(noise_))
    return [a + b for a, b in zip(s, z, strict=True)]


def call_audio(*, noise_rms: float, speech_rms: float = 3000.0, lead_s: float = 1.0, speech_s: float = 2.0,
               tail_s: float = 1.0, seed: int = 3) -> list[bytes]:
    """20 ms PCM16 frames: noise only, then speech over noise, then noise only."""
    total = lead_s + speech_s + tail_s
    nz = noise(total, noise_rms, seed)
    sp = [0.0] * int(lead_s * RATE) + speech_like(speech_s, speech_rms, seed + 1)
    return _frames(mix(sp, nz))


def noise_only(seconds: float, noise_rms: float, seed: int = 4) -> list[bytes]:
    return _frames(noise(seconds, noise_rms, seed))
