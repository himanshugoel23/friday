"""StepRecorder: every browser step as {n, time, tool, action, url, note, screenshot}.

``RecordingSession`` wraps any BrowserSession, so connectors are unchanged. Notes are scrubbed.
Typed VALUES are never recorded (a fill step says which selector, not what was typed), and
screenshots paint over password / OTP / phone inputs first, so a code or number never lands in an
image. Screenshots are shown only behind the unguessable watch token (api/connectors_watch.py).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from friday.connectors.browser.port import BrowserSession
from friday.connectors.scrub import scrub_text

# Painted over in every screenshot (login fields: OTP, phone, passwords).
MASK_SELECTORS: tuple[str, ...] = (
    "input[type=password]",
    "input[type=tel]",
    "input[name*=otp i]",
    "input[autocomplete=one-time-code]",
    "[data-testid=otp-input]",
    "[data-testid=phone-input]",
)
MAX_STEPS = 200


@dataclass
class Step:
    n: int
    time: float
    tool: str
    action: str
    url: str
    note: str
    screenshot: bytes = field(default=b"", repr=False)

    def public(self) -> dict[str, Any]:
        return {"n": self.n, "time": self.time, "tool": self.tool, "action": self.action,
                "url": self.url, "note": self.note, "has_screenshot": bool(self.screenshot)}


class StepRecorder:
    def __init__(self, max_steps: int = MAX_STEPS) -> None:
        self.steps: list[Step] = []
        self.tool = ""  # set by TracedConnector for the tool call in progress
        self.result: dict[str, Any] | None = None
        self.done = False
        self._max = max_steps

    def add(self, action: str, url: str, note: str, screenshot: bytes = b"") -> None:
        if len(self.steps) >= self._max:
            return
        self.steps.append(Step(len(self.steps) + 1, time.time(), self.tool, action,
                               scrub_text(url), scrub_text(note)[:300], screenshot))

    def finish(self, result: dict[str, Any]) -> None:
        self.result, self.done = result, True

    def latest_screenshot(self) -> bytes:
        return next((s.screenshot for s in reversed(self.steps) if s.screenshot), b"")


class RecordingSession:
    """BrowserSession decorator: record a step (with a masked screenshot) after each action."""

    def __init__(self, inner: BrowserSession, recorder: StepRecorder) -> None:
        self._in, self.recorder = inner, recorder
        self._url = ""

    async def _snap(self, action: str, note: str) -> None:
        try:
            png = await self._in.screenshot(MASK_SELECTORS)
        except Exception:  # noqa: BLE001 - a failed screenshot must never break the run
            png = b""
        self.recorder.add(action, self._url, note, png)

    async def goto(self, url: str) -> None:
        self._url = url
        await self._in.goto(url)
        await self._snap("goto", "open page")

    async def fill(self, selector: str, value: str) -> None:
        await self._in.fill(selector, value)  # the value is deliberately not recorded
        await self._snap("fill", f"typed into {selector} (value hidden)")

    async def click(self, selector: str) -> None:
        await self._in.click(selector)
        await self._snap("click", f"clicked {selector}")

    async def text(self, selector: str) -> str:
        return await self._in.text(selector)

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]:
        return await self._in.query_all(selector, fields)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        await self._in.wait_for(selector, timeout_ms)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return await self._in.screenshot(tuple(mask_selectors) or MASK_SELECTORS)

    async def close(self) -> None:
        await self._in.close()


class TracedConnector:
    """Wraps a FoodConnector: tags steps with the tool name and logs tool start / outcome."""

    def __init__(self, inner: Any, recorder: StepRecorder) -> None:
        self._in, self._rec = inner, recorder

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._in, name)
        if name not in {"search_restaurants", "get_menu", "build_cart",
                        "get_payment_handoff", "track_order"}:
            return target

        async def call(*a: Any, **kw: Any) -> Any:
            self._rec.tool = name
            self._rec.add("tool", "", f"start {name}")
            try:
                out = await target(*a, **kw)
            except Exception as e:
                self._rec.add("tool", "", f"{name} failed: {type(e).__name__}")
                raise
            self._rec.add("tool", "", f"{name} ok")
            return out

        return call
