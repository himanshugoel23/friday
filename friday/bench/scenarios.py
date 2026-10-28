"""Load and validate the parity scenarios (data/benchmarks/instinct_parity.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from friday.bench.rules import RULES

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "benchmarks" / "instinct_parity.yaml"
CAPABILITIES = ("email", "calendar", "connector", "browser", "web", "call", "memory", "reminder", "safety", "language")
EXPECTED = ("works", "needs connector", "not built")
USERS = ("hinglish", "english")


class ScenarioError(ValueError):
    """The scenario file is malformed."""


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    capability: str
    messages: tuple[str, ...]
    rules: tuple[tuple[str, Any], ...]
    expected_today: str
    user: str = "hinglish"
    note: str = ""

    @property
    def rule_names(self) -> list[str]:
        return [n for n, _ in self.rules]


def _rule(raw: Any, sid: str) -> tuple[str, Any]:
    if isinstance(raw, str):
        name, arg = raw, None
    elif isinstance(raw, dict) and len(raw) == 1:
        (name, arg), = raw.items()
    else:
        raise ScenarioError(f"{sid}: bad rule entry {raw!r}")
    if name not in RULES:
        raise ScenarioError(f"{sid}: unknown rule {name!r}")
    return name, arg


def parse(data: Any) -> list[Scenario]:
    items = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ScenarioError("file needs a non-empty 'scenarios' list")
    out: list[Scenario] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ScenarioError(f"scenario entry is not a mapping: {raw!r}")
        sid = str(raw.get("id") or "")
        if not sid or sid in seen:
            raise ScenarioError(f"missing or duplicate id {sid!r}")
        seen.add(sid)
        msgs = raw.get("messages")
        if not isinstance(msgs, list) or not msgs or not all(isinstance(m, str) and m.strip() for m in msgs):
            raise ScenarioError(f"{sid}: 'messages' must be a non-empty list of strings")
        cap = raw.get("capability")
        if cap not in CAPABILITIES:
            raise ScenarioError(f"{sid}: capability must be one of {CAPABILITIES}")
        exp = raw.get("expected_today")
        if exp not in EXPECTED:
            raise ScenarioError(f"{sid}: expected_today must be one of {EXPECTED}")
        user = raw.get("user", "hinglish")
        if user not in USERS:
            raise ScenarioError(f"{sid}: user must be one of {USERS}")
        rules = raw.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ScenarioError(f"{sid}: needs at least one rule")
        if not raw.get("category"):
            raise ScenarioError(f"{sid}: needs a category")
        out.append(
            Scenario(
                id=sid, category=str(raw["category"]), capability=cap, messages=tuple(msgs),
                rules=tuple(_rule(r, sid) for r in rules), expected_today=exp, user=user,
                note=str(raw.get("note") or ""),
            )
        )
    return out


def load(path: Path | str | None = None) -> list[Scenario]:
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise ScenarioError(f"cannot read {p}: {e}") from e
    except yaml.YAMLError as e:
        raise ScenarioError(f"bad YAML in {p}: {e}") from e
    return parse(data)

