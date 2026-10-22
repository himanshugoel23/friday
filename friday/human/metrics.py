"""Human-feel metrics: one small record per call, an aggregate report, no transcripts, no numbers.

Per call: hung up within 10 s of being answered, how many times the other side asked 'are you a
robot / AI?', call length, noise level, and how many of each human-voice element fired. Records are
appended to ``var/human/metrics.jsonl`` (never committed: var/ is ignored).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FILE = Path("var/human/metrics.jsonl")
EARLY_HANGUP_S = 10.0
_ROBOT_Q = re.compile(
    r"\b(robot|bot|ai|a\.i\.|machine|computer|recorded|recording|real person|insaan|human|asli|"
    r"artificial|automated)\b|रोबोट|मशीन|इंसान|असली",
    re.I,
)


def asks_if_robot(text: str | None) -> bool:
    t = text or ""
    return bool(_ROBOT_Q.search(t)) and bool(re.search(r"\?|kya|are you|is this|aap|tum|hai", t, re.I))


@dataclass
class CallHumanMetrics:
    call_id: str = ""
    length_s: float = 0.0
    answered: bool = True
    hung_up_by_callee: bool = False
    hangup_within_10s: bool = False
    robot_asked: int = 0
    backchannels: int = 0
    resumes: int = 0
    mood_events: int = 0
    pauses_used: int = 0
    noise_repeat_asks: int = 0
    noise_class: str = "clean"
    snr_db: float | None = None
    noise_rms: float | None = None
    pace_avg: float | None = None
    listener_style: str = "normal"
    switches_on: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"human-feel: length {self.length_s:.0f}s, hangup<10s {int(self.hangup_within_10s)}, "
            f"robot-asked {self.robot_asked}, backchannels {self.backchannels}, resumes {self.resumes}, "
            f"noise {self.noise_class} (snr {self.snr_db if self.snr_db is not None else 'n/a'} dB), "
            f"listener {self.listener_style}"
        )


def finish(m: CallHumanMetrics, *, hung_up_by_callee: bool, length_s: float) -> CallHumanMetrics:
    m.length_s = round(length_s, 1)
    m.hung_up_by_callee = hung_up_by_callee
    m.hangup_within_10s = bool(hung_up_by_callee and length_s <= EARLY_HANGUP_S)
    return m


def append(m: CallHumanMetrics, path: Path = DEFAULT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")


def load(path: Path = DEFAULT_FILE) -> list[CallHumanMetrics]:
    out: list[CallHumanMetrics] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(CallHumanMetrics(**json.loads(ln)))
    except (OSError, ValueError, TypeError):
        pass
    return out


def aggregate(rows: list[CallHumanMetrics]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"calls": 0}
    answered = [r for r in rows if r.answered]
    na = max(len(answered), 1)
    lens = sorted(r.length_s for r in answered) or [0.0]
    return {
        "calls": n,
        "hangup_within_10s_rate": round(sum(r.hangup_within_10s for r in answered) / na, 3),
        "robot_asked_per_call": round(sum(r.robot_asked for r in answered) / na, 3),
        "calls_where_robot_asked": sum(1 for r in answered if r.robot_asked),
        "median_length_s": lens[len(lens) // 2],
        "noisy_calls": sum(1 for r in rows if r.noise_class in ("noisy", "very_noisy")),
        "backchannels_per_call": round(sum(r.backchannels for r in rows) / n, 2),
        "resumes": sum(r.resumes for r in rows),
    }


def report(rows: list[CallHumanMetrics]) -> str:
    a = aggregate(rows)
    if not a["calls"]:
        return "no human-feel records yet (var/human/metrics.jsonl)"
    return "\n".join(f"{k}: {v}" for k, v in a.items())
