# ruff: noqa: E501
"""Offline, SYNTHETIC evaluation of the voice-activity backends: energy rule vs Silero.

    uv run --extra vad python -m friday.voice.vad.evaluate --speech-dir DIR [--quick] [--json OUT]

What it does: takes real (text-to-speech) speech clips from ``--speech-dir`` (never committed), cuts
them into single utterances, mixes each with a synthesised line-noise model (shop hum, traffic,
crowd babble made of mixed tones, music) at several SNRs, passes the result through mu-law like a phone
line, and runs the REAL ``UtteranceSegmenter`` (end-of-speech wait 900 / 650 ms) with each backend.

What it reports, per backend and per noise x SNR cell:
* frame level: precision / recall of the speech decision against the clean-speech ground truth,
* utterance level: share of utterances that came out as exactly one correct segment ("ok"), were
  split or clipped ("cut off"), missed, or never closed because the noise kept the line "busy"
  ("stuck"); and the false-trigger rate on noise-only clips,
* CPU: frames per second of each backend on this machine, single thread.

HONEST LIMITS: the speech is studio-clean synthetic voice (no phone codec artefacts, no room, no
far-field), the noises are synthetic models (the babble is a mixture of harmonic tones, NOT real
voices: a neural VAD that has learned speech may react to real babble more than it does here), and
the ground truth is the clean signal's own energy. This is synthetic evidence only; real shop
recordings are needed to validate (docs/LATENCY.md says so).
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.voice.audio import _DECODE_TABLE, _encode_table, resample_pcm16, wav_to_pcm16
from friday.voice.telephony.media import FRAME_MS, UtteranceSegmenter

FRAME = 160  # 20 ms at 8 kHz
SR = 8000
NOISES = ("hum", "traffic", "babble", "music")
SNRS = (20, 10, 5, 0)
LEVELS = {"normal": 2000.0, "quiet": 700.0}  # speech RMS in PCM16 units
TRUTH_RMS = 100.0  # a clean frame at or above this RMS is speech in the ground truth
LEAD_S, TAIL_S = 2.0, 2.5


def _np() -> Any:
    import numpy as np

    return np


# --------------------------------------------------------------------------- noise models
def make_noise(kind: str, seconds: float, seed: int) -> Any:
    """Unit-RMS float noise, 8 kHz, deterministic."""
    np = _np()
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    if kind == "hum":  # mains hum + fan: stationary harmonics over a low broadband bed
        x = sum(a * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) for f, a in
                ((50, 1.0), (100, 0.8), (150, 0.5), (200, 0.3), (300, 0.2)))
        x = x + 0.6 * _lowpass(rng.standard_normal(n), 0.35)
    elif kind == "traffic":  # engine rumble, vehicles passing (slow swells), the odd horn
        x = 1.0 * _lowpass(rng.standard_normal(n), 0.06)
        for _ in range(int(seconds / 3) + 1):
            c, w = rng.uniform(0, seconds), rng.uniform(0.8, 2.0)
            x += 2.0 * np.exp(-0.5 * ((t - c) / w) ** 2) * _lowpass(rng.standard_normal(n), 0.12)
        for _ in range(int(seconds / 5) + 1):
            s0, d = rng.uniform(0, seconds), rng.uniform(0.25, 0.7)
            env = ((t >= s0) & (t <= s0 + d)).astype(float)
            x += 0.9 * env * (np.sin(2 * np.pi * 410 * t) + 0.7 * np.sin(2 * np.pi * 520 * t))
    elif kind == "babble":  # many "voices": harmonic complexes with syllable-rate gating
        x = np.zeros(n)
        for _ in range(12):
            f0 = rng.uniform(95, 260)
            ph = rng.uniform(0, 6.28)
            drift = 1 + 0.03 * np.sin(2 * np.pi * rng.uniform(0.2, 0.7) * t + ph)
            v = sum((1.0 / k) * np.sin(2 * np.pi * k * f0 * drift * t + ph * k)
                    for k in range(1, 14) if k * f0 < 3600)
            syl = np.clip(np.sin(2 * np.pi * rng.uniform(2.5, 5.5) * t + ph) + 0.25, 0, 1)
            gate = _lowpass((rng.random(n) < 0.0004).astype(float).cumsum() % 2, 0.002)
            x += v * syl * (0.4 + 0.6 * np.clip(gate, 0, 1))
    elif kind == "music":  # a slow chord progression of plucked notes with harmonics
        x = np.zeros(n)
        chords = ((220, 277, 330), (196, 247, 294), (175, 220, 262), (196, 247, 392))
        beat = 0.6
        for i in range(int(seconds / beat) + 1):
            s0 = i * beat
            for f in chords[(i // 4) % len(chords)]:
                env = np.exp(-(t - s0) * 3.0) * (t >= s0)
                x += env * (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * 2 * f * t)
                            + 0.2 * np.sin(2 * np.pi * 3 * f * t))
    else:
        raise ValueError(kind)
    x = x - x.mean()
    return x / (np.sqrt((x**2).mean()) or 1.0)


def _lowpass(x: Any, a: float) -> Any:
    """One-pole low-pass via an FFT-free recursive filter (vectorised with cumulative trick)."""
    np = _np()
    from math import exp

    k = np.arange(0, 400)
    h = (1 - exp(-a * 6.28)) * np.exp(-a * 6.28 * k)
    return np.convolve(x, h, mode="same")


# --------------------------------------------------------------------------- phone line
def mulaw_roundtrip(x: Any) -> Any:
    """float/int16 samples -> mu-law -> int16 (what the leg hears)."""
    np = _np()
    s = np.clip(np.rint(x), -32768, 32767).astype(np.int16)
    enc = np.frombuffer(_encode_table(), dtype=np.uint8)[s.astype(np.int64) & 0xFFFF]
    dec = np.array(_DECODE_TABLE, dtype=np.int16)
    return dec[enc]


# --------------------------------------------------------------------------- speech corpus
@dataclass
class Utterance:
    pcm: Any  # int16 numpy, 8 kHz, normalised to the nominal level
    truth: Any  # bool per 20 ms frame
    source: str


def frame_rms(x: Any) -> Any:
    np = _np()
    n = len(x) // FRAME
    f = x[: n * FRAME].astype(np.float64).reshape(n, FRAME)
    return np.sqrt((f**2).mean(axis=1))


def load_utterances(speech_dir: Path, per_clip: int = 3, max_total: int = 40) -> list[Utterance]:
    """Cut the clips into single utterances (1 to 6 s of speech, internal gaps < 400 ms)."""
    np = _np()
    out: list[Utterance] = []
    files = sorted(speech_dir.rglob("*.wav"))
    stride = max(1, len(files) * per_clip // max(1, max_total))  # spread over all the clips
    for path in files[::stride]:
        if len(out) >= max_total:
            break
        try:
            with wave.open(str(path), "rb") as w:
                if w.getnchannels() != 1 or w.getsampwidth() != 2:
                    continue
            pcm, rate = wav_to_pcm16(path.read_bytes())
        except Exception:  # noqa: BLE001
            continue
        x = np.frombuffer(resample_pcm16(pcm, rate, SR), dtype="<i2").astype(np.float64)
        rms = frame_rms(x)
        speech = rms >= TRUTH_RMS
        runs: list[tuple[int, int]] = []
        i, n = 0, len(speech)
        while i < n:
            if speech[i]:
                j = i
                gap = 0
                last = i
                while j < n and gap < 20:  # merge gaps shorter than 400 ms
                    if speech[j]:
                        last, gap = j, 0
                    else:
                        gap += 1
                    j += 1
                runs.append((i, last + 1))
                i = last + 1
            else:
                i += 1
        runs = [(a, b) for a, b in runs if 50 <= b - a <= 300]  # 1 to 6 s
        step = max(1, len(runs) // per_clip)
        for a, b in runs[::step][:per_clip]:
            seg = x[max(0, (a - 5)) * FRAME : (b + 5) * FRAME]
            r = frame_rms(seg)
            active = r >= TRUTH_RMS
            level = float(np.sqrt((r[active] ** 2).mean())) if active.any() else 1.0
            out.append(Utterance(seg / level, active, path.name))
            if len(out) >= max_total:
                break
    return out


def synthetic_utterances(count: int = 6) -> list[Utterance]:
    """Speech-LIKE stand-ins (harmonic voice with syllable bursts) for when no clips exist. A
    trained VAD may not call these speech; use real clips for any number you intend to quote."""
    np = _np()
    out = []
    for k in range(count):
        rng = np.random.default_rng(100 + k)
        t = np.arange(int((1.5 + k * 0.4) * SR)) / SR
        f0 = 110 + 25 * k
        x = sum((1 / h) * np.sin(2 * np.pi * h * f0 * (1 + 0.02 * np.sin(2 * np.pi * 4 * t)) * t)
                for h in range(1, 12))
        env = np.clip(np.sin(2 * np.pi * (3 + 0.3 * k) * t) + 0.3, 0, 1)
        x = x * env + 0.02 * rng.standard_normal(len(t))
        r = frame_rms(x)
        active = r >= 0.1 * r.max()
        x = x / (np.sqrt((r[active] ** 2).mean()) or 1.0)
        out.append(Utterance(x, active, f"synthetic-{k}"))
    return out


# --------------------------------------------------------------------------- running
def build_clip(utt: Utterance | None, noise: str | None, snr_db: float, level: float, seed: int,
               noise_only_s: float = 7.0) -> tuple[bytes, Any]:
    """(mu-law-roundtripped PCM16 bytes, truth per frame) for one test clip."""
    np = _np()
    if utt is None:
        n = int(noise_only_s * SR)
        speech = np.zeros(n)
        truth = np.zeros(n // FRAME, dtype=bool)
    else:
        lead, tail = int(LEAD_S * SR), int(TAIL_S * SR)
        speech = np.concatenate([np.zeros(lead), utt.pcm * level, np.zeros(tail)])
        truth = np.concatenate([np.zeros(lead // FRAME, dtype=bool), utt.truth,
                                np.zeros(tail // FRAME, dtype=bool)])
        speech = speech[: len(truth) * FRAME]
    n = len(speech)
    if noise is None:
        mix = speech + 3.0 * np.random.default_rng(seed).standard_normal(n)
    else:
        noise_rms = LEVELS["normal"] / (10 ** (snr_db / 20)) if utt is None else level / (10 ** (snr_db / 20))
        mix = speech + noise_rms * make_noise(noise, n / SR + 0.1, seed)[:n]
    return mulaw_roundtrip(mix).astype("<i2").tobytes(), truth


def run_segmenter(pcm: bytes, backend: str) -> tuple[list[tuple[int, int]], list[bool], float, int]:
    """Feed 20 ms frames through the real segmenter. Returns (segments as frame ranges, the speech
    decision per frame, seconds spent, frames)."""
    from friday.voice.vad.silero import build_vad

    seg = UtteranceSegmenter(end_silence_ms=900, short_end_silence_ms=650, max_continuous_ms=20000)
    if backend == "silero":
        seg.vad = build_vad("silero", sample_rate=SR)
        if seg.vad is None:
            raise RuntimeError("silero VAD could not be loaded (uv sync --extra vad)")
    decisions: list[bool] = []
    spans: list[tuple[int, int]] = []
    t_total = 0.0
    nframes = len(pcm) // 2 // FRAME
    for i in range(nframes):
        frame = pcm[i * FRAME * 2 : (i + 1) * FRAME * 2]
        t0 = time.perf_counter()
        fr = seg.analyse(frame)
        out = seg.feed_pcm16(frame, fr)
        t_total += time.perf_counter() - t0
        decisions.append(fr.speech)
        for s in out:
            end = i + 1
            spans.append((max(0, end - int(s.duration_s * 1000 / FRAME_MS)), end))
    stuck_open = seg._active  # still collecting when the clip ended
    if stuck_open:
        spans.append((-1, -1))  # marker: never closed
    return spans, decisions, t_total, nframes


def score_cell(clips: list[tuple[Any, Any, bool]], backend: str) -> dict[str, Any]:
    """clips: (pcm bytes, truth, is_noise_only)."""
    np = _np()
    tp = fp = fn = 0
    outcome = {"ok": 0, "cut_off": 0, "missed": 0, "stuck": 0}
    n_utt = n_noise = false_trig = 0
    secs = 0.0
    frames = 0
    for pcm, truth, noise_only in clips:
        spans, dec, t, nf = run_segmenter(pcm, backend)
        secs += t
        frames += nf
        d = np.array(dec[: len(truth)], dtype=bool)
        tr = np.asarray(truth[: len(d)], dtype=bool)
        tp += int((d & tr).sum())
        fp += int((d & ~tr).sum())
        fn += int((~d & tr).sum())
        stuck = (-1, -1) in spans
        real = [s for s in spans if s != (-1, -1)]
        if noise_only:
            n_noise += 1
            false_trig += 1 if (real or stuck) else 0
            continue
        n_utt += 1
        t_idx = np.nonzero(tr)[0]
        a, b = int(t_idx[0]), int(t_idx[-1]) + 1
        covered = sum(max(0, min(e, b) - max(s, a)) for s, e in real)
        overlapping = [s for s in real if min(s[1], b) > max(s[0], a)]
        if stuck and not real:
            outcome["stuck"] += 1
        elif not real:
            outcome["missed"] += 1
        elif len(overlapping) >= 2 or covered < 0.8 * (b - a):
            outcome["cut_off"] += 1
        elif stuck:
            outcome["stuck"] += 1
        else:
            outcome["ok"] += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "frame_precision": round(prec, 4), "frame_recall": round(rec, 4),
        "frame_f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
        "utterances": n_utt, **{k: round(v / n_utt, 4) if n_utt else 0.0 for k, v in outcome.items()},
        "noise_only_clips": n_noise,
        "false_trigger_rate": round(false_trig / n_noise, 4) if n_noise else 0.0,
        "frames": frames, "cpu_seconds": round(secs, 3),
    }


def run(speech_dir: Path | None, *, quick: bool = False, seed: int = 11) -> dict[str, Any]:
    utts = load_utterances(speech_dir, per_clip=2 if quick else 3, max_total=8 if quick else 24) \
        if speech_dir else []
    source = f"{len(utts)} utterances cut from real speech clips" if utts else "synthetic tones"
    if not utts:
        utts = synthetic_utterances(4 if quick else 6)
    noises = ("hum", "babble") if quick else NOISES
    snrs = (20, 5) if quick else SNRS
    levels = {"normal": LEVELS["normal"]} if quick else LEVELS
    cells: list[dict[str, Any]] = []
    totals = {b: {"frames": 0, "cpu_seconds": 0.0} for b in ("energy", "silero")}
    for lv_name, lv in levels.items():
        for noise in noises:
            for snr in snrs:
                clips = [(*build_clip(u, noise, snr, lv, seed + i), False) for i, u in enumerate(utts)]
                clips += [(*build_clip(None, noise, snr, lv, seed + 1000 + i), True) for i in range(3)]
                row: dict[str, Any] = {"noise": noise, "snr_db": snr, "level": lv_name}
                for backend in ("energy", "silero"):
                    r = score_cell(clips, backend)
                    row[backend] = r
                    totals[backend]["frames"] += r["frames"]
                    totals[backend]["cpu_seconds"] += r["cpu_seconds"]
                cells.append(row)
    # a quiet line with no added noise at all
    clean = [(*build_clip(u, None, 0, LEVELS["normal"], seed + i), False) for i, u in enumerate(utts)]
    clean += [(*build_clip(None, None, 0, LEVELS["normal"], seed + 2000 + i), True) for i in range(3)]
    row = {"noise": "none", "snr_db": None, "level": "normal"}
    for backend in ("energy", "silero"):
        row[backend] = score_cell(clean, backend)
        totals[backend]["frames"] += row[backend]["frames"]
        totals[backend]["cpu_seconds"] += row[backend]["cpu_seconds"]
    cells.append(row)
    summary: dict[str, Any] = {"speech_source": source, "n_utterances": len(utts), "cells": cells}
    for b, t in totals.items():
        fps = t["frames"] / t["cpu_seconds"] if t["cpu_seconds"] else 0.0
        summary[f"{b}_frames_per_second"] = round(fps)
        summary[f"{b}_x_realtime"] = round(fps / (1000 / FRAME_MS), 1)
    for b in ("energy", "silero"):
        rows = [c[b] for c in cells]
        ut = sum(r["utterances"] for r in rows) or 1
        nn = sum(r["noise_only_clips"] for r in rows) or 1
        summary[f"{b}_overall"] = {
            "ok": round(sum(r["ok"] * r["utterances"] for r in rows) / ut, 4),
            "cut_off": round(sum(r["cut_off"] * r["utterances"] for r in rows) / ut, 4),
            "missed": round(sum(r["missed"] * r["utterances"] for r in rows) / ut, 4),
            "stuck": round(sum(r["stuck"] * r["utterances"] for r in rows) / ut, 4),
            "false_trigger_rate": round(
                sum(r["false_trigger_rate"] * r["noise_only_clips"] for r in rows) / nn, 4),
            "frame_precision": round(sum(r["frame_precision"] for r in rows) / len(rows), 4),
            "frame_recall": round(sum(r["frame_recall"] for r in rows) / len(rows), 4),
        }
    return summary


def format_report(s: dict[str, Any]) -> str:
    lines = [f"SYNTHETIC evidence only. speech: {s['speech_source']}; noise: synthesised models",
             f"{'level':<7}{'noise':<9}{'snr':>4} | {'backend':<7} {'P':>6} {'R':>6} {'ok':>6} {'cut':>6} "
             f"{'miss':>6} {'stuck':>6} {'false-trig':>10}"]
    for c in s["cells"]:
        for b in ("energy", "silero"):
            r = c[b]
            lines.append(
                f"{c['level']:<7}{c['noise']:<9}{str(c['snr_db'] if c['snr_db'] is not None else '-'):>4} | "
                f"{b:<7} {r['frame_precision']:>6.1%} {r['frame_recall']:>6.1%} {r['ok']:>6.1%} {r['cut_off']:>6.1%} "
                f"{r['missed']:>6.1%} {r['stuck']:>6.1%} {r['false_trigger_rate']:>10.1%}")
    for b in ("energy", "silero"):
        o = s[f"{b}_overall"]
        lines.append(f"OVERALL {b:<7} ok {o['ok']:.1%} cut-off {o['cut_off']:.1%} missed {o['missed']:.1%} "
                     f"stuck {o['stuck']:.1%} false-trigger {o['false_trigger_rate']:.1%}  "
                     f"frame P {o['frame_precision']:.1%} R {o['frame_recall']:.1%}")
    for b in ("energy", "silero"):
        lines.append(f"CPU {b}: {s[f'{b}_frames_per_second']} frames/s = {s[f'{b}_x_realtime']}x real time "
                     f"(single thread, this machine, includes the segmenter)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--speech-dir", default=None, help="directory of mono 16-bit wav speech clips")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default=None, help="write the full result here")
    args = ap.parse_args(argv)
    from friday.voice.vad.silero import available

    if not available():
        print("onnxruntime / numpy are not installed: uv sync --extra vad")
        return 2
    s = run(Path(args.speech_dir) if args.speech_dir else None, quick=args.quick)
    print(format_report(s))
    if args.json:
        Path(args.json).write_text(json.dumps(s, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


