# ruff: noqa: E501
"""Tool flows over the fake stores: location, search, product, cart, checkout preview, login, logout."""

from __future__ import annotations

import pytest

from friday.sitemcp.tools import TOOL_NAMES
from tests.sitemcp.harness import SITES, make_world


@pytest.fixture
def w():
    world = make_world()
    yield world
    world.stop()


async def call(w, site, tool, args=None, user="u1"):
    return await w.hub.call(site, tool, args or {}, user_id=user)


@pytest.mark.parametrize("site", list(SITES))
async def test_full_anonymous_flow_stops_before_payment(w, site):
    r = await call(w, site, "set_location", {"pincode": "560034"})
    assert r["status"] == "ok" and "Koramangala" in r["location_label"]
    r = await call(w, site, "search_products", {"query": "atta"})
    assert r["status"] == "ok" and len(r["items"]) == 3
    first = r["items"][0]
    assert first["price_inr"] == 289.0 and first["pack"] == "5 kg" and first["id"].startswith("/p/")
    assert any(i["out_of_stock"] for i in r["items"])
    p = await call(w, site, "get_product", {"id": first["id"]})
    assert p["status"] == "ok" and p["title"].startswith("Aashirvaad") and p["price_inr"] == 289.0
    a = await call(w, site, "add_to_cart", {"id": first["id"], "qty": 2})
    assert a["status"] == "ok" and a["staged"]
    c = await call(w, site, "view_cart")
    assert c["items"][0]["qty"] == "2" and c["items"][0]["price_inr"] == 578.0
    # not logged in: proceed lands on the login wall, nothing is paid
    pv = await call(w, site, "checkout_preview")
    assert pv["status"] == "needs_login"
    assert w.stores[site].payments == 0 and "/pay" not in w.stores[site].hits


@pytest.mark.parametrize("site", list(SITES))
async def test_checkout_preview_logged_in_reports_bill_and_payment_step(w, site):
    await call(w, site, "set_location", {"pincode": "560034"})
    pid = (await call(w, site, "search_products", {"query": "milk"}))["items"][0]["id"]
    await call(w, site, "add_to_cart", {"id": pid})
    r = await call(w, site, "login_start", {"phone": "9000000001"})
    assert r["status"] == "otp_required" and r["secure_page"].startswith("https://friday.test/connectors/otp/")
    assert w.started and w.started[-1][:2] == ("u1", site)
    assert (await call(w, site, "login_status"))["pending"] is True
    w.otp.submit(w.started[-1][2], "246810")
    assert (await call(w, site, "login_status"))["status"] == "logged_in"
    pv = await call(w, site, "checkout_preview")
    assert pv["status"] == "ok" and pv["payment_step_reached"] == "payment_options"
    assert pv["total_inr"] == 86.0 and {f["label"] for f in pv["fees"]} >= {"Delivery fee", "Handling fee"}
    assert pv["stopped_before_payment"] is True
    assert w.stores[site].payments == 0 and "/pay" not in w.stores[site].hits


async def test_unverified_proceed_is_never_clicked():
    w = make_world(proceed_verified=False)
    try:
        await call(w, "zepto", "set_location", {"pincode": "560034"})
        pid = (await call(w, "zepto", "search_products", {"query": "milk"}))["items"][0]["id"]
        await call(w, "zepto", "add_to_cart", {"id": pid})
        pv = await call(w, "zepto", "checkout_preview")
        assert pv["proceed_clicked"] is False and pv["payment_step_reached"] == "cart_summary"
        assert "/checkout" not in w.stores["zepto"].hits and pv["total_inr"] == 86.0
    finally:
        w.stop()


async def test_location_not_found_and_needs_location(w):
    assert (await call(w, "zepto", "search_products", {"query": "atta"}))["status"] == "needs_location"
    r = await call(w, "zepto", "set_location", {"pincode": "999999"})
    assert r["status"] == "location_not_found"
    assert (await call(w, "zepto", "search_products", {"query": "atta"}))["status"] == "needs_location"
    assert (await call(w, "zepto", "set_location", {"pincode": "560034", "place": "x"}))["status"] == "error"


async def test_no_results_and_bad_product_id(w):
    await call(w, "blinkit", "set_location", {"place": "Koramangala"})
    assert (await call(w, "blinkit", "search_products", {"query": "zzzz"}))["note"] == "no_results"
    assert (await call(w, "blinkit", "get_product", {"id": "http://evil.test/x"}))["status"] == "error"
    assert (await call(w, "blinkit", "get_product", {"id": "//evil.test/x"}))["status"] == "error"
    assert (await call(w, "blinkit", "get_product", {"id": "/p/nope"}))["status"] == "not_found"


async def test_out_of_stock_cannot_be_added(w):
    await call(w, "zepto", "set_location", {"pincode": "560034"})
    r = await call(w, "zepto", "add_to_cart", {"id": "/p/pillsbury-atta-10kg"})
    assert r == {"status": "unavailable", "reason": "out_of_stock"}


async def test_logout_erases_stored_session_and_cookie_state(w):
    await call(w, "zepto", "login_start", {"phone": "9000000001"})
    w.otp.submit(w.started[-1][2], "246810")
    assert (await call(w, "zepto", "login_status"))["status"] == "logged_in"
    assert w.vault.has("u1", "zepto")
    assert (await call(w, "zepto", "logout"))["status"] == "logged_out"
    assert not w.vault.has("u1", "zepto") and w.factory.live() == 0


async def test_wrong_otp_asks_to_start_again(w):
    await call(w, "zepto", "login_start", {"phone": "9000000001"})
    w.otp.submit(w.started[-1][2], "111111")
    r = await call(w, "zepto", "login_status")
    assert r["status"] == "needs_login" and r["reason"] == "wrong_code"


async def test_bad_arguments_are_protocol_errors_not_site_hits(w):
    r = await w.hub.call("zepto", "search_products", {}, user_id="u1")
    assert r["status"] == "error"
    r = await w.hub.call("zepto", "set_location", {"pincode": "12"}, user_id="u1")
    assert r["status"] == "error"
    assert w.stores["zepto"].hits == []


def test_tool_names_are_the_nine():
    assert TOOL_NAMES == ("set_location", "search_products", "get_product", "add_to_cart", "view_cart", "checkout_preview",
                          "login_start", "login_status", "logout")
