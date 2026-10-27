# ruff: noqa: E501
"""The one-time secure page that saves a website login (mounted by `friday serve` through
mount_browser): token expiry, CSRF, headers, rate limit, iPad-friendly form, wrong user, WhatsApp
commands "my logins" / "forget my logins" / "forget <site>" with confirmation. Fakes only."""

from __future__ import annotations

import re
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.connectors_credentials import credentials_router
from friday.api.page_security import PageLimiter, client_key, same_site
from friday.connectors.flow import register_browser_handler
from friday.connectors.session import (
    AuditLog,
    BrowserSettings,
    CredentialService,
    CredentialTokenRegistry,
    CredentialVault,
    InMemoryVaultStore,
)
from tests.browser_runtime.conftest import make_cipher
from tests.chatbot.conftest import build_chat

PW = "Tr0ub4dor&3-secret"
HOSTS = ["www.fake.test", "*.fake.test"]
FORM = {"content-type": "application/x-www-form-urlencoded"}
IPAD = {"user-agent": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Safari/604.1"}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cvault(clock):
    return CredentialVault(InMemoryVaultStore(), make_cipher(), clock=clock)


@pytest.fixture
def svc(cvault, clock):
    s = BrowserSettings(enabled=True, enabled_users="*", backend="fake", credentials_enabled=True,
                        credentials_enabled_users="*")
    return CredentialService(cvault, CredentialTokenRegistry(clock=clock), s, AuditLog(),
                             base_url="https://f.example")


def app_for(svc, cvault, limiter=None):
    app = FastAPI()
    app.include_router(credentials_router(svc.tokens, cvault, limiter), prefix="/connectors")
    return TestClient(app, headers=IPAD)


def tok(link: str) -> str:
    return link.rsplit("/", 1)[1]


def body(svc, token, **over):
    d = {"u": "ravi", "p": PW, "c": "1", "t": svc.tokens.get(token).csrf, **over}
    return urlencode(d)


# ------------------------------------------------------------------ the page itself
def test_page_works_on_an_ipad_and_sends_the_hardening_headers(svc, cvault):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("u", "fake", HOSTS))
    r = c.get(f"/connectors/credentials/{t}")
    assert r.status_code == 200
    h = r.headers
    assert "no-store" in h["cache-control"] and h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY" and h["x-robots-tag"] == "noindex" and h["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    html = r.text
    assert "name='viewport' content='width=device-width,initial-scale=1'" in html  # fits an iPad / phone
    sizes = [int(n) for n in re.findall(r"font(?:-size)?:(\d+)px", html)]
    assert sizes and min(sizes) >= 16  # iOS Safari zooms into smaller inputs
    assert "type='password'" in html and "name='t' value=" in html  # page token present
    assert "http://" not in html and "https://" not in html and "<script" not in html  # nothing external, no JS
    assert PW not in html


def test_post_needs_the_page_token(svc, cvault):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("u", "fake", HOSTS))
    for bad in ("", "wrong"):
        r = c.post(f"/connectors/credentials/{t}", content=urlencode({"u": "ravi", "p": PW, "c": "1", "t": bad}), headers=FORM)
        assert r.status_code == 403 and PW not in r.text
    assert not cvault._store.data  # nothing saved
    r = c.post(f"/connectors/credentials/{t}", content=body(svc, t), headers=FORM)
    assert r.status_code == 200 and cvault.release("u", "fake", current_host="www.fake.test").password == PW


def test_wrong_page_tokens_burn_the_link(svc, cvault):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("u", "fake", HOSTS))
    for _ in range(5):
        c.post(f"/connectors/credentials/{t}", content=urlencode({"u": "a", "p": PW, "c": "1", "t": "x"}), headers=FORM)
    assert c.get(f"/connectors/credentials/{t}").status_code == 404


def test_cross_site_posts_are_refused_even_with_a_valid_page_token(svc, cvault):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("u", "fake", HOSTS))
    ok = body(svc, t)
    r = c.post(f"/connectors/credentials/{t}", content=ok, headers={**FORM, "origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post(f"/connectors/credentials/{t}", content=ok, headers={**FORM, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert not cvault._store.data
    r = c.post(f"/connectors/credentials/{t}", content=ok, headers={**FORM, "sec-fetch-site": "same-origin"})
    assert r.status_code == 200


def test_link_expires_after_ten_minutes(svc, cvault, clock):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("u", "fake", HOSTS))
    csrf = svc.tokens.get(t).csrf
    clock.t += 599
    assert c.get(f"/connectors/credentials/{t}").status_code == 200
    clock.t += 2
    assert c.get(f"/connectors/credentials/{t}").status_code == 404
    r = c.post(f"/connectors/credentials/{t}", content=urlencode({"u": "a", "p": PW, "c": "1", "t": csrf}), headers=FORM)
    assert r.status_code == 404 and not cvault._store.data


def test_link_is_bound_to_the_user_who_asked(svc, cvault):
    c = app_for(svc, cvault)
    t = tok(svc.request_link("userA", "fake", HOSTS))
    assert c.post(f"/connectors/credentials/{t}", content=body(svc, t), headers=FORM).status_code == 200
    assert cvault.has("userA", "fake") and not cvault.has("userB", "fake")
    assert cvault.saved_logins("userB") == [] and len(cvault.saved_logins("userA")) == 1
    svc.forget("userB")  # another user's "forget" does not touch it
    assert cvault.has("userA", "fake")


def test_bank_site_is_refused_even_through_the_page(svc, cvault):
    t = svc.tokens.create("u", "fake", ("www.icicibank.com",))
    c = app_for(svc, cvault)
    r = c.post(f"/connectors/credentials/{t}", content=body(svc, t), headers=FORM)
    assert r.status_code == 400 and not cvault._store.data


# ------------------------------------------------------------------ rate limit
def test_rate_limit_per_client_and_for_guessed_tokens(svc, cvault):
    t_clock = Clock()
    lim = PageLimiter(max_hits=5, max_misses=3, window=600, clock=t_clock)
    c = app_for(svc, cvault, lim)
    t = tok(svc.request_link("u", "fake", HOSTS))
    codes = [c.get(f"/connectors/credentials/{t}").status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    assert "Retry-After" in c.get(f"/connectors/credentials/{t}").headers and c.get("/connectors/credentials/x").status_code == 429
    t_clock.t += 601  # the window passes
    assert c.get(f"/connectors/credentials/{t}").status_code == 200
    # guessing: three misses lock the client out, even for a valid link
    c2 = app_for(svc, cvault, PageLimiter(max_hits=50, max_misses=3, clock=Clock()))
    assert [c2.get(f"/connectors/credentials/guess{i}").status_code for i in range(3)] == [404] * 3
    assert c2.get(f"/connectors/credentials/{t}").status_code == 429


def test_client_key_trusts_the_header_only_from_our_own_proxy():
    def req(peer, xff=None):
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff} if xff else {})

    assert client_key(req("172.18.0.5", "203.0.113.9")) == "203.0.113.9"  # behind Caddy
    assert client_key(req("172.18.0.5", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"  # forged first hop ignored
    assert client_key(req("8.8.4.4", "6.6.6.6")) == "8.8.4.4"  # direct public peer: header ignored
    assert client_key(SimpleNamespace(client=None, headers={})) == "unknown"
    assert same_site({"host": "a.test"}) and not same_site({"host": "a.test", "origin": "https://b.test"})
    assert same_site({"host": "a.test", "origin": "https://a.test"}) and same_site({"host": "a.test", "origin": "null"})


# ------------------------------------------------------------------ WhatsApp + the mounted app
@pytest.fixture(autouse=True)
def _clean_handler():
    register_browser_handler(None)
    yield
    register_browser_handler(None)


def on(tmp_path, **over):
    return {"browser_enabled": True, "browser_enabled_users": ["*"], "browser_backend": "fake",
            "browser_vault_dir": str(tmp_path / "v"), "browser_credentials_dir": str(tmp_path / "c"),
            "browser_audit_file": str(tmp_path / "a.jsonl"), "browser_credentials_enabled": True,
            "browser_credentials_enabled_users": ["*"], **over}


async def test_whatsapp_link_to_page_to_my_logins_to_forget_one_site(tmp_path):
    from friday.api.app import create_app

    w = await build_chat(**on(tmp_path, public_base_url="https://f.example"))
    try:
        await w.onboard()
        user = await w.user()
        out = await w.say("save blinkit login")
        link = next(m.text for m in out if "/connectors/credentials/" in (m.text or ""))
        path = "/connectors/credentials/" + re.search(r"/connectors/credentials/([\w-]+)", link).group(1)
        client = TestClient(create_app(w.c, background=False), headers=IPAD)
        stack = w.pipeline.browser
        # the app builds its own pipeline/stack; share the token registry by saving through that stack
        app_stack = client.app.state.browser
        app_stack.cred_tokens._entries.update(stack.cred_tokens._entries)  # same link, served by the mounted app
        page = client.get(path)
        assert page.status_code == 200 and "blinkit" in page.text.lower()
        csrf = re.search(r"name='t' value='([^']+)'", page.text).group(1)
        r = client.post(path, content=urlencode({"u": "asha@example.test", "p": PW, "c": "1", "t": csrf}), headers=FORM)
        assert r.status_code == 200 and PW not in r.text
        assert client.get(path).status_code == 404  # one use
        stack.cred_vault._store = app_stack.cred_vault._store  # the file store is shared on disk anyway
        shown = " ".join(m.text or "" for m in await w.say("my logins"))
        assert "blinkit" in shown and PW not in shown and "asha@example.test" not in shown
        # forget one site: asks first
        ask = await w.say("forget blinkit")
        assert ask[0].buttons and [b.id for b in ask[0].buttons] == ["lg:yes", "lg:no"]
        assert stack.cred_vault.has(user.id, "blinkit")
        await w.say("nahi")
        assert stack.cred_vault.has(user.id, "blinkit")  # kept
        await w.say("forget blinkit")
        done = await w.say("haan")
        assert done and not stack.cred_vault.has(user.id, "blinkit")
        # a stale button does nothing
        assert await w.tap_id("lg:yes") == []
    finally:
        await w.c.aclose()


async def test_forget_all_asks_first_and_can_be_cancelled_by_button_or_other_text(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        for site, host in (("blinkit", "blinkit.com"), ("zepto", "www.zeptonow.com")):
            stack.cred_vault.save(user.id, site, "u@example.test", PW, hosts=[host], consent=True)
        ask = await w.say("forget my logins")
        assert "2" in ask[0].text and len(stack.cred_vault.saved_logins(user.id)) == 2
        out = await w.tap_id("lg:no")
        assert out and len(stack.cred_vault.saved_logins(user.id)) == 2
        await w.say("forget my logins")
        await w.say("what is the weather")  # anything else drops the question
        assert await w.tap_id("lg:yes") == []
        assert len(stack.cred_vault.saved_logins(user.id)) == 2
        await w.say("forget my logins")
        await w.tap_id("lg:yes")
        assert stack.cred_vault.saved_logins(user.id) == []
    finally:
        await w.c.aclose()


async def test_forget_unknown_words_and_unsaved_sites(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.cred_vault.save(user.id, "zepto", "u@example.test", PW, hosts=["www.zeptonow.com"], consent=True)
        out = await w.say("forget it")  # not a site: left to the normal chat
        assert all("lg:" not in str(b.id) for m in out for b in m.buttons)
        out = await w.say("forget blinkit")  # a known site with no saved login
        assert out and not out[0].buttons
        assert stack.cred_vault.has(user.id, "zepto")
    finally:
        await w.c.aclose()


async def test_my_logins_when_switch_is_off_and_nothing_saved(tmp_path):
    w = await build_chat(**on(tmp_path, browser_credentials_enabled=False))
    try:
        await w.onboard()
        out = await w.say("my logins")
        assert out and not out[0].buttons
        user = await w.user()
        stack = w.pipeline.browser
        stack.cred_vault.save(user.id, "zepto", "u@example.test", PW, hosts=["www.zeptonow.com"], consent=True)
        shown = " ".join(m.text or "" for m in await w.say("my logins"))  # leftovers can still be seen and deleted
        assert "zepto" in shown and PW not in shown
    finally:
        await w.c.aclose()
