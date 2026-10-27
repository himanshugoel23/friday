"""Pick the facts that matter for THIS message (recency x frequency x word match).

Always kept: facts with a due date (reminders) and the user's own stated preferences are scored
like the rest but never fall below the recency floor. The result carries a ``why`` per item so the
trace shows why each fact was handed to the model.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from friday.core.models import Fact

_WORD = re.compile(r"[a-z0-9ऀ-ॿ]{3,}")
HALF_LIFE_DAYS = 90.0
INTERNAL_PREFIXES = ("alias_seen:",)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def rank_facts(facts: list[Fact], text: str | None, now: datetime, *, k: int = 12
               ) -> list[tuple[Fact, float, str]]:
    """``[(fact, score, why)]`` best first, at most ``k``; internal candidates are dropped."""
    words = _tokens(text or "")
    scored: list[tuple[Fact, float, str]] = []
    for f in facts:
        if f.key.startswith(INTERNAL_PREFIXES):
            continue
        hit = len(words & (_tokens(f.key.replace("_", " ")) | _tokens(f.value)))
        age_days = max(0.0, (now - f.updated_at).total_seconds() / 86400.0)
        recency = math.pow(0.5, age_days / HALF_LIFE_DAYS)
        score = 3.0 * hit + recency + 0.5 * float(f.confidence)
        if f.due_on is not None:
            score += 1.5
        why = f"match={hit} recency={recency:.2f}" + (" due" if f.due_on else "")
        scored.append((f, score, why))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]
