# ruff: noqa: E501
"""Store scoping: ONE named store ('from blinkit') is checked alone first, the ack line says so, and the single closing
question offers the others. Compare all only when no store is named or the user asks. Fakes only."""

from __future__ import annotations

from friday.planner.web import RawWebResult, WebItem, WebSource
from tests.shopping.helpers import BIGBASKET, INSTAMART, SiteFake
from tests.shopping.test_shopping import texts, world

BL = "https://blinkit.com/prn/"
BLINKIT = RawWebResult(
    summary="Blinkit.",
    items=[
        WebItem(title="Aashirvaad Shudh Chakki Atta 5 kg", price_text="Rs 244", price_inr=244, store="Blinkit", url=BL + "aashirvaad", pack_text="5 kg", delivery_time="9 mins"),
        WebItem(title="Rajdhani Chakki Atta 5 kg", price_text="Rs 219", price_inr=219, store="Blinkit", url=BL + "rajdhani", pack_text="5 kg", delivery_time="9 mins"),
    ],
    sources=[WebSource(url=BL + "aashirvaad"), WebSource(url=BL + "rajdhani")],
)
ALL = {"blinkit": BLINKIT, "bigbasket": BIGBASKET, "instamart": INSTAMART}


async def test_one_named_store_is_checked_alone_the_ack_says_so_and_the_closing_question_offers_the_rest(media_world):
    fake = SiteFake(ALL)
    w, _ = await world(media_world, fake)
    out = await w.say("Get aata price from blinkit")
    msgs = texts(out)
    assert fake.sites_called() == ["blinkit"]  # nobody else was asked
    assert "only Blinkit" in msgs[0] and "as you asked" in msgs[0]  # the ack line says so
    body = "\n".join(msgs)
    assert "Rs 244" in body and "Rs 219" in body and "Rs 260" not in body and "Rs 289" not in body  # only Blinkit prices
    last = out[-1]
    assert last.text.rstrip().endswith("Want me to compare with Zepto, Instamart and BigBasket too?")
    assert sum(m.text.count("?") for m in out if m.text) == 1  # ONE question in the whole reply
    assert [b.title for b in last.buttons] == ["Compare", "No thanks"]
    assert "Home or PG" not in body  # the place question waits until the user chooses to compare


async def test_yes_compares_everything_then_asks_the_place(media_world):
    fake = SiteFake(ALL)
    w, _ = await world(media_world, fake)
    await w.say("atta price on blinkit")
    out = await w.say("yes")
    assert sorted(set(fake.sites_called())) == ["bigbasket", "blinkit", "instamart", "zepto"]
    assert "Checking Zepto, Blinkit" in texts(out)[0] and "I would take" in "\n".join(texts(out))


async def test_no_stays_with_the_store(media_world):
    fake = SiteFake(ALL)
    w, _ = await world(media_world, fake)
    await w.say("atta price on blinkit")
    n = len(fake.calls)
    out = await w.say("no")
    assert len(fake.calls) == n and "stay with Blinkit" in "\n".join(texts(out))


async def test_no_store_named_compares_all_and_asking_to_compare_overrides(media_world):
    fake = SiteFake(ALL)
    w, _ = await world(media_world, fake)
    await w.say("atta")
    assert len(set(fake.sites_called())) == 4  # nothing named: everything, as before
    fake2 = SiteFake(ALL)
    w2, _ = await world(media_world, fake2)
    await w2.say("compare atta prices on blinkit")
    assert len(set(fake2.sites_called())) == 4  # the user asked to compare


async def test_a_failed_single_store_lookup_says_what_happened_in_plain_words_and_offers_the_rest(media_world):
    fake = SiteFake({"bigbasket": BIGBASKET})  # blinkit shows no prices
    w, _ = await world(media_world, fake, style_layer_enabled=True)
    out = await w.say("atta price from blinkit")
    body = "\n".join(texts(out))
    assert fake.sites_called() == ["blinkit"]
    assert "I could not read live prices on Blinkit." in body and "Want me to compare with Zepto, Instamart and BigBasket too?" in body
    for code in ("no_result", "not_visible", "unavailable", "lookup"):
        assert code not in body
    yes = "\n".join(texts(await w.say("yes")))
    assert "BigBasket" in yes
