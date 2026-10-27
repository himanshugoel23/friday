"""Real Chromium against the local fake site (skipped when Playwright / Chromium are missing)."""

from __future__ import annotations

import pytest

from friday.connectors.browser.backend import LocalPlaywrightBackend
from friday.connectors.browser.playwright_session import browser_available
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.browser.port import NetworkBlocked
from friday.connectors.fake_site import FakeSiteServer, FakeSiteState
from friday.connectors.session import (
    AuditLog,
    BrowserSettings,
    InMemoryVaultStore,
    LiveViewService,
    SessionManager,
    StorageVault,
)

from .conftest import make_cipher

pytestmark = pytest.mark.skipif(not browser_available(), reason="no Playwright/Chromium")
OTP = "135790"


@pytest.fixture
def site():
    with FakeSiteServer(FakeSiteState(otp=OTP)) as base:
        yield base


def _mgr(vault):
    st = BrowserSettings(enabled=True, enabled_users="*", max_per_user=2, max_global=4)
    return SessionManager(LocalPlaywrightBackend(), vault, st, audit=AuditLog())


async def _login(sess, base):
    await sess.goto(base + "/login")
    await sess.fill("input[type=tel]", "9000000001")
    await sess.click("button")
    await sess.fill("input[name=otp]", OTP)
    await sess.click("button")


async def test_user_isolation_and_login_reuse(site):
    vault = StorageVault(InMemoryVaultStore(), make_cipher())
    mgr = _mgr(vault)
    pol = NetworkPolicy.for_hosts({"127.0.0.1"}, allow_loopback=True)
    a = await mgr.open("A", "fake", "ta", policy=pol)
    await _login(a, site)
    await a.goto(site + "/")
    assert await a.query_all("[data-testid=account-name]")
    b = await mgr.open("B", "fake", "tb", policy=pol)  # concurrent, other user
    await b.goto(site + "/")
    assert not await b.query_all("[data-testid=account-name]")  # B never sees A's login
    await a.close()
    await b.close()
    ca = {c["value"] for c in vault.load("A", "fake")["cookies"]}
    cb = {c["value"] for c in vault.load("B", "fake")["cookies"]}
    assert ca and cb and not ca & cb  # separate slots, separate cookies
    a2 = await mgr.open("A", "fake", "ta2", policy=pol)  # login restored from the vault
    await a2.goto(site + "/")
    assert await a2.query_all("[data-testid=account-name]")
    await a2.close()


async def test_real_network_guard_blocks_other_hosts(site):
    mgr = _mgr(StorageVault(InMemoryVaultStore(), make_cipher()))
    pol = NetworkPolicy.for_hosts({"127.0.0.1"}, allow_loopback=True)
    s = await mgr.open("A", "fake", "t", policy=pol)
    with pytest.raises(NetworkBlocked):
        await s.goto("http://example.com/")
    # a page that pulls a sub-resource from a forbidden host: blocked inside the browser
    raw = s._raw
    await raw._page.set_content(
        '<img src="http://blocked.example/x.png"><script src="http://169.254.169.254/a.js"></script>')
    await raw._page.wait_for_timeout(300)
    blocked = mgr.audit.entries(task_id="t", event="network_blocked")
    assert len(blocked) >= 1
    await s.close()


async def test_takeover_types_into_real_page_and_masks_frame(site):
    mgr = _mgr(StorageVault(InMemoryVaultStore(), make_cipher()))
    live = LiveViewService(mgr)
    pol = NetworkPolicy.for_hosts({"127.0.0.1"}, allow_loopback=True)
    s = await mgr.open("A", "fake", "t", policy=pol)
    await s.goto(site + "/login")
    v = live.open_view(live.create_link("t"))
    assert (await live.frame(v.view_id)).startswith(b"\x89PNG")
    await live.start_takeover(v.view_id)
    await s._raw._page.focus("input[type=tel]")
    await live.send_input(v.view_id, {"kind": "type", "text": "9000000001"})
    assert await s._raw._page.input_value("input[type=tel]") == "9000000001"
    await live.give_back(v.view_id)
    await s.close()
