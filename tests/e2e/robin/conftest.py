"""Fixtures for the Robin end-to-end suite: a fresh world per test (Robin ON, fakes)."""

from __future__ import annotations

import pytest

from tests.e2e.robin.harness import RobinWorld


@pytest.fixture
async def world():
    w = await RobinWorld.start()
    yield w
    await w.close()


@pytest.fixture
async def dworld():
    """The same, with the device API mounted (FRIDAY_ROBIN_DEVICE_ENABLED on)."""
    w = await RobinWorld.start(device=True)
    yield w
    await w.close()
