"""Shared helpers for the live Sarvam voice probes (probe_saaras_realtime.py, probe_bulbul_ws.py).

Opt-in tools that spend a few paise of real Sarvam credit; never run by the test suite.
The key is read via ``Settings()`` (never printed). HTTP 401/402 from Sarvam aborts the run.
"""

from __future__ import annotations

import re
import statistics
import time

from friday.core.config import Settings


class Abort(RuntimeError):
    """Sarvam answered 401 (bad key) or 402 (out of credit): stop and report."""


def api_key() -> str:
    s = Settings()
    if not s.sarvam_api_key:
        raise Abort("SARVAM_API_KEY is not set")
    return s.sarvam_api_key.get_secret_value()


def check_status(code: int | None, where: str) -> None:
    if code in (401, 402, 403):
        raise Abort(f"HTTP {code} from Sarvam at {where}: stop and report (key / credit)")


def pctl(vals: list[float], p: float) -> float | None:
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def summary(vals: list[float | None]) -> str:
    v = [x for x in vals if x is not None]
    if not v:
        return "n/a"
    return f"p50 {statistics.median(v):.0f} / p90 {pctl(v, 0.9):.0f} (n={len(v)})"


def now_ms() -> float:
    return time.perf_counter() * 1000


_DEV = str.maketrans("", "", "ँं़")  # chandrabindu, anusvara, nukta


def norm(text: str) -> list[str]:
    t = text.lower().replace("।", " ").translate(_DEV)
    t = re.sub(r"[^\w\s]", " ", t)
    return t.split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)


def best_wer(refs: list[str], hyp: str) -> float:
    """Lowest WER over the acceptable spellings (Roman, Devanagari, digits)."""
    return min(wer(r, hyp) for r in refs)
