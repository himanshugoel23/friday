# ruff: noqa: E501
"""WEB_LOOKUP agent. One job: turn a lookup request into sourced, time-stamped results.

Never hangs: a hard overall deadline (default 25 s) covers the single allowed retry. Results
(status ok only) are cached for a few minutes. Every result carries sources (URLs the provider
cited) and an 'as of' time; a price taken from a web page gets a caveat, and quick-commerce prices
ask for a pincode when none is known.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from friday.core.logging import get_logger
from friday.planner import signals as sg
from friday.planner import wording
from friday.planner.web import RawWebResult, WebItem, WebSearchPort, WebSource

log = get_logger(__name__)
_IST = timezone(timedelta(hours=5, minutes=30))


class WebLookupInput(BaseModel):
    query: str
    retailer: str | None = None
    pincode: str | None = None
    lang: str = "hinglish"


class WebLookupOutput(BaseModel):
    status: Literal["ok", "no_result", "timeout", "unavailable"]
    summary: str = ""
    items: list[WebItem] = Field(default_factory=list)
    sources: list[WebSource] = Field(default_factory=list)
    as_of: datetime
    caveat: str | None = None
    ask_pincode: bool = False
    from_cache: bool = False
    retailer: str | None = None


class WebLookupAgent:
    def __init__(
        self,
        provider: WebSearchPort,
        *,
        timeout_s: float = 25.0,
        cache_ttl_s: float = 300.0,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        min_retry_budget_s: float = 8.0,
    ) -> None:
        self.provider, self.timeout_s, self.cache_ttl_s = provider, timeout_s, cache_ttl_s
        self._now = now or (lambda: datetime.now(UTC))
        self._mono = monotonic
        self.min_retry_budget_s = min_retry_budget_s
        self._cache: dict[tuple[str, str, str], tuple[float, WebLookupOutput]] = {}

    @staticmethod
    def _key(inp: WebLookupInput) -> tuple[str, str, str]:
        return (" ".join(inp.query.lower().split()), (inp.retailer or "").lower(), inp.pincode or "")

    async def run(self, inp: WebLookupInput) -> WebLookupOutput:
        key = self._key(inp)
        hit = self._cache.get(key)
        if hit and self._mono() - hit[0] < self.cache_ttl_s:
            return hit[1].model_copy(update={"from_cache": True})
        started = self._mono()
        raw: RawWebResult | None = None
        status: Literal["ok", "no_result", "timeout", "unavailable"] = "timeout"
        for attempt in (1, 2):  # a single retry at most, inside the one overall deadline
            remaining = self.timeout_s - (self._mono() - started)
            if remaining <= 0 or (attempt == 2 and remaining < self.min_retry_budget_s):
                break
            try:
                raw = await asyncio.wait_for(self.provider.search(inp.query, timeout_s=remaining), remaining)
                status = "ok"
                break
            except TimeoutError:
                status = "timeout"
            except Exception as e:  # noqa: BLE001 - provider errors: unavailable
                log.info("web lookup: provider error %s (attempt %d)", type(e).__name__, attempt)
                status = "unavailable"
                if getattr(self.provider, "permanent_failure", False):
                    break
        out = self._build(inp, raw, status)
        if out.status == "ok":
            self._cache[key] = (self._mono(), out)
            if len(self._cache) > 200:
                self._cache.pop(next(iter(self._cache)))
        return out

    def _build(self, inp: WebLookupInput, raw: RawWebResult | None, status: str) -> WebLookupOutput:
        now = self._now()
        if raw is None:
            return WebLookupOutput(status=status, as_of=now, retailer=inp.retailer)  # type: ignore[arg-type]
        # no cited source, no answer: never present an unsourced price
        if not raw.sources or not (raw.summary or raw.items):
            return WebLookupOutput(status="no_result", as_of=now, retailer=inp.retailer)
        quick = sg.is_quick_commerce(inp.retailer)
        has_price = any(i.price_text or i.price_inr for i in raw.items) or sg.PRICE_RE.search(inp.query) is not None
        caveat = None
        if has_price:
            key = "caveat_quick" if quick else "caveat_web"
            caveat = wording.line(key, inp.lang, store=(inp.retailer or "").title())
        return WebLookupOutput(
            status="ok", summary=raw.summary, items=raw.items, sources=raw.sources, as_of=now, caveat=caveat,
            ask_pincode=bool(quick and not inp.pincode and has_price), retailer=inp.retailer,
        )  # fmt: skip

    # ------------------------------------------------------------------ chat text
    def render(self, out: WebLookupOutput, lang: str = "hinglish") -> str:
        where = wording.where_label(out.retailer, lang if lang == "en" else "hinglish")
        if out.status == "timeout":
            return wording.line("web_timeout", lang, where=where)
        if out.status == "unavailable":
            return wording.line("web_unavailable", lang, where=where)
        if out.status == "no_result":
            return wording.line("web_none", lang)
        lines = [out.summary] if out.summary else []
        for it in out.items[:3]:
            price = it.price_text or (f"Rs {it.price_inr:g}" if it.price_inr is not None else "")
            store = f" ({it.store})" if it.store else ""
            lines.append(f"- {it.title}{store}: {price}".rstrip(": "))
        stamp = out.as_of.astimezone(_IST).strftime("%d %b %H:%M")
        lines.append(wording.line("web_as_of", lang, time=stamp))
        if out.caveat:
            lines.append(out.caveat)
        if out.ask_pincode:
            lines.append(wording.line("ask_pincode", lang))
        urls = " ".join(s.url for s in out.sources[:3])
        lines.append(f"{wording.line('web_sources', lang)} {urls}")
        return "\n".join(lines)

