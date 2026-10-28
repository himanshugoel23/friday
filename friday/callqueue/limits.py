"""Vobiz limits for the queue: explicit setting > cached account config > safe defaults.

The account config is what ``GET /auth/me`` returns (``concurrent_calls_limit``, ``cps_limit``; see
friday/voice/telephony/vobiz_probe.py). ``save_probe`` caches those two numbers next to the queue
database so the queue never needs the network to start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONCURRENT = 3
DEFAULT_CPS = 1.0


@dataclass(frozen=True)
class Limits:
    max_concurrent: int = DEFAULT_CONCURRENT
    cps: float = DEFAULT_CPS
    source: str = "default"

    @property
    def min_start_gap_s(self) -> float:
        return 1.0 / self.cps if self.cps > 0 else 1.0


def cache_path(settings: Any) -> Path:
    return Path(str(settings.call_queue_db)).with_suffix(".limits.json")


def _pos(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def save_probe(settings: Any, probe: dict[str, Any]) -> bool:
    """Cache the account limits from a ``vobiz_probe.summarize`` result. False if unusable."""
    conc, cps = _pos(probe.get("concurrent_calls_limit")), _pos(probe.get("cps_limit"))
    if conc is None and cps is None:
        return False
    path = cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"concurrent": conc, "cps": cps}), encoding="utf-8")
    return True


def resolve(settings: Any) -> Limits:
    conc: float | None = _pos(getattr(settings, "call_queue_max_concurrent", None))
    cps: float | None = _pos(getattr(settings, "call_queue_cps", None))
    src = "settings" if (conc or cps) else "default"
    if conc is None or cps is None:
        try:
            cached = json.loads(cache_path(settings).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if conc is None and _pos(cached.get("concurrent")):
            conc, src = _pos(cached["concurrent"]), "account"
        if cps is None and _pos(cached.get("cps")):
            cps, src = _pos(cached["cps"]), "account"
    return Limits(int(conc or DEFAULT_CONCURRENT), float(cps or DEFAULT_CPS), src)
