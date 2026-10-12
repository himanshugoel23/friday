"""Plan templates: archetype base + per-category overrides, merged from data/plans.yaml."""

from __future__ import annotations

from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .taxonomy import DATA_DIR, buckets, categories


class PlanTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archetype: str
    category: str | None
    steps: list[str]
    required: list[str]
    optional: list[str]
    defaults: dict[str, str]
    n_vendors: int
    call_mode: str  # all | first_success | none
    radius_km: float
    hard_max_km: float
    radius_steps: list[float]
    questions: dict[str, dict[str, str]] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def raw() -> dict:
    return yaml.safe_load((DATA_DIR / "plans.yaml").read_text(encoding="utf-8"))


def message(key: str, lang: str, **kw: object) -> str:
    """User-facing template text; Devanagari Hindi falls back to the Hinglish wording."""
    entry = raw()["messages"][key]
    text = entry["en"] if lang == "en" else entry["hinglish"]
    return text.format(**kw) if kw else text


def slot_kind(slot: str) -> str:
    return raw()["slots"][slot]["kind"]


def slot_question(slot: str, lang: str, template: PlanTemplate | None = None) -> str:
    entry = (template.questions.get(slot) if template else None) or raw()["slots"][slot]
    return entry["en"] if lang == "en" else entry["hinglish"]


def _uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def build_template(archetype: str, category: str | None = None) -> PlanTemplate:
    data = raw()
    if archetype not in data["archetypes"]:
        raise KeyError(f"unknown archetype {archetype!r}")
    base = dict(data["archetypes"][archetype])
    required = list(base["required"])
    optional = list(base["optional"])
    defaults = dict(base["defaults"])
    questions: dict[str, dict[str, str]] = {}
    radius = hard = None
    if category is not None:
        info = categories()[category]
        radius, hard = info.radius_km, info.hard_max_km
        cat_over = data["categories"].get(category, {})
        for layer in (cat_over.get("*", {}), cat_over.get(archetype, {})):
            required = [r for r in required if r not in layer.get("required_remove", [])]
            required = _uniq(required + layer.get("required_add", []))
            optional = _uniq(optional + layer.get("optional_add", []))
            defaults.update(layer.get("defaults", {}))
            questions.update(layer.get("questions", {}))
            radius = layer.get("radius_km", radius)
            hard = layer.get("hard_max_km", hard)
    optional = [o for o in optional if o not in required]
    if radius is None or hard is None:
        radius, hard = 5.0, 10.0  # only the handoff plan has no category
    steps_def = categories()[category].radius_steps() if category else [radius]
    if category and (radius != categories()[category].radius_km):
        steps_def = sorted({float(radius), float(round(radius * 1.5)), float(hard)})
        steps_def = [s for s in steps_def if s <= hard]
    return PlanTemplate(
        archetype=archetype, category=category, steps=list(base["steps"]),
        required=required, optional=optional, defaults=defaults,
        n_vendors=base["n_vendors"], call_mode=base["call_mode"],
        radius_km=float(radius), hard_max_km=float(hard), radius_steps=steps_def,
        questions=questions,
    )


def archetype_for(bucket: str) -> str:
    return buckets()[bucket].archetype


def template_for(bucket: str, category: str | None) -> PlanTemplate:
    arch = archetype_for(bucket)
    return build_template(arch, None if arch == "handoff" else category)
