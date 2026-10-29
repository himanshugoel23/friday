# ruff: noqa: E501
"""Ports of the browser agent. The loop depends only on these, so every test runs on fakes and the real adapters
(Playwright page, OpenAI client, vault, OTP page) plug in at the edge."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from friday.browser_agent.types import Action, AskField, PageSnapshot, RunSpec, RunState


class AgentPage(Protocol):
    """One tab. Elements are addressed ONLY by the ids of the last ``snapshot`` (no selectors from the model)."""

    async def goto(self, url: str) -> None: ...
    async def snapshot(self) -> PageSnapshot: ...
    async def click(self, element_id: str) -> None: ...
    async def fill(self, element_id: str, value: str) -> None: ...
    async def select(self, element_id: str, option: str) -> None: ...
    async def check(self, element_id: str, checked: bool) -> None: ...
    async def upload(self, element_id: str, path: str) -> bool:
        """Attach a file to a file input. True only when the page shows the file attached (input.files read back)."""
        ...

    async def press(self, key: str) -> None: ...
    async def wait(self, ms: int) -> None: ...
    async def screenshot(self) -> bytes: ...
    def current_url(self) -> str: ...


class PageProvider(Protocol):
    def session(self, user_id: str, spec: RunSpec, domains: list[str]) -> AbstractAsyncContextManager[AgentPage]:
        """A guarded page for this user. May raise ``Blocked`` / ``Busy`` (see errors.py). ``domains`` is the CURRENT allow-list."""
        ...

    async def reopen(self, user_id: str, spec: RunSpec) -> None:
        """Close the user's context so the next ``session`` starts with the new allow-list (used after the user allows a domain)."""
        ...


class Decision(Protocol):
    action: Action
    cost_inr: float


class BrowserLLM(Protocol):
    async def decide(self, *, system: str, user: str) -> tuple[Action, float]:
        """Strict-JSON next action and its estimated cost in INR. Raises on invalid output (the loop counts that as a refusal)."""
        ...

    async def extract(self, *, question: str, page_text: str) -> tuple[str, float]: ...

    async def parse_answers(self, *, fields: list[AskField], reply: str) -> tuple[dict[str, str], float]:
        """Map a free-text reply onto the asked fields. Only keys in ``fields`` may come back."""
        ...


class FactSource(Protocol):
    async def load(self, user_id: str) -> dict[str, str]:
        """All remembered facts for the user: profile, resume facts, earlier answers. key -> value."""
        ...

    async def remember(self, user_id: str, key: str, value: str) -> None: ...


class FileStore(Protocol):
    def resolve(self, user_id: str, file_ref: str) -> str | None:
        """A local path for a file reference the USER registered (e.g. 'resume'); None when unknown. Never a free path."""
        ...


class RunStore(Protocol):
    def save(self, state: RunState) -> None: ...
    def load(self, run_id: str) -> RunState | None: ...
    def active_for(self, user_id: str) -> RunState | None: ...
    def list_open(self) -> list[RunState]: ...
    def delete_user(self, user_id: str) -> int: ...


class ProofSink(Protocol):
    def save(self, user_id: str, run_id: str, what: str, url: str, png: bytes) -> tuple[str, str]:
        """Returns (proof id, path). Small, auto-expiring."""
        ...


class LoginPort(Protocol):
    def credential_link(self, user_id: str, site: str, hosts: list[str]) -> str | None:
        """Secure vault page link for the user to save a login (never a chat password). None when saved logins are off."""
        ...

    def release(self, user_id: str, site: str, host: str) -> tuple[str, str] | None:
        """(username, password) for the worker only, and only on a host the login was saved for."""
        ...

    def otp_link(self, user_id: str, site: str, run_id: str) -> str | None:
        """Secure OTP page link; also arms the guarded login-OTP-in-chat path."""
        ...

    def take_otp(self, run_id: str) -> str | None: ...


class Audit(Protocol):
    def __call__(self, event: str, **detail: object) -> None: ...
