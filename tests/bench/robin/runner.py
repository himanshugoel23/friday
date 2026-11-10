# ruff: noqa: E501
"""Robin safety evaluation runner (T18). Fakes only, no network. Corpus is SMALL, SYNTHETIC and overfit-prone: see docs/ROBIN_EVAL.md.

unverified clinical/linguistic review needed.

Every scenario becomes an ``Outcome``: *positive* (the detector must flag / act), *negative* (it must stay quiet), optionally
*high* (a miss is dangerous) and optionally *known_gap* (a real miss we know about: reported, never gated).
Per category: precision = TP/(TP+FP), recall = TP/P, recall_high = TP_high/P_high, fp_rate = FP/N.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).parent
SCEN = HERE / "scenarios"
BASELINE = HERE / "baseline.json"
EXISTING_DIALOGUES = HERE.parents[1] / "robindevice" / "call_dialogues.yaml"
CATEGORIES = (
    "scamcheck",
    "callpattern",
    "care",
    "emergency_words",
    "emergency_ladder",
    "emergency_flow",
)


@dataclass
class Outcome:
    id: str
    category: str
    positive: bool
    high: bool
    ok: bool
    detail: str = ""
    known_gap: bool = False


def _load(name: str) -> Any:
    return yaml.safe_load((SCEN / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- scam-check
def run_scamcheck() -> list[Outcome]:
    from friday.robindevice import scamcheck as S

    out: list[Outcome] = []
    for sc in _load("scamcheck.yaml")["scenarios"]:
        res = S.check_rules("text", sc["text"])
        rank = S._RANK[res.verdict]
        if sc["label"] == "scam":
            need = S._RANK[sc.get("min", "RISKY")]
            out.append(
                Outcome(
                    sc["id"],
                    "scamcheck",
                    True,
                    bool(sc.get("high")),
                    rank >= need,
                    f"{res.verdict} score={res.score} cats={res.categories} want>={sc.get('min', 'RISKY')}",
                )
            )
        else:
            cap = S._RANK[sc.get("max", "UNSURE")]
            out.append(
                Outcome(
                    sc["id"],
                    "scamcheck",
                    False,
                    False,
                    rank <= cap,
                    f"{res.verdict} score={res.score} cats={res.categories} want<={sc.get('max', 'UNSURE')}",
                )
            )
    return out


# ----------------------------------------------------------------------------- call patterns
def _dialogues() -> list[dict[str, Any]]:
    d = yaml.safe_load(EXISTING_DIALOGUES.read_text(encoding="utf-8"))["dialogues"]
    d += _load("calls.yaml")["dialogues"]
    return d


def run_callpattern() -> list[Outcome]:
    from friday.robindevice.callpattern import TIERS, CallPatternAnalyzer

    out: list[Outcome] = []
    for d in _dialogues():
        a = CallPatternAnalyzer(context={k: True for k in d.get("context", [])})
        for i, line in enumerate(d["turns"]):
            who, text = line.split(": ", 1)
            a.turn({"c": "caller", "p": "parent"}[who], text, float(i * 15))
        rank = TIERS.index(a.state.tier)
        cues = [c.id for c in a.state.cues]
        detail = f"{a.state.tier} score={a.state.score} cues={cues}"
        if "min" in d:
            out.append(
                Outcome(
                    d["id"],
                    "callpattern",
                    True,
                    d["min"] == "HIGH",
                    rank >= TIERS.index(d["min"]),
                    f"{detail} want>={d['min']}",
                )
            )
        else:
            out.append(
                Outcome(
                    d["id"],
                    "callpattern",
                    False,
                    False,
                    rank <= TIERS.index(d["max"]),
                    f"{detail} want<={d['max']}",
                )
            )
    return out


# ----------------------------------------------------------------------------- care protocol
def run_care() -> list[Outcome]:
    from friday.care.detect import Tier, assess

    order = {Tier.NONE: 0, Tier.ELEVATED: 1, Tier.HIGH: 2}
    want = {"NONE": 0, "ELEVATED": 1, "HIGH": 2}
    out: list[Outcome] = []
    for sc in _load("care.yaml")["scenarios"]:
        got = assess(sc["text"]).tier
        exp = sc["expect"]
        if exp == "NONE":
            out.append(
                Outcome(sc["id"], "care", False, False, order[got] == 0, f"{got.value} want none")
            )
        else:
            out.append(
                Outcome(
                    sc["id"],
                    "care",
                    True,
                    exp == "HIGH",
                    order[got] >= want[exp],
                    f"{got.value} want>={exp.lower()}",
                )
            )
    return out


# ----------------------------------------------------------------------------- emergency
def run_words() -> list[Outcome]:
    from friday.robin import answers as ans

    out: list[Outcome] = []
    for w in _load("emergency.yaml")["words"]:
        h, t = ans.is_help(w["text"]), ans.is_threat(w["text"])
        gap = bool(w.get("known_gap"))
        if w["expect"] == "none":
            out.append(
                Outcome(
                    w["id"],
                    "emergency_words",
                    False,
                    False,
                    not (h or t),
                    f"help={h} threat={t}",
                    gap,
                )
            )
        else:
            got = h if w["expect"] == "help" else t
            out.append(
                Outcome(
                    w["id"],
                    "emergency_words",
                    True,
                    True,
                    got,
                    f"help={h} threat={t} want {w['expect']}",
                    gap,
                )
            )
    return out


def run_ladder() -> list[Outcome]:
    from friday.robin.alerts import plan_for
    from friday.robin.models import Tier

    out: list[Outcome] = []
    for c in _load("emergency.yaml")["ladder"]:
        s = int(c.get("spacing", 300))
        plan = plan_for(Tier[c["tier"]], c["scenario"], s, minimal_sos=bool(c.get("minimal")))
        got = [f"{p['action']}@{p['offset_s'] / s:g}" for p in plan]
        out.append(
            Outcome(c["id"], "emergency_ladder", True, True, got == c["steps"], f"got {got}")
        )
    return out


def run_flow() -> list[Outcome]:
    from tests.bench.robin.world import run_flow as one

    out: list[Outcome] = []
    for c in _load("emergency.yaml")["flow"]:
        r = asyncio.run(one(c))
        e = c["expect"]
        ok = r["accepted"] == e["accepted"]
        if "child_told" in e:
            ok = ok and r["child_told"] == e["child_told"]
        if "child_rings_min" in e:
            ok = ok and r["child_rings"] >= e["child_rings_min"]
        if "child_rings_max" in e:
            ok = ok and r["child_rings"] <= e["child_rings_max"]
        if "parent_calls_min" in e:
            ok = ok and r["parent_calls"] >= e["parent_calls_min"]
        if "parent_calls_max" in e:
            ok = ok and r["parent_calls"] <= e["parent_calls_max"]
        pos = c["kind"] == "positive"
        out.append(Outcome(c["id"], "emergency_flow", pos, pos, ok, f"{r} want {e}"))
    return out


RUNNERS = {
    "scamcheck": run_scamcheck,
    "callpattern": run_callpattern,
    "care": run_care,
    "emergency_words": run_words,
    "emergency_ladder": run_ladder,
    "emergency_flow": run_flow,
}


def evaluate_all(categories: tuple[str, ...] = CATEGORIES) -> list[Outcome]:
    out: list[Outcome] = []
    for cat in categories:
        out += RUNNERS[cat]()
    return out


# ----------------------------------------------------------------------------- metrics and gate
def _ratio(n: int, d: int, empty: float) -> float:
    return empty if d == 0 else n / d


def metrics(outcomes: list[Outcome]) -> dict[str, dict[str, Any]]:
    res: dict[str, dict[str, Any]] = {}
    for cat in sorted({o.category for o in outcomes}, key=CATEGORIES.index):
        os_ = [o for o in outcomes if o.category == cat and not o.known_gap]
        pos = [o for o in os_ if o.positive]
        neg = [o for o in os_ if not o.positive]
        hi = [o for o in pos if o.high]
        tp = sum(o.ok for o in pos)
        fp = sum(not o.ok for o in neg)
        res[cat] = {
            "scenarios": len(os_),
            "positives": len(pos),
            "negatives": len(neg),
            "high_positives": len(hi),
            "tp": tp,
            "fp": fp,
            "high_tp": sum(o.ok for o in hi),
            "precision": _ratio(tp, tp + fp, 1.0),
            "recall": _ratio(tp, len(pos), 1.0),
            "recall_high": _ratio(sum(o.ok for o in hi), len(hi), 1.0),
            "fp_rate": _ratio(fp, len(neg), 0.0),
            "known_gaps": len([o for o in outcomes if o.category == cat and o.known_gap]),
        }
    return res


def baseline_view(m: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keys = ("scenarios", "positives", "negatives", "high_positives", "tp", "fp", "high_tp")
    return {
        "_note": "Committed safety baseline. ONLY THE LEAD may update it (python -m tests.bench.robin --write-baseline), after reviewing why a number moved. Never lower it to make a failing gate pass.",
        "categories": {c: {k: v[k] for k in keys} for c, v in m.items()},
    }


def check_gate(m: dict[str, dict[str, Any]], baseline: dict[str, Any]) -> list[str]:
    """Reasons the gate fails (empty = pass): recall on HIGH-risk or overall recall below baseline, false-positive rate above, corpus shrunk, category missing."""
    bad: list[str] = []
    for cat, b in baseline["categories"].items():
        cur = m.get(cat)
        if cur is None:
            bad.append(f"{cat}: category missing from the run")
            continue
        if cur["scenarios"] < b["scenarios"]:
            bad.append(f"{cat}: corpus shrank ({cur['scenarios']} < {b['scenarios']})")
        b_high = _ratio(b["high_tp"], b["high_positives"], 1.0)
        b_rec = _ratio(b["tp"], b["positives"], 1.0)
        b_fp = _ratio(b["fp"], b["negatives"], 0.0)
        eps = 1e-9
        if cur["recall_high"] < b_high - eps:
            bad.append(f"{cat}: HIGH-risk recall {cur['recall_high']:.3f} < baseline {b_high:.3f}")
        if cur["recall"] < b_rec - eps:
            bad.append(f"{cat}: recall {cur['recall']:.3f} < baseline {b_rec:.3f}")
        if cur["fp_rate"] > b_fp + eps:
            bad.append(f"{cat}: false-positive rate {cur['fp_rate']:.3f} > baseline {b_fp:.3f}")
    return bad


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def render(outcomes: list[Outcome], m: dict[str, dict[str, Any]], *, verbose: bool = False) -> str:
    lines = [
        f"{'category':<18}{'n':>4}{'prec':>7}{'recall':>8}{'recHIGH':>9}{'FP rate':>9}{'gaps':>6}"
    ]
    for cat, v in m.items():
        lines.append(
            f"{cat:<18}{v['scenarios']:>4}{v['precision']:>7.2f}{v['recall']:>8.2f}{v['recall_high']:>9.2f}{v['fp_rate']:>9.2f}{v['known_gaps']:>6}"
        )
    miss = [o for o in outcomes if not o.ok]
    lines.append("")
    lines.append(
        f"{len(miss)} scenario(s) not met"
        + (" (known gaps marked G)" if any(o.known_gap for o in miss) else "")
    )
    for o in miss:
        lines.append(
            f"  {'G' if o.known_gap else '-'} [{o.category}] {o.id} ({'should flag' if o.positive else 'should stay quiet'}{', HIGH' if o.high else ''}): {o.detail}"
        )
    if verbose:
        lines.append("")
        lines += [f"  ok [{o.category}] {o.id}: {o.detail}" for o in outcomes if o.ok]
    lines.append("")
    lines.append(
        "Small synthetic corpus; unverified clinical/linguistic review needed (docs/ROBIN_EVAL.md)."
    )
    return "\n".join(lines)
