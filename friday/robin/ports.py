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
HelpHandler = Callable[[str], Awaitable[bool]]  # (what the listener said) -> True only when the SOS alert was ACCEPTED; the call speaks "I have told {child}" only then


@runtime_checkable
class ParentCaller(Protocol):
    async def converse(
        self, *, member: Member, family: Family, purpose: str, steps: list[Step], dedupe_key: str, brand: str, max_seconds: int = 180,
        on_help: HelpHandler | None = None,
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
    help_line: str | None = None  # the line spoken after a help word: sos.parent (alert accepted) or widget.sos_failed (honest, not accepted)


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
        self, *, member: Member, family: Family, purpose: str, steps: list[Step], dedupe_key: str, brand: str, max_seconds: int = 180,
        on_help: HelpHandler | None = None,
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
        helped = next((a.text for a in out.answers if ans.is_help(a.text) or ans.is_threat(a.text)), None)
        if out.result == CallResult.ANSWERED and helped is not None and out.detail != "stop_requested":  # like the real caller: help ends the call, the child is told only if the alert was accepted
            ok = False
            if on_help is not None:
                try:
                    ok = bool(await on_help(helped))
                except Exception:  # noqa: BLE001
                    ok = False
            rec.help_line = "sos.parent" if ok else "widget.sos_failed"
            out = out.model_copy(update={"detail": "help_requested"})
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
    """The parent's PRIMARY channel: WhatsApp, voice-note first (docs/ROBIN_FAMILY_CORE.md section 10). Implemented by
    ``channel.WhatsAppParentChannel`` (Meta send BLOCKED: tested with fakes only; outside the 24 h window a pre-approved template is used). Replies are text + a TTS
    voice note; inbound voice notes go through the existing media/speech path (STT) and arrive as text in ``parent_said``."""

    async def send_text(self, member: Member, text: str) -> bool: ...
    async def send_voice_note(self, member: Member, text: str, language: str) -> bool: ...
    async def send_template(self, member: Member, template: str, params: dict[str, str], media: bytes | None = None, media_mime: str | None = None) -> bool: ...


@dataclass
class FakeParentChannel:
    """Same behaviour as ``channel.WhatsAppParentChannel`` without a network: ``window_open=False`` turns every text and voice note into
    the pre-approved message template (recorded in ``templates``); ``fail=True`` returns False (the caller then queues the line in the app outbox)."""

    texts: list[tuple[str, str]] = field(default_factory=list)  # (member id, text)
    voice_notes: list[tuple[str, str, str]] = field(default_factory=list)
    templates: list[tuple[str, str, dict[str, str], str | None]] = field(default_factory=list)
    window_open: bool = True
    fail: bool = False
    inbound_from: list[str] = field(default_factory=list)  # phones that wrote to us (each opens the window)
    reopens: list[tuple[str, str, str]] = field(default_factory=list)  # (member id, parent label, child name): the "say anything" template (T08 outbox drain)
    log: list[str] = field(default_factory=list)  # order of calls: "reopen", "voice", "text" (tests check the reopen comes first)

    async def note_inbound(self, phone: str) -> None:
        self.inbound_from.append(phone)
        self.window_open = True

    async def in_window(self, phone: str) -> bool:  # noqa: ARG002
        return self.window_open

    async def reopen(self, member: Member, parent_label: str, child_name: str) -> bool:
        if self.fail:
            return False
        self.reopens.append((member.id, parent_label, child_name))
        self.log.append("reopen")
        return True

    async def send_text(self, member: Member, text: str) -> bool:
        if self.fail:
            return False
        self.log.append("text")
        if not self.window_open:
            self.templates.append((member.id, "robin_parent_message", {"line": text}, None))
            return True
        self.texts.append((member.id, text))
        return True

    async def send_voice_note(self, member: Member, text: str, language: str) -> bool:
        if self.fail:
            return False
        self.log.append("voice")
        if not self.window_open:
            self.templates.append((member.id, "robin_parent_message", {"line": text}, None))
            return True
        self.voice_notes.append((member.id, text, language))
        return True

    async def send_template(self, member: Member, template: str, params: dict[str, str], media: bytes | None = None, media_mime: str | None = None) -> bool:
        if self.fail:
            return False
        self.templates.append((member.id, template, params, media_mime))
        return True


# ---------------------------------------------------------------------------- erase hooks (no import cycle)
# "Delete everything" must also drop what OTHER Robin packages hold for a parent (friday/robindevice: its encrypted
# state rows, the pairing codes, the live in-memory analyzers and token cache). The family package never imports
# them: they register an async hook here when they are mounted, and ``FamilyService.erase`` /
# ``DataPurger.purge_user`` call ``run_erase_hooks`` with the parent member ids. A failing hook never stops the erase.
EraseHook = Callable[[str], Awaitable[dict[str, int]]]  # (parent member id) -> counts of what was removed
_ERASE_HOOKS: dict[str, EraseHook] = {}


def register_erase_hook(name: str, hook: EraseHook) -> None:
    _ERASE_HOOKS[name] = hook  # same name replaces (a re-mounted app does not stack hooks)


def unregister_erase_hook(name: str) -> None:
    _ERASE_HOOKS.pop(name, None)


async def run_erase_hooks(parent_ids: Sequence[str]) -> dict[str, int]:
    from friday.core.logging import get_logger

    out: dict[str, int] = {}
    for name, hook in list(_ERASE_HOOKS.items()):
        for pid in parent_ids:
            try:
                for k, v in (await hook(pid) or {}).items():
                    out[f"{name}.{k}"] = out.get(f"{name}.{k}", 0) + int(v)
            except Exception as e:  # noqa: BLE001 - one broken hook never blocks erasure
                get_logger(__name__).error("robin: erase hook %s failed (%s)", name, type(e).__name__)
    return out
