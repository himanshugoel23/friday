"""Load and validate the scenario rules (``scenarios.yaml``). A bad file fails loudly at load time."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).with_name("scenarios.yaml")
TIERS = ("INFO", "WATCH", "HIGH", "EMERGENCY")


class RulesError(ValueError):
    """The scenario file is malformed."""


@dataclass(frozen=True)
class SignalDef:
    id: str
    predicate: str
    params: dict[str, Any]
    weight: float
    required: bool
    why: str


@dataclass(frozen=True)
class TierDef:
    tier: str
    min_score: float
    prompt: str | None
    child_alert: bool
    full_screen: bool
    defer_quiet: bool
    digest: bool
    shadow_exempt: bool = False  # this tier alerts even in the shadow week (per-tier; the scenario flag exempts all of its tiers)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    priority: int
    window_min: int
    cooldown_min: int
    shiftable: bool
    suppressible: bool
    shadow_exempt: bool
    money: bool
    anchor: str | None
    needs_consent: tuple[str, ...]
    applies_if_tag: str | None
    unless_events: tuple[str, ...]
    signals: tuple[SignalDef, ...]
    tiers: tuple[TierDef, ...]  # ascending by min_score

    def window_ms(self) -> int:
        return self.window_min * 60_000


@dataclass(frozen=True)
class Rules:
    version: int
    unverified: bool
    defaults: dict[str, Any]
    sensitivity: dict[str, dict[str, float]]
    scenarios: tuple[Scenario, ...]

    def get(self, scenario_id: str) -> Scenario:
        for s in self.scenarios:
            if s.id == scenario_id:
                return s
        raise KeyError(scenario_id)


def _req(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RulesError(f"{where}: missing '{key}'")
    return d[key]


def parse(data: Any, *, known_predicates: set[str] | None = None) -> Rules:
    if not isinstance(data, dict):
        raise RulesError("top level must be a mapping")
    version = _req(data, "version", "file")
    if not isinstance(version, int) or version < 1:
        raise RulesError("version must be a positive integer")
    defaults = _req(data, "defaults", "file")
    for key in ("shadow_days", "nudges_per_hour", "quiet_hours", "payment_threshold_paise", "night_hours"):
        _req(defaults, key, "defaults")
    sens = _req(data, "sensitivity", "file")
    for name in ("calm", "balanced", "careful"):
        entry = _req(sens, name, "sensitivity")
        _req(entry, "threshold_shift", f"sensitivity.{name}")
        _req(entry, "duration_scale", f"sensitivity.{name}")
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        raise RulesError("scenarios must be a non-empty list")
    out: list[Scenario] = []
    seen: set[str] = set()
    for raw in items:
        sid = str(_req(raw, "id", "scenario"))
        where = f"scenario {sid}"
        if sid in seen:
            raise RulesError(f"duplicate scenario id {sid}")
        seen.add(sid)
        sigs: list[SignalDef] = []
        sig_ids: set[str] = set()
        for s in _req(raw, "signals", where):
            pred = str(_req(s, "predicate", where))
            if known_predicates is not None and pred not in known_predicates:
                raise RulesError(f"{where}: unknown predicate '{pred}'")
            sig_id = str(_req(s, "id", where))
            if sig_id in sig_ids:
                raise RulesError(f"{where}: duplicate signal id {sig_id}")
            sig_ids.add(sig_id)
            weight = _req(s, "weight", where)
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                raise RulesError(f"{where}: weight must be a number")
            sigs.append(
                SignalDef(sig_id, pred, dict(s.get("params") or {}), float(weight),
                          bool(s.get("required", False)), str(s.get("why", "")))
            )
        if not sigs:
            raise RulesError(f"{where}: no signals")
        tiers: list[TierDef] = []
        for t in _req(raw, "tiers", where):
            tier = str(_req(t, "tier", where))
            if tier not in TIERS or tier == "EMERGENCY":
                raise RulesError(f"{where}: tier must be INFO, WATCH or HIGH (EMERGENCY comes only from SOS)")
            tiers.append(
                TierDef(tier, float(_req(t, "min_score", where)), t.get("prompt"),
                        bool(t.get("child_alert", True)), bool(t.get("full_screen", False)),
                        bool(t.get("defer_quiet", False)), bool(t.get("digest", False)), bool(t.get("shadow_exempt", False)))
            )
        if not tiers:
            raise RulesError(f"{where}: no tiers")
        tiers.sort(key=lambda t: t.min_score)
        window = int(_req(raw, "window_min", where))
        cooldown = int(_req(raw, "cooldown_min", where))
        if window < 1 or cooldown < 0:
            raise RulesError(f"{where}: bad window/cooldown")
        out.append(
            Scenario(
                id=sid, name=str(_req(raw, "name", where)), priority=int(raw.get("priority", 50)),
                window_min=window, cooldown_min=cooldown, shiftable=bool(raw.get("shiftable", False)),
                suppressible=bool(raw.get("suppressible", False)),
                shadow_exempt=bool(raw.get("shadow_exempt", False)), money=bool(raw.get("money", False)),
                anchor=raw.get("anchor"), needs_consent=tuple(raw.get("needs_consent") or ()),
                applies_if_tag=raw.get("applies_if_tag"),
                unless_events=tuple(raw.get("unless_events") or ()), signals=tuple(sigs), tiers=tuple(tiers),
            )
        )
    return Rules(
        version=version, unverified=bool(data.get("unverified", True)), defaults=dict(defaults),
        sensitivity={k: dict(v) for k, v in sens.items()}, scenarios=tuple(out),
    )


def load(path: Path | str | None = None, *, known_predicates: set[str] | None = None) -> Rules:
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise RulesError(f"cannot read {p}: {e}") from e
    return parse(data, known_predicates=known_predicates)

