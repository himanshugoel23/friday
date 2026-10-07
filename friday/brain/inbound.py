"""Inbound business call-backs & missed calls (BRIEF section E, items 30-35).

Core has no inbound fields on ``CallBrief`` yet (proposed in docs/CORE_CHANGES.md),
so the brain uses ``InboundCallBrief`` - a ``CallBrief`` subclass carrying
``direction`` and an ``InboundContext``. It IS a ``CallBrief`` (the voice runner
needs nothing new); the policy reads the extras via ``inbound_of(brief)``, which
also works once core grows ``CallBrief.direction`` / ``CallBrief.inbound``.

Three situations
* ``answered``: a business called Friday's number back and we answered.
* ``missed_call``: a business rang and we missed it; Friday calls them back
  (an OUTBOUND call with call-back context).
* ``unknown``: no match in call memory -> take a message, reveal nothing.
"""

from __future__ import annotations

# Merged into core (docs/CORE_CHANGES.md, Stage 3); re-exported here.
from friday.core.models import (  # noqa: E402
    CLOSED_ELSEWHERE,
    CallBrief,
    CallDirection,
    InboundContext,
    InboundKind,
    RelatedTask,
    Resolution,
    TaskType,
)

__all__ = [
    "CLOSED_ELSEWHERE",
    "InboundCallBrief",
    "InboundContext",
    "InboundKind",
    "RelatedTask",
    "Resolution",
    "inbound_of",
]


class _AwaitableBrief:
    """Lets ``Brain.build_call_brief`` be used both ways: ``await brain.build_call_brief(...)``
    (the Protocol is async) and plain ``brain.build_call_brief(...)`` (the brief is
    built synchronously - no I/O - so awaiting just returns it)."""

    def __await__(self):  # noqa: ANN204
        if False:  # pragma: no cover - makes this a generator
            yield None
        return self


class AwaitableCallBrief(_AwaitableBrief, CallBrief):
    pass


class InboundCallBrief(_AwaitableBrief, CallBrief):
    direction: CallDirection = CallDirection.INBOUND
    inbound: InboundContext | None = None


def inbound_of(brief: CallBrief) -> InboundContext | None:
    ctx = getattr(brief, "inbound", None)
    if isinstance(ctx, InboundContext):
        return ctx
    if isinstance(ctx, dict):
        return InboundContext.model_validate(ctx)
    return None


def task_label(task_type: TaskType, goal: str, item: str | None = None) -> str:
    """Short spoken label for "is this about the haircut or the facial?"."""
    g = (item or goal or "").strip()
    low = g.lower()
    for prefix in ("book ", "get ", "find ", "order ", "check ", "ask ", "cancel ", "move "):
        if low.startswith(prefix):
            g = g[len(prefix):]
            break
    for cut in (" for ", " at ", " with ", ",", " on ", " tomorrow", " today"):
        idx = g.lower().find(cut)
        if idx > 0:
            g = g[:idx]
    g = g.strip().removeprefix("a ").removeprefix("an ").strip()
    return g[:40] or task_type.value.replace("_", " ")
