"""`friday loadtest` smoke: a tiny run must pass with zero lost/duplicate items."""

from __future__ import annotations

import asyncio

from friday.cli import _loadtest


async def test_loadtest_smoke_has_zero_lost_or_duplicate_items():
    r = await asyncio.wait_for(_loadtest(2, 2, 0.5, 60.0, ["api", "task", "voice"]), 90)
    assert r["pass"], r
    assert r["tasks"] == 2 and r["lost_tasks"] == r["duplicate_tasks"] == 0
    assert r["duplicate_calls"] == r["duplicate_messages"] == r["lost_calls"] == 0
