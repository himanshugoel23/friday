"""BrowserSession: the only browser surface connectors may touch (no Playwright imports there).

Selectors are CSS strings. ``query_all`` reads many rows at once: ``fields`` maps a name to a CSS
sub-selector inside each row; a trailing ``@attr`` reads that attribute instead of the text, and
a bare ``@attr`` reads the row's own attribute. Every row also gets ``"text"``. Page text is
UNTRUSTED input: connectors parse and validate it, they never pass it on as instructions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class BrowserError(Exception):
    """Base for browser failures. Messages carry the selector, never page content."""


class ElementNotFound(BrowserError):
    """A selector matched nothing (or did not appear in time)."""


class BrowserSession(Protocol):
    async def goto(self, url: str) -> None: ...

    async def fill(self, selector: str, value: str) -> None: ...

    async def click(self, selector: str) -> None: ...

    async def text(self, selector: str) -> str: ...

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]: ...

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None: ...

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        """PNG of the page; elements matching ``mask_selectors`` are painted over."""
        ...

    async def close(self) -> None: ...
