"""The narrow ports to the family package (``friday/robin``, another builder). The lead wires real
implementations at merge; the in-memory fakes here are for tests and local runs.

Nothing in this package imports ``friday.robin``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Tier = Literal["INFO", "WATCH", "HIGH", "EMERGENCY"]
TIER_RANK: dict[str, int] = {"INFO": 0, "WATCH": 1, "HIGH": 2, "EMERGENCY": 3}
Lang = Literal["en", "hinglish", "hi"]
Sensitivity = Literal["calm", "balanced", "careful"]

# What a parent consents to, one by one. The app shows and records these; the server enforces them.
CONSENT_ITEMS: tuple[str, ...] = (
    "calls",  # unknown-call start/end and call duration (call-screening role + phone state)
    "camera",  # "camera is in use" (no picture, no app name)
    "remote_access",  # a remote-control app opened/installed (fixed list)
    "payment_app",  # a bank/UPI app came to the front (fixed list)
    "payment_notifications",  # amount, direction and payee kind of a payment notification (no text)
    "unknown_sources",  # an app installed from outside the store (optional)
    "heartbeat",  # "phone not seen for a long time"
    "share_check",  # the parent shares something for Robin to check
    "share_alert_child",  # the child may be told when a shared item looks risky
    "location",  # location with an SOS (optional)
    "voice_messages",  # the press-to-talk button may upload a voice message for speech-to-text
    "call_pattern",  # a call transcript (from the family package) may be scored for scam patterns; cues only are kept
)


@dataclass(frozen=True)
class ParentInfo:
    parent_id: str
    language: Lang = "hinglish"
    # profile hints from the family package, e.g. {"pensioner"}; None = unknown
    tags: frozenset[str] | None = None


@runtime_checkable
class AlertPort(Protocol):
    """Raise an alert to the child. ``details`` holds only enums, ints and the fixed fields documented in
    the engine (never message text, contact names or numbers). The family package routes it."""

    async def raise_alert(
        self, parent_id: str, tier: str, scenario: str, why: str, details: dict[str, Any]
    ) -> None: ...


@runtime_checkable
class ConsentPort(Protocol):
    async def has(self, parent_id: str, item: str) -> bool: ...

    async def set(self, parent_id: str, item: str, granted: bool, source: str = "app") -> None: ...


@runtime_checkable
class ParentLookup(Protocol):
    async def get(self, parent_id: str) -> ParentInfo | None: ...


@dataclass(frozen=True)
class VoiceResult:
    ok: bool = True
    reply_text: str | None = None  # optional short text the app may show/read back


@runtime_checkable
class VoiceIntake(Protocol):
    """The family/chat side transcribes the voice message and acts on it. It MUST delete the audio after
    speech-to-text. This package holds the bytes in memory for the call only and never stores them."""

    async def handle(self, parent_id: str, audio: bytes, mime: str, duration_s: int) -> VoiceResult: ...


@dataclass
class FakeVoiceIntake:
    received: list[dict[str, Any]] = field(default_factory=list)

    async def handle(self, parent_id: str, audio: bytes, mime: str, duration_s: int) -> VoiceResult:
        self.received.append({"parent_id": parent_id, "bytes": len(audio), "mime": mime, "duration_s": duration_s})
        return VoiceResult(True, None)


@dataclass
class FakeAlertPort:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def raise_alert(
        self, parent_id: str, tier: str, scenario: str, why: str, details: dict[str, Any]
    ) -> None:
        self.calls.append(
            {"parent_id": parent_id, "tier": tier, "scenario": scenario, "why": why, "details": dict(details)}
        )

    def of(self, parent_id: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["parent_id"] == parent_id]


@dataclass
class InMemoryConsent:
    granted: dict[str, set[str]] = field(default_factory=dict)

    async def has(self, parent_id: str, item: str) -> bool:
        return item in self.granted.get(parent_id, set())

    async def set(self, parent_id: str, item: str, granted: bool, source: str = "app") -> None:  # noqa: ARG002
        s = self.granted.setdefault(parent_id, set())
        (s.add if granted else s.discard)(item)

    def grant_all(self, parent_id: str, items: tuple[str, ...] = CONSENT_ITEMS) -> None:
        self.granted.setdefault(parent_id, set()).update(items)


@dataclass
class InMemoryParents:
    parents: dict[str, ParentInfo] = field(default_factory=dict)

    def add(self, parent_id: str, language: Lang = "hinglish", tags: frozenset[str] | None = None) -> None:
        self.parents[parent_id] = ParentInfo(parent_id, language, tags)

    async def get(self, parent_id: str) -> ParentInfo | None:
        return self.parents.get(parent_id)
