"""BriefTemplate data - one JSON file per TaskType (data, not code branches).

``template_for(task_type)`` returns a validated ``BriefTemplate``; ``load_templates()``
loads them all (cached). Adding a task type = adding a JSON file here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from friday.core.models import BriefTemplate, TaskType

TEMPLATE_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_templates() -> dict[TaskType, BriefTemplate]:
    out: dict[TaskType, BriefTemplate] = {}
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        tpl = BriefTemplate.model_validate(json.loads(path.read_text(encoding="utf-8")))
        out[tpl.task_type] = tpl
    return out


def template_for(task_type: TaskType) -> BriefTemplate:
    templates = load_templates()
    try:
        return templates[TaskType(task_type)].model_copy(deep=True)
    except KeyError:
        raise KeyError(f"no BriefTemplate for task type {task_type!r}") from None


def missing_fields(template: BriefTemplate, values: dict[str, object]) -> list[str]:
    """``required_fields`` entries use ``a|b|c`` for alternatives; returns the first
    alternative of every unsatisfied requirement."""
    missing: list[str] = []
    for req in template.required_fields:
        alts = req.split("|")
        if not any(values.get(a) for a in alts):
            missing.append(alts[0])
    return missing
