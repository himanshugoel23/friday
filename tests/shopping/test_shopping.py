# ruff: noqa: E501
"""Shopping assistant, fakes only: comparison + one pick + image cards + Home/PG, place memory, hidden prices,
no invented numbers, cited-only images, parallel site agents over A2A, MCP-style provider swap, switch off."""

from __future__ import annotations

import asyncio
import re

from friday.core.models import Place
from friday.planner import signals as sg
from friday.shopping import catalog, places
from friday.shopping.agent import ShoppingAgent
from friday.shopping.compare import ShoppingInput, parse_pack
from friday.shopping.images import FakeImages, og_image_from_html, public_https
from friday.shopping.sites import GroceryResult, GrocerySearch
from tests.shopping.helpers import ALLOWED_NUMBERS, BB, BIGBASKET, EMPTY, IM, INSTAMART, SiteFake

PAGES = {BB + "pillsbury": "https://cdn.bigbasket.com/pillsbury.jpg", BB + "fortune": "https://cdn.bigbasket.com/fortune.jpg"}


def texts(msgs) -> list[str]:  # noqa: ANN001
    return [m.text or "" for m in msgs]


async def world(media_world, fake, *, images=None, cards=True, shopping=True, **kw):  # noqa: ANN001, ANN201
    w = await media_world(approach_planner_enabled=True, shopping_assistant_enabled=shopping, **kw)

    async def lang(_user):  # noqa: ANN001, ANN202
        return "en"

    w.runtime.pipeline._reply_lang = lang
    gw = w.runtime.pipeline.planner
    if shopping:
        gw.shopping.agent = ShoppingAgent(fake, images=images or FakeImages(PAGES), now=w.runtime.pipeline.clock.now)
        gw.shopping._image_cards = cards
    return w, gw


DEFAULT = {"bigbasket": BIGBASKET, "instamart": INSTAMART}


async def test_atta_gives_progress_pick_cards_comparison_and_home_pg_buttons(media_world):
    fake = SiteFake(DEFAULT)
    w, _ = await world(media_world, fake)
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Home", address_text="Koramangala 560034"))
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="PG", address_text="HSR Layout 560102"))
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Office", address_text="Whitefield 560066"))
    out = await w.say("atta")
    body = "\n".join(texts(out))
    assert "Checking Zepto, Blinkit" in texts(out)[0] and "Instamart" in texts(out)[0]  # one progress line first
    assert "I would take Pillsbury Chakki Fresh Atta 5 kg" in body and "lowest price per kg (Rs 52/kg)" in body
    assert "Rs 52/kg" in body and "Rs 260" in body and "also" in body  # per-kg figures and the other seller's price
    assert "Prices as of" in body and "may differ in the app" in body
    assert "Could not read: Zepto, Blinkit" in body  # honest about what it could not read
    cards = [m for m in out if m.media_url]
    assert cards and all(m.media_url.startswith("https://cdn.bigbasket.com/") for m in cards)
    assert "Pillsbury" in (cards[0].text or "")
    last = out[-1]
    assert [b.title for b in last.buttons] == ["Home", "PG"]  # Office only when asked
    assert "pincode" not in last.text.lower()  # a saved place exists: no pincode question
    assert sum(t.count("?") for t in [last.text]) == 1  # one question in the message


async def test_office_button_only_when_asked(media_world):
    w, _ = await world(media_world, SiteFake(DEFAULT))
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Home", address_text="Koramangala 560034"))
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Office", address_text="Whitefield 560066"))
    out = await w.say("atta for my office")
    assert [b.title for b in out[-1].buttons] == ["Home", "Office"]


async def test_tapping_home_reads_the_pincode_from_the_saved_address_and_refines(media_world):
    fake = SiteFake(DEFAULT)
    w, _ = await world(media_world, fake)
    await w.c.repos.places.upsert(Place(owner_user_id=w.user.id, label="Home", address_text="Koramangala 560034"))
    await w.say("atta")
    n = len(fake.calls)
    out = await w.tap("Home")
    body = "\n".join(texts(out))
    assert len(fake.calls) > n and all("560034" in q for q in fake.calls[n:])
    assert "Same pick for home" in body and "Pillsbury" in body
    assert "560034" not in w.brain.seen and not w.brain.seen  # never fell through to the brain


async def test_no_saved_place_asks_one_question_then_saves_the_answer(media_world):
    fake = SiteFake(DEFAULT)
    w, _ = await world(media_world, fake)
    out = await w.say("atta")
    q = out[-1]
    assert "Ghar ya PG? Share the area or pincode once and I will remember it." in q.text and not q.buttons
    assert q.text.count("?") == 1
    out2 = await w.say("PG, Koramangala 560034")
    body = "\n".join(texts(out2))
    assert "Saved your PG" in body and "560034" in body and "Pillsbury" in body
    saved = await w.c.repos.places.list_for_owner(w.user.id)
    assert [p.label for p in saved] == ["PG"] and "560034" in (saved[0].address_text or "")
    assert not w.brain.seen
    # next time the saved PG is offered as a button and no pincode is asked
    out3 = await w.say("rice")
    assert [b.title for b in out3[-1].buttons] == ["PG"] and "pincode" not in out3[-1].text.lower()


async def test_quick_commerce_hidden_price_falls_back_to_other_sellers_and_says_so(media_world):
    w, _ = await world(media_world, SiteFake(DEFAULT))
    out = await w.say("aashirvaad atta price on zepto")
    body = "\n".join(texts(out))
    assert "Zepto does not show its own prices online, so these are other sellers' prices." in body
    assert "Rs 289" in body or "Rs 295" in body
    assert not sg.mentions_call(body)


async def test_no_invented_numbers_and_every_source_is_cited(media_world):
    w, _ = await world(media_world, SiteFake(DEFAULT))
    out = await w.say("atta")
    body = "\n".join(texts(out))
    body = re.sub(r"https?://\S+", "", body)
    body = re.sub(r"\d{1,2} \w{3} \d{2}:\d{2} IST", "", body)  # the as-of stamp
    nums = {float(n) for n in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", body)}
    assert nums <= {float(n) for n in ALLOWED_NUMBERS} | {1.0, 2.0, 3.0, 4.0, 4.1, 4.5, 560.0}, nums
    urls = set(re.findall(r"https?://\S+", "\n".join(texts(out))))
    assert urls <= {BB + "aashirvaad", BB + "pillsbury", BB + "fortune", IM + "aashirvaad"} | set(PAGES.values())


async def test_uncited_prices_and_uncited_images_are_dropped(media_world):
    from friday.planner.web import RawWebResult, WebItem, WebSource

    rogue = RawWebResult(
        summary="x",
        items=[
            WebItem(title="Aashirvaad Atta 5 kg", price_text="Rs 999", price_inr=999, store="BigBasket", url=None, pack_text="5 kg"),  # page not cited
            WebItem(title="Pillsbury Atta 5 kg", price_text="Rs 250", price_inr=250, store="BigBasket", url=BB + "p", pack_text="5 kg", image_url="https://evil.example/x.jpg"),
        ],
        sources=[WebSource(url=BB + "p")],
    )
    images = FakeImages({BB + "notcited": "https://cdn.example/n.jpg"})
    w, _ = await world(media_world, SiteFake({"bigbasket": rogue}), images=images)
    out = await w.say("atta")
    body = "\n".join(texts(out))
    assert "999" not in body and "Rs 250" in body
    assert not [m for m in out if m.media_url]  # evil.example was never cited; the page has no og:image in the fake
    assert images.calls == [BB + "p"]  # only a cited product page was ever asked for an image


async def test_simulator_and_whatsapp_get_text_only_no_image_messages(media_world):
    w, _ = await world(media_world, SiteFake(DEFAULT), cards=None)  # detect: the simulator is not the web chat
    out = await w.say("atta")
    assert not [m for m in out if m.media_url] and "Pillsbury" in "\n".join(texts(out))


async def test_nothing_readable_is_a_soft_fail_with_popular_names_and_no_demand(media_world):
    w, _ = await world(media_world, SiteFake({}))
    out = await w.say("atta")
    body = "\n".join(texts(out))
    assert "Aashirvaad" in body and "Pillsbury" in body and "try again" in body
    assert "pincode" not in body.lower() and "exact product" not in body.lower() and not sg.mentions_call(body.replace("try again", ""))


async def test_all_sites_failing_says_unavailable(media_world):
    w, _ = await world(media_world, SiteFake({s: RuntimeError("x") for s in ("zepto", "blinkit", "instamart", "bigbasket", "amazon", "jiomart")}))
    out = await w.say("atta")
    assert "can't look up prices right now" in "\n".join(texts(out))


async def test_sites_are_asked_in_parallel_over_a2a_and_extras_only_when_needed(media_world):
    fake = SiteFake(DEFAULT, barrier=4)  # all four core sites must be inside search() at the same moment
    w, _ = await world(media_world, fake)
    await w.say("atta")
    assert sorted(fake.sites_called()) == ["bigbasket", "blinkit", "instamart", "zepto"]  # 2 core sites readable: no extras
    fake2 = SiteFake({"amazon": BIGBASKET.model_copy(update={"items": [i.model_copy(update={"url": "https://www.amazon.in/dp/" + str(n), "store": "Amazon"}) for n, i in enumerate(BIGBASKET.items)], "sources": [type(s)(url="https://www.amazon.in/dp/" + str(n)) for n, s in enumerate(BIGBASKET.sources)]})})
    w2, _ = await world(media_world, fake2)
    out = await w2.say("atta")
    assert "amazon" in fake2.sites_called() and "Amazon" in "\n".join(texts(out))  # second wave when fewer than 2 core sites show prices


async def test_an_official_mcp_provider_replaces_the_zepto_web_agent_without_changing_the_pm():
    class ZeptoMcp:
        site = "zepto"

        async def search(self, req: GrocerySearch) -> GroceryResult:
            from friday.planner.web import WebItem, WebSource

            u = "https://www.zepto.com/pn/atta"
            return GroceryResult(site="zepto", status="ok", items=[WebItem(title="Aashirvaad Select Atta 5 kg", price_inr=279, price_text="Rs 279", url=u, pack_text="5 kg", store="Zepto", delivery_time="9 mins")], sources=[WebSource(url=u)])

    agent = ShoppingAgent(SiteFake(DEFAULT), overrides={"zepto": ZeptoMcp()}, images=FakeImages())
    out = await agent.run(ShoppingInput(query="atta", category_id="atta", lang="en"))
    aash = next(p for p in out.products if p.title.startswith("Aashirvaad"))
    assert aash.store == "Zepto" and aash.price_inr == 279 and aash.delivery_time == "9 mins"
    assert {o.store for o in aash.offers} == {"Zepto", "BigBasket", "Swiggy Instamart"}


async def test_switch_off_keeps_the_old_behaviour(media_world):
    w, gw = await world(media_world, SiteFake(DEFAULT), shopping=False)
    assert gw.shopping is None
    from friday.planner.web import FakeWebSearch

    gw.web.provider = FakeWebSearch()
    out = await w.say("atta")
    assert not any("Checking Zepto" in t for t in texts(out))
    w2 = await media_world()
    assert w2.runtime.pipeline.planner is None


# ------------------------------------------------------------------ pure units
def test_pack_and_catalog_and_places_units():
    assert parse_pack("Aashirvaad 5 kg")[0] == 5 and parse_pack("2 x 500 g")[0] == 1.0 and parse_pack("750 ml")[0] == 0.75
    assert parse_pack("no size")[0] is None
    assert catalog.is_shopping_request("atta") and catalog.is_shopping_request("aashirvaad atta rate on zepto")
    assert catalog.is_shopping_request("how to make atta dough") is None  # a knowledge question
    assert catalog.is_shopping_request("find me a plumber") is None
    assert catalog.is_shopping_request("call the shop and ask atta price") is None
    p = places.parse_answer("PG, Koramangala 560034")
    assert p and p.kind == "pg" and p.pincode == "560034" and p.area == "Koramangala"
    assert places.parse_answer("ghar 110001").kind == "home" and places.parse_answer("???") is None
    assert og_image_from_html('<meta property="og:image" content="/i/a.jpg">', "https://www.bigbasket.com/x") == "https://www.bigbasket.com/i/a.jpg"
    assert not public_https("http://x.com/a.jpg") and not public_https("https://127.0.0.1/a.jpg") and public_https("https://cdn.x.com/a.jpg")


async def test_timeout_is_clean(media_world):
    async def slow():  # noqa: ANN202
        await asyncio.sleep(5)

    class Slow:
        async def search(self, query, *, timeout_s, hint=None):  # noqa: ANN001, ANN202
            await asyncio.sleep(5)
            return EMPTY

    agent = ShoppingAgent(Slow(), timeout_s=0.3, images=FakeImages())
    out = await agent.run(ShoppingInput(query="atta", category_id="atta", lang="en"))
    assert out.status in ("timeout", "unavailable", "no_result")
