"""Ports the live engine talks to. Real adapters live in thin files (``sarvam_adapter.py``);
tests and the simulation use fakes. Nothing here imports the voice stack."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from friday.liveagent.contracts import CallLanguage


class CallDropped(Exception):  # noqa: N818 - a signal, not an error
    """The line went away (callee hung up, network drop, provider error)."""


class HeardUtterance(BaseModel):
    """What the telephony leg heard in one listen window (text may be empty for music/silence)."""

    text: str = ""
    language: str | None = None  # "hi" | "en" | "hinglish" as tagged by the STT, if known
    confidence: float | None = None
    # human | ivr_prompt | hold_music | queue_announcement | voicemail | silence | unknown
    audio_class: str = "human"
    duration_s: float = 0.0  # audio length of this chunk (hold accounting)


@runtime_checkable
class TelephonyPort(Protocol):
    async def speak(self, text: str, language: CallLanguage) -> None: ...

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        """Next thing the callee side produced, or None when nothing happened in ``timeout_s``."""
        ...

    async def send_dtmf(self, digits: str) -> None: ...

    async def hangup(self) -> None: ...


@runtime_checkable
class UserChannel(Protocol):
    """Warm-transfer / ask-the-user hook: a mid-call question to the user with a time limit."""

    async def ask_user(self, question: str, *, timeout_s: float) -> str | None:
        """The user's answer, or None when they did not answer in time."""
        ...


@runtime_checkable
class MoveModel(Protocol):
    """An LLM that ONLY proposes the next move (a dict). Its output is validated by code."""

    async def propose(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class LineModel(Protocol):
    """Fully generated line mode (OFF by default). Output passes the same guards."""

    async def generate(self, payload: dict[str, Any]) -> str: ...
