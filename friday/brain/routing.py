"""Model routing + token budgets (founder cost rule).

* Haiku (``claude-haiku-5-5``) for interpretation, extraction, nudge judgement,
  summaries, comparisons, shortlist reasons, translation.
* Sonnet (``claude-sonnet-5-5``) for live call turns.
* Opus (``claude-opus-5-5``) ONLY as an explicit escalation - never a default.
* Deterministic inputs never reach a model at all (see ``interpret`` fast path,
  hold / learned-IVR shortcuts in ``next_call_action``, rule-first nudges).

Per-purpose models come from ``Settings.model_for(purpose)`` (env ``FRIDAY_LLM_MODELS``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from friday.core.config import Settings
from friday.core.logging import get_logger

log = get_logger(__name__)

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"

DEFAULT_MODELS: dict[str, str] = {
    "interpret": HAIKU,
    "resolve_references": HAIKU,
    "extract": HAIKU,
    "judge_nudge": HAIKU,
    "summarize": HAIKU,
    "compare": HAIKU,
    "shortlist_reasons": HAIKU,
    "translate": HAIKU,
    "sim_business": HAIKU,
    "call_turn": SONNET,
}
# tight output caps: short structured outputs (cost rule 3)
MAX_TOKENS: dict[str, int] = {
    "interpret": 700,
    "resolve_references": 300,
    "extract": 2500,
    "judge_nudge": 300,
    "summarize": 500,
    "compare": 500,
    "shortlist_reasons": 400,
    "translate": 300,
    "sim_business": 150,
    "call_turn": 400,
}
EFFORT: dict[str, str] = {p: "low" for p in DEFAULT_MODELS}
# cheaper model when a task is over its token budget
CHEAPER: dict[str, str] = {SONNET: HAIKU, OPUS: SONNET}
DEFAULT_TASK_TOKEN_BUDGET = 60_000


@dataclass
class ModelRouter:
    """Routing is ``Settings.model_for(purpose)`` (``llm_models`` / ``llm_default_purpose_model``
    / ``llm_escalation_model``) and ``Settings.llm_task_token_budget``. Constructor args
    override per instance (tests); module defaults apply when no Settings are given."""

    settings: Settings | None = None
    overrides: dict[str, str] = field(default_factory=dict)
    escalation_model: str | None = None
    task_token_budget: int | None = None
    _used: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _alerted: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        s = self.settings
        if self.escalation_model is None:
            self.escalation_model = s.llm_escalation_model if s else OPUS
        if self.task_token_budget is None:
            self.task_token_budget = s.llm_task_token_budget if s else DEFAULT_TASK_TOKEN_BUDGET

    def model_for(self, purpose: str, *, task_id: str | None = None, escalate: bool = False) -> str:
        if escalate:
            return self.escalation_model  # type: ignore[return-value]
        if purpose in self.overrides:
            model = self.overrides[purpose]
        elif self.settings is not None:
            model = self.settings.model_for(purpose)
        else:
            model = DEFAULT_MODELS.get(purpose, HAIKU)
        if task_id and self.over_budget(task_id):
            return CHEAPER.get(model, model)
        return model

    def max_tokens(self, purpose: str) -> int:
        return MAX_TOKENS.get(purpose, 600)

    def effort(self, purpose: str) -> str | None:
        return EFFORT.get(purpose)

    # ------------------------------------------------------------------ budgets
    def record(self, task_id: str | None, tokens: int) -> None:
        if not task_id:
            return
        self._used[task_id] += tokens
        if self.over_budget(task_id) and task_id not in self._alerted:
            self._alerted.add(task_id)
            log.warning(
                "task %s over its LLM token budget (%d > %d): cheaper models now",
                task_id[:8],
                self._used[task_id],
                self.task_token_budget,
            )

    def used(self, task_id: str) -> int:
        return self._used.get(task_id, 0)

    def over_budget(self, task_id: str) -> bool:
        return self._used.get(task_id, 0) > (self.task_token_budget or 0)
