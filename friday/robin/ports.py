# ruff: noqa: E501
"""Ports of the Robin family core: how it speaks on a phone, how it writes to the child, who is a user.

``ParentCaller`` is implemented by ``telephony.TelephonyParentCaller`` (real, refuses while the spoken
lines are PENDING approval) and by ``FakeParentCaller`` (tests and the simulator; dials nothing).
The caller never decides WHETHER to ring; ``context.Ctx.call`` does, after consent, quiet hours, the care
gate and the CallGate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from friday.core.models import ReplyButton, User
from friday.robin import answers as ans
from friday.robin import lines
from friday.robin.models import AnswerRaw, CallOutcome, CallResult, Family, Member, Step

Sender = Callable[[str, str, Sequence[ReplyButton]], Awaitable[None]]  # (child user id, text, buttons)


@runtime_checkable
class ParentCaller(Protocol):
    async def converse(
        self, *, member: Member, family: Family, purpose: str, steps: list[Step], dedupe_key: str, brand: str, max_seconds: int = 180
    ) -> CallOutcome: ...

    async def bridge(self, *, child: Member, parent: Member, family: Family, dedupe_key: str, brand: str) -> CallOutcome: ...


class UserDirectory(Protocol):
    async def get(self, user_id: str) -> User | None: ...


@dataclass
class CallRecord:
    member_id: str
    role: str
    purpose: str
    line_keys: list[str]
    texts: list[str]
    dedupe_key: str
    kind: str = "converse"


@dataclass
class FakeParentCaller:
    """Scripted. ``outcomes`` are consumed in order, the last repeats (default NO_ANSWER). A step's
    answer is looked up in ``answers[line_key]`` (default: no words). The same ``dedupe_key`` returns the
    first outcome again and records nothing (a replayed dial is a no-op). ``hook`` runs before each real
    ring (tests tap 'Mark safe' mid-call or raise)."""

    outcomes: list[CallOutcome] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    hook: Callable[[CallRecord], None] | None = None
    calls: list[CallRecord] = field(default_factory=list)
    seen: dict[str, CallOutcome] = field(default_factory=dict)

    def script(self, *outcomes: CallOutcome | CallResult) -> FakeParentCaller:
        self.outcomes = [o if isinstance(o, CallOutcome) else CallOutcome(result=o) for o in outcomes]
        return self

    def _next(self) -> CallOutcome:
        if not self.outcomes:
            return CallOutcome(result=CallResult.NO_ANSWER, detail="fake")
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]

    async def converse(
        self, *, member: Member, family: Family, purpose: str, steps: list[Step], dedupe_key: str, brand: str, max_seconds: int = 180
    ) -> CallOutcome:
        if dedupe_key in self.seen:
            return self.seen[dedupe_key]
        texts = [lines.say(k, member.language, brand=brand, **s.slots) for s in steps for k in (s.line, s.on_yes, s.on_no) if k]  # renders EVERY line: a missing slot fails the test
        rec = CallRecord(member.id, member.role.value, purpose, [s.line for s in steps], texts, dedupe_key)
        if self.hook is not None:
            self.hook(rec)
        self.calls.append(rec)
        out = self._next()
        if out.result == CallResult.ANSWERED and not out.answers:
            out = out.model_copy(update={"answers": [AnswerRaw(line=s.line, text=self.answers.get(s.line, "")) for s in steps if s.expect != "none"]})
        if out.result == CallResult.ANSWERED and any(ans.is_stop(a.text) for a in out.answers):
            out = out.model_copy(update={"detail": "stop_requested"})
        self.seen[dedupe_key] = out
        return out

    async def bridge(self, *, child: Member, parent: Member, family: Family, dedupe_key: str, brand: str) -> CallOutcome:
        if dedupe_key in self.seen:
            return self.seen[dedupe_key]
        rec = CallRecord(child.id, child.role.value, "bridge", ["bridge.child", "bridge.parent"], [], dedupe_key, kind="bridge")
        self.calls.append(rec)
        out = self._next()
        self.seen[dedupe_key] = out
        return out


@dataclass
class Sent:
    user_id: str
    text: str
    buttons: list[ReplyButton]


@dataclass
class RecordingSender:
    """A ``Sender`` that remembers what was sent (and can also deliver to other users by phone, e.g. the second contact)."""

    sent: list[Sent] = field(default_factory=list)
    fail: bool = False

    async def __call__(self, user_id: str, text: str, buttons: Sequence[ReplyButton]) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(Sent(user_id, text, list(buttons)))

    def texts(self) -> list[str]:
        return [s.text for s in self.sent]


def care_active_fn(care: Any = None) -> Callable[[str], Any]:
    """``care.is_active(user_id)`` from the care-protocol builder, imported defensively (it may be sync or
    async; ``Ctx`` awaits an awaitable). Absent or broken -> inactive."""
    if care is not None:
        return care
    import importlib

    for mod in ("friday.guardrails.care", "friday.care"):
        try:
            fn = getattr(importlib.import_module(mod), "is_active", None)
        except Exception:  # noqa: BLE001 - not delivered yet, or broken: treat as inactive
            fn = None
        if callable(fn):
            return fn
    return lambda user_id: False


@runtime_checkable
class ParentChannel(Protocol):
    """The parent's PRIMARY channel: WhatsApp, voice-note first (docs/ROBIN_FAMILY_CORE.md section 10). DESIGN ONLY: no real
    adapter exists yet (Meta is blocked; outside the 24 h window a pre-approved template is needed). Replies are text + a TTS
    voice note; inbound voice notes go through the existing media/speech path (STT) and arrive as text in ``parent_said``."""

    async def send_text(self, member: Member, text: str) -> bool: ...
    async def send_voice_note(self, member: Member, text: str, language: str) -> bool: ...
    async def send_template(self, member: Member, template: str, params: dict[str, str], media: bytes | None = None, media_mime: str | None = None) -> bool: ...


@dataclass
class FakeParentChannel:
    texts: list[tuple[str, str]] = field(default_factory=list)  # (member id, text)
    voice_notes: list[tuple[str, str, str]] = field(default_factory=list)
    templates: list[tuple[str, str, dict[str, str], str | None]] = field(default_factory=list)

    async def send_text(self, member: Member, text: str) -> bool:
        self.texts.append((member.id, text))
        return True

    async def send_voice_note(self, member: Member, text: str, language: str) -> bool:
        self.voice_notes.append((member.id, text, language))
        return True

    async def send_template(self, member: Member, template: str, params: dict[str, str], media: bytes | None = None, media_mime: str | None = None) -> bool:
        self.templates.append((member.id, template, params, media_mime))
        return True
