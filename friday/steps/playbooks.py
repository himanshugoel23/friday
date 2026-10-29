# ruff: noqa: E501
"""Data playbooks -> a StepPlan, before the browser is touched. No model, no network.

The allowed domains come from the USER's words (a link, a domain, a brand word) or from the shopping site table
(``friday/shopping/knowledge``), never from a model and never from a page."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from friday.shopping import catalog
from friday.steps.types import Step, StepPlan, StepType

DATA = Path(__file__).parent / "data" / "playbooks.v1.json"
PACK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|grams?|l|ltr|litres?|liters?|ml)\b", re.I)
_LEAD = re.compile(r"^\W*(?:the|my|a|an|some|me|please|pls|get|check|find|show|batao|dikhao)\b\W*", re.I)
_TRAIL = re.compile(r"\W*\b(?:please|pls|price|rate|daam|bhav|cost|today|now)\W*$", re.I)


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _matchers() -> dict[str, list[re.Pattern[str]]]:
    return {name: [re.compile(p, re.I) for p in pb["match"]] for name, pb in data()["playbooks"].items()}


def forbidden_re() -> re.Pattern[str]:
    words = sorted(data()["forbidden"], key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z])", re.I)


def steps_of(name: str) -> list[Step]:
    return [Step(type=StepType(s["type"]), args=dict(s.get("args", {}))) for s in data()["playbooks"][name]["steps"]]


def goal_template(key: str) -> str:
    return str(data()["goals"][key])


class _Safe(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def render_goal(key: str, **kw: str) -> str:
    return " ".join(goal_template(key).format_map(_Safe(kw)).split())


# ----------------------------------------------------------------------------- sites
def resolve_store(word: str, text: str) -> tuple[list[str], str, str]:
    """-> (allowed domains, start url, display name). From the shopping site table by name, else from what the user wrote."""
    from friday.browser_agent.gateway import domains_from_text
    from friday.shopping.sites import load_knowledge

    w = (word or "").lower().strip(".,!? ")
    low = (text or "").lower()
    for site, kb in load_knowledge().items():
        display = str(kb["display"])
        named = bool(w) and (w == site or w in display.lower() or site in w)
        in_text = not w and re.search(rf"(?<![a-z]){re.escape(site)}(?![a-z])", low) is not None  # 'track my order on zepto'
        if named or in_text:
            doms = [str(d) for d in kb["domains"]]
            return doms, f"https://{doms[0]}/", display
    doms, start = domains_from_text(f"{word} {text}")
    if doms:
        return doms, start, doms[0]
    return [], "", ""


# ----------------------------------------------------------------------------- price_check slots
def _clean_item(raw: str) -> str:
    s = raw.strip()
    for _ in range(3):
        s = _LEAD.sub("", s).strip()
    s = _TRAIL.sub("", s).strip()
    return s[:80]


def variant_slots(item: str, cat: catalog.Category | None) -> dict[str, str]:
    """A pack ('5 kg') and/or a brand the user named. Empty dict when the user gave no variant."""
    out: dict[str, str] = {}
    m = PACK_RE.search(item)
    if m:
        out["pack"] = f"{m.group(1)} {m.group(2).lower()}"
    if cat is not None:
        low = item.lower()
        for b in cat.brands:
            if re.search(rf"(?<![a-z]){re.escape(b.lower())}(?![a-z])", low):
                out["brand"] = b.lower()
                break
    return out


def match(text: str) -> StepPlan | None:
    """A data playbook for this request, or None (the old flow keeps it). A site is required: no site, no plan."""
    t = (text or "").strip()
    if not t or len(t) > 240:
        return None
    for name, pats in _matchers().items():
        for pat in pats:
            m = pat.search(t)
            if not m:
                continue
            if name == "price_check":
                item = _clean_item(m.group("item"))
                doms, start, display = resolve_store(m.group("store"), "")
                if not item or not doms:
                    continue
                cat = catalog.match(item)
                slots = {"item": item, "store": display, "query": item, **variant_slots(item, cat)}
                if cat is not None:
                    slots["category"] = cat.id
                return StepPlan(playbook=name, goal=t, domains=doms, start_url=start, slots=slots, steps=steps_of(name))
            doms, start, display = resolve_store("", t)
            if not doms:
                continue
            return StepPlan(playbook=name, goal=t, domains=doms, start_url=start, slots={"store": display}, steps=steps_of(name))
    return None
