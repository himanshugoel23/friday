# ruff: noqa: E501
"""Fakes for the shopping tests: a web provider that answers per site, scripted pages, no network."""

from __future__ import annotations

import asyncio

from friday.planner.web import RawWebResult, WebItem, WebSource

BB = "https://www.bigbasket.com/pd/"
IM = "https://www.swiggy.com/instamart/item/"


def page(url: str, title: str = "") -> WebSource:
    return WebSource(url=url, title=title)


BIGBASKET = RawWebResult(
    summary="BigBasket listings.",
    items=[
        WebItem(title="Aashirvaad Select Whole Wheat Atta 5 kg", price_text="Rs 295", price_inr=295, store="BigBasket", url=BB + "aashirvaad", pack_text="5 kg", rating="4.2", ingredients="100% whole wheat atta", delivery_time="Tomorrow"),
        WebItem(title="Pillsbury Chakki Fresh Atta 5 kg", price_text="Rs 260", price_inr=260, store="BigBasket", url=BB + "pillsbury", pack_text="5 kg", rating="4.1", rating_count=900, ingredients="100% whole wheat"),
        WebItem(title="Fortune Chakki Fresh Atta 5 kg", price_text="Rs 275", price_inr=275, store="BigBasket", url=BB + "fortune", pack_text="5 kg", rating="4.0", ingredients="Whole wheat"),
    ],
    sources=[page(BB + "aashirvaad"), page(BB + "pillsbury"), page(BB + "fortune")],
)
INSTAMART = RawWebResult(
    summary="Instamart.",
    items=[WebItem(title="Aashirvaad Select Whole Wheat Atta 5 kg", price_text="Rs 289", price_inr=289, store="Instamart", url=IM + "aashirvaad", pack_text="5 kg", delivery_time="12 mins")],
    sources=[page(IM + "aashirvaad")],
)
EMPTY = RawWebResult(summary="No prices shown on these pages.")
ALLOWED_NUMBERS = {100, 900, 4.1, 4.2, 295, 260, 275, 289, 5, 4, 3, 12, 2, 1, 52, 55, 57.8, 58, 53}


class SiteFake:
    """search(query) -> the page set of the site named last in the query. Records calls and concurrency."""

    def __init__(self, by_site: dict[str, RawWebResult | Exception], *, barrier: int = 0) -> None:
        self.by_site, self.calls, self.barrier = by_site, [], barrier
        self._arrived = 0
        self._all = asyncio.Event()

    async def search(self, query: str, *, timeout_s: float, hint: str | None = None) -> RawWebResult:  # noqa: ARG002
        self.calls.append(query)
        if self.barrier:  # every site in the first wave must be running at the same moment
            self._arrived += 1
            if self._arrived >= self.barrier:
                self._all.set()
            await asyncio.wait_for(self._all.wait(), 3)
        site = query.rsplit(" ", 1)[-1]
        item = self.by_site.get(site, EMPTY)
        if isinstance(item, Exception):
            raise item
        return item

    def sites_called(self) -> list[str]:
        return [q.rsplit(" ", 1)[-1] for q in self.calls]
