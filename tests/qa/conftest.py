"""Fixtures for the QA tests: fake backends only. No real call, no network, no .env."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from friday.core.config import Settings
from friday.qa import override
from friday.qa.config import QaConfig
from friday.qa.models import CallReport, CallSpec
from friday.qa.runner import QaRunner
from friday.qa.safety import QaGuard
from friday.qa.scenarios import Scenario
from friday.qa.store import QaStore

NUMBER = "+919800000042"  # invented
OTHER = "+919800000077"  # invented: a number that must never be dialled


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in list(__import__("os").environ):
        if name.startswith(("FRIDAY_", "SARVAM_", "ANTHROPIC_", "OPENAI_", "WHATSAPP_")):
            monkeypatch.delenv(name, raising=False)
    override.deactivate()
    yield
    override.deactivate()


def make_settings(**kw: Any) -> Settings:
    values: dict[str, Any] = dict(
        mode="live",
        profile="pilot",
        pilot_allowed_numbers=[NUMBER],
        pause_file="/nonexistent/friday-test-pause",
    )
    values.update(kw)
    return Settings(_env_file=None, **values)


def make_qa(tmp_path: Path, **kw: Any) -> QaConfig:
    values: dict[str, Any] = dict(live=True, dir=str(tmp_path / "qa"), countdown_s=3)
    values.update(kw)
    return QaConfig(**values)


class FakeCalls:
    """Records what it was asked to dial; never touches a network."""

    def __init__(self, report: CallReport | None = None, hold: asyncio.Event | None = None) -> None:
        self.specs: list[CallSpec] = []
        self.report = report or CallReport(
            status="completed",
            duration_s=42,
            cost_inr=3.5,
            summary="answered / ok",
            transcript=[{"who": "friday", "text": "Hello"}, {"who": "callee", "text": "Hi"}],
        )
        self.hold = hold
        self.active_during: list[Any] = []
        self.hung = 0

    async def run(self, spec: CallSpec, emit: Any) -> CallReport:
        self.specs.append(spec)
        self.active_during.append(override.active())
        emit("Placing the call... answer your phone")
        if self.hold is not None:
            await self.hold.wait()
        return self.report

    def hangup(self) -> None:
        self.hung += 1
        if self.hold is not None:
            self.hold.set()


class FakeChat:
    def __init__(self) -> None:
        self.ran: list[str] = []

    async def run(self, scenario: Scenario, emit: Any) -> CallReport:
        self.ran.append(scenario.id)
        emit("Friday: hello")
        return CallReport(
            status="chat", summary="ok", transcript=[{"who": "friday", "text": "hello"}]
        )


async def _no_sleep(_s: float) -> None:
    await asyncio.sleep(0)


async def fake_shortlist(query: str, area: str) -> dict[str, Any]:
    return {
        "source": "sample",
        "items": [{"name": "Shreya Salon", "rating": 4.4, "address": area}],
        "note": "Sample.",
    }


class World:
    def __init__(self, tmp_path: Path, **qa_kw: Any) -> None:
        self.settings = make_settings()
        self.qa = make_qa(tmp_path, **qa_kw)
        self.store = QaStore(self.qa.path)
        self.paused = False
        self.guard = QaGuard(self.settings, self.qa, self.store, paused=lambda: self.paused)
        self.calls = FakeCalls()
        self.chat = FakeChat()
        self.runner = QaRunner(
            self.guard,
            self.store,
            self.calls,
            self.chat,
            qa=self.qa,
            sleep=_no_sleep,
            shortlist_fn=fake_shortlist,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)
