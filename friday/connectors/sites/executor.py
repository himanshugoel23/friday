"""Action executor: a ``BrowserSession`` wrapper that every connector talks to.

Per call it runs, in order: safety (domain, secrets, payment wording, approvals) -> the action with
selector alternates -> up to 3 logged LLM repairs on click / fill / text -> page reader (injection,
block pages) -> verifier. It is itself a ``BrowserSession``, so connectors do not change. The action
log holds selector KEYS only: typed values and page text are never recorded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.sites.locator import ElementLocator, RepairLog
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import SiteSafety
from friday.connectors.sites.verifier import Verifier


@dataclass
class ActionRecord:
    n: int
    action: str  # goto / fill / click / text / wait / query
    key: str  # selector key (or "-")
    ok: bool
    note: str = ""  # "alternate", "repaired", reason; never values


@dataclass
class GuardedSession:
    inner: BrowserSession
    safety: SiteSafety
    locator: ElementLocator
    reader: PageReader = field(default_factory=PageReader)
    verifier: Verifier = field(default_factory=Verifier)
    log: list[ActionRecord] = field(default_factory=list)

    def _rec(self, action: str, key: str | None, ok: bool, note: str = "") -> None:
        self.log.append(ActionRecord(len(self.log) + 1, action, key or "-", ok, note))

    async def _after(self, selector: str = "") -> None:
        snap = await self.reader.read(self.inner)
        self.safety.note_injection(snap.injections)
        self.verifier.check_text(snap.raw_for_checks)
        if selector:
            await self.verifier.check_after(self.inner, selector)

    # ---- BrowserSession
    async def goto(self, url: str) -> None:
        self.safety.check_goto(url)
        await self.inner.goto(url)
        self._rec("goto", None, True)
        await self._after()

    async def _try(self, op: str, selector: str, value: str | None, *, repairable: bool) -> object:
        key, _ = self.locator.key_for(selector)
        cands = self.locator.candidates(selector)
        last: ElementNotFound | None = None
        for i, cand in enumerate(cands):
            try:
                res = await self._call(op, cand, value)
            except ElementNotFound as e:
                last = e
                continue
            self._rec(op, key, True, "" if i == 0 else "alternate")
            return res
        if repairable:
            outline = await self._outline()
            new = await self.locator.repair(selector, outline)
            if new:
                try:
                    res = await self._call(op, new, value)
                except ElementNotFound as e:
                    last = e
                else:
                    self._rec(op, key, True, "repaired (unconfirmed)")
                    return res
        self._rec(op, key, False, "not found")
        raise last or ElementNotFound(f"selector '{key}' not found")

    async def _call(self, op: str, selector: str, value: str | None) -> object:
        if op == "click":
            return await self.inner.click(selector)
        if op == "fill":
            assert value is not None
            return await self.inner.fill(selector, value)
        if op == "text":
            return await self.inner.text(selector)
        return await self.inner.wait_for(selector, int(value or 5000))

    async def _outline(self) -> str:
        fn = getattr(self.inner, "outline", None)  # optional port extension (Developer A)
        if fn is not None:
            return str(await fn(4000))
        return (await self.reader.read(self.inner)).text

    async def fill(self, selector: str, value: str) -> None:
        key, _ = self.locator.key_for(selector)
        self.safety.check_fill(key, value)
        await self._try("fill", selector, value, repairable=True)

    async def click(self, selector: str) -> None:
        key, _ = self.locator.key_for(selector)
        self.safety.check_click(key, selector)
        await self._try("click", selector, None, repairable=True)
        await self._after(selector)

    async def text(self, selector: str) -> str:
        return str(await self._try("text", selector, None, repairable=True))

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        await self._try("wait", selector, str(timeout_ms), repairable=False)

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]:
        for i, cand in enumerate(self.locator.candidates(selector)):
            rows = await self.inner.query_all(cand, fields)
            if rows:
                if i:
                    self._rec("query", self.locator.key_for(selector)[0], True, "alternate")
                return rows
        return []

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return await self.inner.screenshot(mask_selectors)

    async def close(self) -> None:
        await self.inner.close()


@dataclass
class AgentKit:
    """The guarded session plus the pieces the flow reads afterwards."""

    session: GuardedSession
    safety: SiteSafety
    locator: ElementLocator
    repairs: RepairLog
