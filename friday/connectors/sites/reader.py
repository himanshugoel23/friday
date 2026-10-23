"""Page reader: turns the page into scrubbed, injection-free text (one job, read-only)."""

from __future__ import annotations

from dataclasses import dataclass

from friday.connectors.browser.port import BrowserError, BrowserSession
from friday.connectors.scrub import scrub_text
from friday.connectors.sites.injection import strip_injection

BODY = "body"


@dataclass(frozen=True)
class PageSnapshot:
    text: str  # scrubbed, instruction sentences removed, truncated: safe for logs and prompts
    injections: list[str]  # instruction-like sentences found (ignored, reported)
    raw_for_checks: str  # for block / error detection only; never leaves the executor


class PageReader:
    def __init__(self, limit: int = 4000, selector: str = BODY) -> None:
        self._limit, self._selector = limit, selector

    async def read(self, session: BrowserSession) -> PageSnapshot:
        try:
            raw = await session.text(self._selector)
        except BrowserError:
            raw = ""
        clean, hits = strip_injection(raw[: self._limit * 3])
        return PageSnapshot(scrub_text(clean)[: self._limit], hits, raw[: self._limit])
