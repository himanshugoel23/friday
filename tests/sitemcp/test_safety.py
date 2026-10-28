# ruff: noqa: E501
"""Honest boundaries, enforced: blocked handling, robots, pacing, isolation, memory guard, caps, no payment surface."""

from __future__ import annotations

import pytest

from friday.sitemcp.guard import PaymentBlocked, SafeSession
from friday.sitemcp.knowledge import load_knowledge, smells_like_payment_selector, validate
from friday.sitemcp.tools import TOOL_NAMES, assert_no_payment_tools
from tests.sitemcp.harness import SITES, make_world


@pytest.fixture
def w():
    world = make_world()
    yield world
    world.stop()


async def call(w, site, tool, args=None, user="u1"):
    return await w.hub.call(site, tool, args or {}, user_id=user)


# ------------------------------------------------------------------ blocked is final, not a retry loop
@pytest.mark.parametrize("mode,reason", [("challenge", "challenge"), ("denied", "http_403"), ("rate429", "http_429")])
async def test_block_returns_blocked_and_does_not_retry(w, mode, reason):
    w.stores["zepto"].mode = mode
    r = await call(w, "zepto", "set_location", {"pincode": "560034"})
    assert r["status"] == "blocked" and r["reason"] == reason and "web sources" in r["advice"]
    n = len(w.stores["zepto"].hits)
    for tool, args in (("set_location", {"pincode": "560034"}), ("search_products", {"query": "atta"}), ("view_cart", {})):
        again = await call(w, "zepto", tool, args)
        assert again["status"] == "blocked" and again["cooldown"] is True
    assert len(w.stores["zepto"].hits) == n  # nothing more was sent to the site


async def test_cooldown_ends_and_other_sites_and_users_are_unaffected(w):
    w.stores["zepto"].mode = "challenge"
    await call(w, "zepto", "set_location", {"pincode": "560034"})
    assert (await call(w, "blinkit", "set_location", {"pincode": "560034"}))["status"] == "ok"
    assert (await call(w, "zepto", "set_location", {"pincode": "560034"}, user="u2"))["status"] == "blocked"  # the site is blocking everyone
    w.stores["zepto"].mode = "ok"
    w.clock.t += 601  # past cooldown_s
    assert (await call(w, "zepto", "set_location", {"pincode": "560034"}))["status"] == "ok"


# ------------------------------------------------------------------ robots.txt for anonymous pages
async def test_robots_disallow_blocks_anonymous_page_without_fetching_it():
    w = make_world(robots_aware=True)
    try:
        w.stores["zepto"].robots = "User-agent: *\nDisallow: /search\n"
        assert (await call(w, "zepto", "set_location", {"pincode": "560034"}))["status"] == "ok"
        r = await call(w, "zepto", "search_products", {"query": "atta"})
        assert r["status"] == "blocked" and r["reason"] == "robots"
        assert "/search" not in w.stores["zepto"].hits
        assert "/robots.txt" in w.stores["zepto"].hits
    finally:
        w.stop()


async def test_unreadable_robots_is_treated_as_disallowed():
    w = make_world(robots_aware=True)
    try:
        w.stores["blinkit"].stop()  # robots fetch fails
        r = await call(w, "blinkit", "set_location", {"pincode": "560034"})
        assert r["status"] == "blocked" and r["reason"] == "robots"
    finally:
        w.stop()


# ------------------------------------------------------------------ polite pacing
async def test_page_loads_are_paced_per_site_and_user():
    w = make_world(rate=(4.0, 3.0))
    try:
        await call(w, "zepto", "set_location", {"pincode": "560034"})
        await call(w, "zepto", "search_products", {"query": "atta"})
        await call(w, "zepto", "search_products", {"query": "milk"})
        assert len(w.clock.slept) == 2 and all(s >= 4.0 - 1e-6 for s in w.clock.slept)
        before = w.clock.t
        await call(w, "zepto", "search_products", {"query": "milk"}, user="u2")  # same site, other user: still the site interval
        assert w.clock.t - before >= 0
    finally:
        w.stop()


async def test_too_long_a_wait_is_rate_limited_not_slept():
    w = make_world(rate=(100.0, 100.0))  # max_wait_s is 30
    try:
        await call(w, "zepto", "set_location", {"pincode": "560034"})
        assert (await call(w, "zepto", "search_products", {"query": "atta"}))["status"] == "rate_limited"
    finally:
        w.stop()


# ------------------------------------------------------------------ users are isolated
async def test_two_users_have_separate_sessions_logins_and_carts(w):
    for u in ("alice", "bob"):
        await call(w, "zepto", "set_location", {"pincode": "560034"}, user=u)
    pid = (await call(w, "zepto", "search_products", {"query": "milk"}, user="alice"))["items"][0]["id"]
    await call(w, "zepto", "add_to_cart", {"id": pid, "qty": 3}, user="alice")
    assert (await call(w, "zepto", "view_cart", user="bob"))["empty"] is True
    assert (await call(w, "zepto", "view_cart", user="alice"))["items"][0]["qty"] == "3"
    await call(w, "zepto", "login_start", {"phone": "9000000001"}, user="alice")
    w.otp.submit(w.started[-1][2], "246810")
    assert (await call(w, "zepto", "login_status", user="alice"))["status"] == "logged_in"
    assert (await call(w, "zepto", "login_status", user="bob"))["status"] == "needs_login"
    assert w.vault.has("alice", "zepto") and not w.vault.has("bob", "zepto")
    jars = {id(s.jar) for s in w.factory.sessions}
    assert len(jars) == len(w.factory.sessions) >= 2


async def test_forget_my_logins_erases_cookies_and_closes_contexts(w):
    await call(w, "zepto", "login_start", {"phone": "9000000001"}, user="alice")
    w.otp.submit(w.started[-1][2], "246810")
    await call(w, "zepto", "login_status", user="alice")
    await call(w, "blinkit", "set_location", {"pincode": "560034"}, user="alice")
    assert w.vault.has("alice", "zepto")
    await w.hub.forget_user("alice")
    assert not w.vault.has("alice", "zepto") and w.pool.open_count() == 0 and w.factory.live() == 0
    # a returning user starts logged out
    assert (await call(w, "zepto", "login_status", user="alice"))["status"] == "needs_login"


async def test_a_saved_session_is_reused_after_the_context_was_reaped(w):
    await call(w, "zepto", "login_start", {"phone": "9000000001"}, user="alice")
    w.otp.submit(w.started[-1][2], "246810")
    await call(w, "zepto", "login_status", user="alice")
    w.clock.t += 500  # idle timeout is 100 s
    assert await w.pool.reap() == 1 and w.factory.live() == 0
    assert (await call(w, "zepto", "login_status", user="alice"))["status"] == "logged_in"  # cookies came back from the encrypted vault


def test_vault_holds_ciphertext_not_cookies(w):
    w.vault.save("alice", "zepto", {"cookies": [{"name": "sid", "value": "SECRETVALUE"}]})
    raw = str(list(w.vault._store.data.values()))  # type: ignore[attr-defined]
    assert "SECRETVALUE" not in raw


# ------------------------------------------------------------------ RAM: memory guard and caps
async def test_memory_guard_refuses_new_sessions_but_keeps_existing_ones(w):
    await call(w, "zepto", "set_location", {"pincode": "560034"})
    w.mem[0] = 100.0
    r = await call(w, "blinkit", "set_location", {"pincode": "560034"})
    assert r == {"status": "busy", "reason": "low_memory"}
    assert (await call(w, "zepto", "search_products", {"query": "atta"}))["status"] == "ok"  # existing session still works
    assert w.factory.opened == 1


async def test_session_cap_evicts_the_least_recently_used_idle_session():
    w = make_world(max_sessions=2)
    try:
        for u in ("a", "b", "c"):
            w.clock.t += 1
            await call(w, "zepto", "set_location", {"pincode": "560034"}, user=u)
        assert w.pool.open_count() == 2 and w.pool.users() == {"b", "c"} and w.factory.live() == 2
    finally:
        w.stop()


async def test_idle_sessions_are_closed():
    w = make_world()
    try:
        await call(w, "zepto", "set_location", {"pincode": "560034"})
        w.clock.t += 50
        assert await w.pool.reap() == 0
        w.clock.t += 100
        assert await w.pool.reap() == 1 and w.factory.live() == 0
    finally:
        w.stop()


async def test_browser_unavailable_is_busy_not_a_crash(w):
    async def boom(kb, state):
        raise RuntimeError("no chromium")

    w.factory.open = boom  # type: ignore[method-assign]
    r = await call(w, "zepto", "set_location", {"pincode": "560034"})
    assert r["status"] == "busy" and r["reason"].startswith("browser_unavailable")


# ------------------------------------------------------------------ same tools everywhere, no payment anywhere
async def test_tool_names_and_schemas_are_identical_across_sites(w):
    lists = {s: await w.hub.list_tools(s) for s in SITES}
    names = {s: [t["name"] for t in v] for s, v in lists.items()}
    assert all(n == list(TOOL_NAMES) for n in names.values())
    assert lists["zepto"] == lists["blinkit"] == lists["instamart"]


def test_no_payment_or_order_tool_can_exist():
    for bad in ("pay", "place_order", "confirm_order", "buy_now", "submit_payment", "upi_pay", "checkout", "order"):
        with pytest.raises(ValueError):
            assert_no_payment_tools([bad])
    assert_no_payment_tools(TOOL_NAMES)
    for n in TOOL_NAMES:
        assert not any(x in n for x in ("pay", "order", "purchase", "buy"))


async def test_the_guard_refuses_payment_clicks_fills_and_urls(w):
    sess = await w.factory.open(w.kbs["zepto"], None)
    safe = SafeSession(sess, w.kbs["zepto"], "u", limiter=w.pool.limiter, robots=None)
    base = w.kbs["zepto"]["base_url"]
    for sel in (".pay-now", "#place-order", "button.confirm-order", "[data-testid=upi-pay]"):
        with pytest.raises(PaymentBlocked):
            await safe.click(sel)
    with pytest.raises(PaymentBlocked):
        await safe.fill("input.card-number", "4111")
    for url in (base + "/payment", base + "/pay/", "https://rzp.razorpay.com/x", "http://evil.test/"):
        with pytest.raises(PaymentBlocked):
            await safe.goto(url)
    assert w.stores["zepto"].payments == 0 and "/pay" not in w.stores["zepto"].hits


async def test_proceed_to_checkout_is_the_only_exempt_click_and_only_when_verified(w):
    kb = w.kbs["zepto"]
    proceed = kb["checkout"]["proceed"]
    sess = await w.factory.open(kb, None)
    strict = SafeSession(sess, kb, "u", limiter=w.pool.limiter, robots=None)
    assert not smells_like_payment_selector(proceed)
    kb2 = {**kb, "checkout": {**kb["checkout"], "proceed": "#pay-now"}}
    assert any("checkout.proceed" in p for p in validate(kb2))
    assert strict._exempt == frozenset()


def test_knowledge_edit_cannot_add_a_payment_step():
    kb = load_knowledge()["zepto"]
    for sec, key, bad in (("product", "add", ".place-order"), ("login", "verify", "button.pay-now"), ("checkout", "proceed", ".confirm-order")):
        doc = {**kb, sec: {**kb[sec], key: bad}}
        assert validate(doc), (sec, key)
    doc = {**kb, "urls": {**kb["urls"], "cart": "/payment"}}
    assert validate(doc)
