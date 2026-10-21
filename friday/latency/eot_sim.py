# ruff: noqa: E501
"""Simulate the semantic end-of-turn detector on the HELD-OUT hand-written sentences.

    uv run python -m friday.latency.eot_sim [--extend-ms 700] [--median-ms 700]

For every held-out sentence the REAL detector (rules + the gate-passed model, or the rules only) gives a
verdict, and the commit time of the turn is worked out from the same timings as the other simulator
(``Timing``: 650 ms short wait, 900 ms long wait, early transcript 340 + 500 ms, streaming partial 350 ms
+ 220 ms stable). Two questions are answered:

* FINISHED sentences: how much sooner / later does the turn commit than today (the reply gap moves by the
  same amount, the rest of the chain is unchanged)? A false "unfinished" costs the extension.
* UNFINISHED sentences: the caller is going to carry on after a pause. How often is the turn cut at the
  pause today, and with the extension? The pause length is an ASSUMPTION (log-normal, median
  ``--median-ms``, sigma 0.5; evaluated on a fixed grid of 99 quantiles, so there is no randomness): there
  is no measured distribution of real hesitation pauses yet. The table repeats it for other medians.

Mechanics modelled (as built in ``SarvamCallLeg`` / ``UtteranceSegmenter``):
* REST speech-to-text: the early transcript is ready at ``early_stt_at + stt`` = 840 ms. While it is being
  made the close is HELD (at most 800 ms), which costs a finished answer nothing because the reply needs the
  transcript anyway. Unfinished verdict: the wait becomes ``W + extension``. Finished + short: committed when
  the transcript is ready.
* Streaming speech-to-text: partials exist during the pause; only the early-commit VETO is applied (an
  unfinished short partial is not committed early), the local wait is not what closes the turn there.

NOT measured: real pause lengths, real STT partial quality, a real call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from friday.latency.simulator import Timing
from friday.learning.eot_train import Example, load_gold
from friday.voice.eot import SemanticEot, Verdict, load_active

SHORT_WORDS = 6
HOLD_MAX_MS = 800


@dataclass
class EotSimResult:
    mode: str
    extend_ms: int
    median_ms: int
    finished_n: int
    unfinished_n: int
    mean_commit_delta_ms: float  # finished turns: semantic commit - today's commit (negative = sooner)
    mean_wasted_ms: float  # finished turns wrongly extended: extra wait, averaged over finished turns
    mean_saved_ms: float  # finished turns committed sooner, averaged over finished turns
    cut_rate_today: float  # unfinished turns cut at the pause (pause longer than today's wait)
    cut_rate_semantic: float
    cut_rate_oracle: float  # if every unfinished turn were extended
    extended_unfinished: float  # share of unfinished turns that got the extension


def _quantiles(median_ms: float, sigma: float = 0.5, n: int = 99) -> list[float]:
    nd = NormalDist()
    return [median_ms * math.exp(sigma * nd.inv_cdf((i + 0.5) / n)) for i in range(n)]


def simulate(
    items: list[Example], det: SemanticEot, *, mode: str = "rest", extend_ms: int = 700,
    median_ms: int = 700, timing: Timing | None = None,
) -> EotSimResult:
    t = timing or Timing()
    ready = t.early_stt_at_ms + t.stt_ms  # REST: early transcript ready
    stream_commit = t.partial_ms + t.stable_ms
    pauses = _quantiles(median_ms)
    fin = [e for e in items if e.label == "complete"]
    unf = [e for e in items if e.label == "incomplete"]

    def wait_of(e: Example) -> int:
        return t.end_silence_ms if len(e.text.split()) <= SHORT_WORDS else t.long_end_silence_ms

    def today_commit(e: Example) -> float:
        w = wait_of(e)
        if mode == "rest":
            return float(max(w, ready))
        short = len(e.text.split()) <= SHORT_WORDS
        return float(stream_commit if short else t.stream_final_ms)

    deltas: list[float] = []
    wasted = saved = 0.0
    for e in fin:
        v = det.assess(e.text, e.answer_type).verdict
        base = today_commit(e)
        sem = base
        short = len(e.text.split()) <= SHORT_WORDS
        if v is Verdict.INCOMPLETE and mode == "rest":
            sem = float(max(wait_of(e) + extend_ms, base))
            wasted += max(0.0, sem - base)
        elif v is Verdict.COMPLETE and short and mode == "rest":
            sem = float(min(base, ready))  # committed as soon as the transcript is ready
            saved += max(0.0, base - sem)
        deltas.append(sem - base)

    cut_today = cut_sem = cut_orc = 0.0
    ext_n = 0
    for e in unf:
        v = det.assess(e.text, e.answer_type).verdict
        w = wait_of(e)
        extended = v is Verdict.INCOMPLETE and mode == "rest"
        ext_n += 1 if extended else 0
        # the pause is cut when it outlasts the wait (a pause shorter than the wait is bridged)
        cut_today += sum(1 for p in pauses if p > w) / len(pauses)
        cut_sem += sum(1 for p in pauses if p > (w + extend_ms if extended else w)) / len(pauses)
        cut_orc += sum(1 for p in pauses if p > (w + extend_ms)) / len(pauses)
    n_u = max(1, len(unf))
    n_f = max(1, len(fin))
    return EotSimResult(
        mode, extend_ms, median_ms, len(fin), len(unf),
        round(sum(deltas) / n_f, 1), round(wasted / n_f, 1), round(saved / n_f, 1),
        round(cut_today / n_u, 4), round(cut_sem / n_u, 4), round(cut_orc / n_u, 4),
        round(ext_n / n_u, 4),
    )


def default_detector(rules_only: bool = False) -> tuple[SemanticEot, str]:
    active = load_active()
    if active is None or rules_only:
        return SemanticEot(None, 0.9, rules_only=True), "rules only"
    model, ver = active
    return SemanticEot(model, float(ver.get("threshold", 0.9))), f"rules + model (threshold {ver.get('threshold')})"


def format_report(items: list[Example], extend_ms: int = 700, medians: tuple[int, ...] = (500, 700, 1000)) -> str:
    lines = ["Semantic end-of-turn on the held-out sentences (SIMULATION; pause lengths are an assumption)"]
    for rules_only in (True, False):
        det, label = default_detector(rules_only)
        lines.append(f"\n{label}:")
        lines.append(f"  {'mode':<7}{'pause median':>13} | {'finished: commit change':>24} {'(wasted / saved)':>18} | "
                     f"{'unfinished cut today':>21} {'with extension':>15} {'oracle':>8}")
        for mode in ("rest", "stream"):
            for med in medians:
                r = simulate(items, det, mode=mode, extend_ms=extend_ms, median_ms=med)
                lines.append(
                    f"  {mode:<7}{str(med) + ' ms':>13} | {r.mean_commit_delta_ms:>+21.0f} ms {f'(+{r.mean_wasted_ms:.0f} / -{r.mean_saved_ms:.0f})':>18} | "
                    f"{r.cut_rate_today:>20.1%} {r.cut_rate_semantic:>15.1%} {r.cut_rate_oracle:>8.1%}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Semantic end-of-turn simulation on the held-out set")
    ap.add_argument("--extend-ms", type=int, default=700)
    ap.add_argument("--split", choices=("test", "train", "all"), default="test")
    a = ap.parse_args(argv)
    train, test = load_gold()
    items = {"test": test, "train": train, "all": train + test}[a.split]
    print(format_report(items, a.extend_ms))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
