# ruff: noqa: E501
"""BrowserMcpGroceryProvider behind the GroceryProvider port, with the web provider as fallback; shopping flow unchanged."""

from __future__ import annotations

import pytest

from friday.shopping.agent import ShoppingAgent
from friday.shopping.compare import ShoppingInput
from friday.shopping.sites import GroceryResult, GrocerySearch, load_knowledge
from friday.sitemcp.provider import BrowserMcpGroceryProvider, FallbackGroceryProvider
from tests.shopping.helpers import BIGBASKET, INSTAMART, SiteFake
from tests.sitemcp.harness import make_world

DEFAULT = {"bigbasket": BIGBASKET, "instamart": INSTAMART}
REQ = GrocerySearch(category="atta", products=["atta", "milk"], query="atta", pincode="560034", user_id="u1")


@pytest.fixture
def w():
    world = make_world()
    yield world
    world.stop()


def provider(w, site="zepto"):
    kb = {**load_knowledge()[site]}
    return BrowserMcpGroceryProvider(w.hub, kb, allow_http=True)  # the local fake store is http


async def test_ok_path_maps_items_prices_and_sources(w):
    res = await provider(w).search(REQ)
    assert res.status == "ok" and res.site == "zepto"
    titles = {i.title for i in res.items}
    assert "Aashirvaad Whole Wheat Atta" in titles and "Amul Taaza Milk" in titles
    aash = next(i for i in res.items if i.title.startswith("Aashirvaad"))
    assert aash.price_inr == 289 and aash.pack_text == "5 kg" and aash.store == "Zepto" and aash.url.startswith("http://127.0.0.1")
    assert next(i for i in res.items if i.title.startswith("Pillsbury")).offer == "Out of stock"
    assert res.sources and len(w.stores["zepto"].hits) < 12  # polite: a handful of loads


async def test_no_place_means_not_visible_without_touching_the_site(w):
    res = await provider(w).search(REQ.model_copy(update={"pincode": None}))
    assert res.status == "not_visible" and res.note == "no_location" and w.stores["zepto"].hits == []


async def test_location_not_found_is_not_visible(w):
    res = await provider(w).search(REQ.model_copy(update={"pincode": "999999"}))
    assert res.status == "not_visible" and res.note == "location_not_found"


async def test_blocked_is_failed_and_the_fallback_answers_instead(w):
    w.stores["zepto"].mode = "challenge"
    primary = provider(w)
    assert (await primary.search(REQ)).status == "failed"

    class Web:
        site = "zepto"
        calls = 0

        async def search(self, req):
            Web.calls += 1
            return GroceryResult(site="zepto", status="ok", note="from web")

    res = await FallbackGroceryProvider(primary, Web()).search(REQ)
    assert res.note == "from web" and Web.calls == 1


async def test_fallback_not_used_when_browser_is_ok(w):
    class Web:
        site = "zepto"

        async def search(self, req):
            raise AssertionError("web search must not run when the browser worked")

    assert (await FallbackGroceryProvider(provider(w), Web()).search(REQ)).status == "ok"


async def test_primary_exception_falls_back():
    class Boom:
        site = "zepto"

        async def search(self, req):
            raise RuntimeError("x")

    class Web:
        site = "zepto"

        async def search(self, req):
            return GroceryResult(site="zepto", status="not_visible", note="price not visible")

    res = await FallbackGroceryProvider(Boom(), Web()).search(REQ)
    assert res.status == "not_visible" and "browser: browser:RuntimeError" in res.note


async def test_shopping_agent_uses_browser_for_zepto_and_web_for_the_rest(w):
    web = SiteFake(DEFAULT)
    shop = load_knowledge()
    from friday.shopping.sites import WebGroceryProvider

    zep = FallbackGroceryProvider(provider(w), WebGroceryProvider(shop["zepto"], web))
    agent = ShoppingAgent(web, overrides={"zepto": zep})
    out = await agent.run(ShoppingInput(query="atta", category_id="atta", lang="en", pincode="560034", user_id="u1"))
    assert out.status != "timeout" and any(o.store == "Zepto" and o.price_inr == 289 for p in out.products for o in p.offers)
    assert "zepto" not in web.sites_called()  # Zepto came from the browser server, not from web search
    assert "blinkit" in web.sites_called()


async def test_shopping_agent_falls_back_to_web_when_zepto_blocks(w):
    w.stores["zepto"].mode = "denied"
    web = SiteFake(DEFAULT)
    shop = load_knowledge()
    from friday.shopping.sites import WebGroceryProvider

    zep = FallbackGroceryProvider(provider(w), WebGroceryProvider(shop["zepto"], web))
    out = await ShoppingAgent(web, overrides={"zepto": zep}).run(ShoppingInput(query="atta", category_id="atta", lang="en", pincode="560034", user_id="u1"))
    assert "zepto" in web.sites_called() and out.status != "timeout"


def test_overrides_empty_while_the_switch_is_off():
    from types import SimpleNamespace

    from friday.sitemcp.wiring import shopping_overrides

    assert shopping_overrides(SimpleNamespace(site_mcp_enabled=False), object()) == {}
