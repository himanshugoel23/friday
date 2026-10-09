"""Authoring backends: who writes the draft.

* ``OfflineAuthor``  deterministic template generator (default; no model, no network, no key)
* ``LLMAuthor``      the real model through the existing ``LLMClient`` abstraction (``--live``)

A backend answers one ``AuthorRequest`` with the text of a reply in the marker format of
``prompt.py``. Tests use a scripted backend of their own (see tests/playbooks/test_authoring.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from friday.core.interfaces import LLMMessage
from friday.playbooks.authoring import offline, prompt
from friday.playbooks.authoring.knowledge import BusinessType

PURPOSE = "playbook_author"  # a heavy, one-off authoring purpose (never used on a live call)
DEFAULT_MAX_TOKENS = 14000  # per model call; the hard output budget


class LiveRefused(RuntimeError):
    """--live was asked for but cannot run (no LLM key, fake provider)."""


@dataclass
class AuthorRequest:
    kind: Literal["draft", "repair", "patch"]
    business_type: BusinessType
    system: str
    user: str
    attempt: int = 1
    previous_playbook: str = ""
    previous_personas: str = ""


@dataclass
class AuthorReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_inr: float = 0.0
    model: str = ""


class AuthorBackend(Protocol):
    name: str
    is_live: bool
    max_tokens: int
    model: str

    async def generate(self, req: AuthorRequest) -> AuthorReply: ...

    def estimate_cost_inr(self, input_tokens: int, output_tokens: int) -> float: ...


class OfflineAuthor:
    """Deterministic template generator. A repair or patch returns the same template (it is
    valid by construction), so the loop ends after the first dry run."""

    name = "offline template generator (no model)"
    is_live = False
    max_tokens = 0
    model = "none"

    async def generate(self, req: AuthorRequest) -> AuthorReply:
        bt = req.business_type
        text = prompt.format_reply(
            offline.render_playbook_yaml(bt, "the offline template generator"),
            offline.render_personas_yaml(bt, "the offline template generator"),
        )
        return AuthorReply(text=text, model="offline")

    def estimate_cost_inr(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


@dataclass
class LLMAuthor:
    """The real model. Cost routing: purpose ``playbook_author`` (a bigger model than the
    background purposes, allowed because it runs once per business type, never on a call)."""

    llm: Any  # friday.core.interfaces.LLMClient
    model: str
    provider: str = "anthropic"
    max_tokens: int = DEFAULT_MAX_TOKENS
    prices: dict[str, Any] = field(default_factory=dict)
    usd_to_inr: float = 84.0
    close: Callable[[], Any] | None = None
    is_live = True

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"live model {self.model} ({self.provider})"

    async def generate(self, req: AuthorRequest) -> AuthorReply:
        resp = await self.llm.complete(
            system=req.system,
            messages=[LLMMessage(role="user", content=req.user)],
            purpose=PURPOSE,
            model=self.model,
            max_tokens=self.max_tokens,
            effort="medium",
        )
        cost = self.estimate_cost_inr(resp.input_tokens, resp.output_tokens)
        return AuthorReply(
            text=resp.text,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_inr=cost,
            model=resp.model or self.model,
        )

    def estimate_cost_inr(self, input_tokens: int, output_tokens: int) -> float:
        if self.provider == "openai":
            from friday.brain.openai_llm import estimate_cost_inr as est

            return est(self.model, input_tokens, output_tokens, 0, prices=self.prices,
                       usd_to_inr=self.usd_to_inr)
        from friday.brain.llm import estimate_cost_inr as est_a

        return est_a(self.model, input_tokens, output_tokens)


def load_settings() -> Any:
    """The app settings (reads the environment / .env). Only ever called for ``--live``;
    tests replace this function."""
    from friday.core.config import Settings

    return Settings()


def build_live_author(max_tokens: int = DEFAULT_MAX_TOKENS) -> LLMAuthor:
    """The real LLM through the existing abstraction. Refuses without an LLM key."""
    settings = load_settings()
    provider = settings.resolve_llm()
    if provider == "fake" or not settings.llm_key_configured():
        key = settings.llm_key_name() or "ANTHROPIC_API_KEY or OPENAI_API_KEY"
        raise LiveRefused(
            f"--live needs an LLM key ({key} in the environment or .env). Not running; "
            "the offline draft (no --live) needs no key."
        )
    # a 10k-token answer takes minutes; the default 30 s per-request timeout is for short jobs
    settings = settings.model_copy(update={"llm_timeout_s": 420.0, "openai_timeout_s": 420.0})
    from friday.core.container import Container

    container = Container(settings)
    llm = container.llm
    return LLMAuthor(
        llm=llm,
        model=settings.model_for(PURPOSE),
        provider=provider,
        max_tokens=max_tokens,
        prices=dict(settings.openai_prices_usd_per_mtok),
        usd_to_inr=settings.openai_usd_to_inr,
        close=container.aclose,
    )
