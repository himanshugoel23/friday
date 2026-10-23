"""In-memory ``LiveBrowserSession`` for tests of the runtime (no Chromium needed).

Cookies live in a jar that round-trips through ``storage_state``; ``goto`` enforces the network
policy like the real route guard; input events are recorded so tests can see takeover traffic.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any

from friday.connectors.browser.policy import LimitCounter, NetworkPolicy
from friday.connectors.browser.port import ElementNotFound, NetworkBlocked

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg=="
)


class FakeLiveSession:
    def __init__(self, storage_state: dict | None, policy: NetworkPolicy | None,
                 counter: LimitCounter | None, pages: Mapping[str, str] | None = None) -> None:
        self.cookies: list[dict[str, Any]] = list((storage_state or {}).get("cookies", []))
        self.policy, self.counter = policy, counter
        self.pages = dict(pages or {})
        self.url = "about:blank"
        self.closed = False
        self.steps: list[tuple[str, str]] = []
        self.inputs: list[tuple[str, Any]] = []
        self.screenshot_masks: list[tuple[str, ...]] = []

    def set_cookie(self, name: str, value: str, domain: str = "fake.test") -> None:
        self.cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})

    async def goto(self, url: str) -> None:
        reason = self.policy.check(url) if self.policy else None
        if reason:
            if self.counter:
                self.counter.blocked(url, reason)
            raise NetworkBlocked(reason)
        self.url = url
        self.steps.append(("goto", url))

    async def fill(self, selector: str, value: str) -> None:
        self.steps.append(("fill", selector))

    async def click(self, selector: str) -> None:
        self.steps.append(("click", selector))

    async def text(self, selector: str) -> str:
        if selector not in self.pages:
            raise ElementNotFound(f"selector not found: {selector}")
        return self.pages[selector]

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None):
        return []

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        return None

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        self.screenshot_masks.append(tuple(mask_selectors))
        return PNG_1PX

    async def storage_state(self) -> dict:
        return {"cookies": list(self.cookies), "origins": []}

    def viewport(self) -> tuple[int, int]:
        return (1280, 800)

    def current_url(self) -> str:
        return self.url

    async def pointer_click(self, x: int, y: int) -> None:
        self.inputs.append(("click", (x, y)))

    async def type_text(self, text: str) -> None:
        self.inputs.append(("type", len(text)))  # content is not even kept here

    async def press_key(self, key: str) -> None:
        self.inputs.append(("key", key))

    async def scroll(self, dy: int) -> None:
        self.inputs.append(("scroll", dy))

    async def close(self) -> None:
        self.closed = True
