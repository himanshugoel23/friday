"""Closed lists: 10 request buckets and the 22 Wave 1 vendor categories (data/*.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DATA_DIR = Path(__file__).parent / "data"


class Bucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    archetype: str
    keywords: list[str] = Field(default_factory=list)


class CategoryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    radius_km: float
    hard_max_km: float
    keywords: list[str] = Field(default_factory=list)

    def radius_steps(self) -> list[float]:
        """Default radius, one widening step, hard max (ascending, unique)."""
        mid = float(round(self.radius_km * 1.5))
        steps = sorted({float(self.radius_km), mid, float(self.hard_max_km)})
        return [s for s in steps if s <= self.hard_max_km]


def _load(name: str) -> dict:
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def buckets() -> dict[str, Bucket]:
    return {k: Bucket(key=k, **v) for k, v in _load("buckets.yaml").items()}


@lru_cache(maxsize=1)
def categories() -> dict[str, CategoryInfo]:
    return {k: CategoryInfo(key=k, **v) for k, v in _load("categories.yaml").items()}


def bucket_keys() -> list[str]:
    return list(buckets())


def category_keys() -> list[str]:
    return list(categories())
