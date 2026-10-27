"""Verifier: after every action, is the page in a sane state? (one job, no side effects)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.sites.errors import SiteBlocked, VerifyFailed

_BLOCK = re.compile(
    r"(?i)(verify (?:that )?you are (?:a )?human|captcha|access denied|unusual traffic|"
    r"are you a robot|temporarily blocked|403 forbidden|request blocked)"
)
_ERROR = re.compile(r"(?i)(something went wrong|internal server error|502 bad gateway|"
                    r"service unavailable|try again later)")


@dataclass(frozen=True)
class Expect:
    """What must be true after an action: these selectors present, and these absent."""

    present: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    timeout_ms: int = 3000


@dataclass
class Verifier:
    expectations: dict[str, Expect] = field(default_factory=dict)  # by the action's selector

    def check_text(self, page_text: str) -> None:
        """Block / error pages end the run cleanly (we never try to get around a bot check)."""
        if _BLOCK.search(page_text or ""):
            raise SiteBlocked("the site shows a bot check or block page")
        if _ERROR.search(page_text or ""):
            raise VerifyFailed("the site shows an error page")

    async def check_after(self, session: BrowserSession, selector: str) -> None:
        exp = self.expectations.get(selector)
        if exp is None:
            return
        for sel in exp.present:
            try:
                await session.wait_for(sel, exp.timeout_ms)
            except ElementNotFound:
                raise VerifyFailed("the page did not show the expected result") from None
        for sel in exp.absent:
            if await session.query_all(sel):
                raise VerifyFailed("the page still shows something that should be gone")
