"""A consumer-beta world (simulated WhatsApp, fakes only) with the voice/Devanagari switches
settable per test. Reuses ``tests/integration/conftest.make_world`` and closes what it opened."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

import tests.integration.conftest as ic

Factory = Callable[..., Awaitable[ic.World]]


@pytest.fixture
async def media_world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Factory]:
    made: list[ic.World] = []
    orig = ic.settings_with

    async def factory(**extra: object) -> ic.World:
        def with_extra(google_extra: dict | None = None, **sw: bool):  # noqa: ANN202
            return orig(google_extra, **sw, **extra)

        monkeypatch.setattr(ic, "settings_with", with_extra)
        w = await ic.make_world(calls=True, savings=True, lifestate=True)
        made.append(w)
        return w

    try:
        yield factory
    finally:
        for w in made:
            await ic.close_world(w)


@pytest.fixture(autouse=True)
def _quiet_router(caplog: pytest.LogCaptureFixture):  # noqa: ANN202
    caplog.set_level(logging.DEBUG, logger="friday")
    yield
    assert "consumer router failed" not in caplog.text
    assert "outbound hook failed" not in caplog.text
