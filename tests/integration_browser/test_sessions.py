"""Runtime scenarios on the fake backend: per-user isolation, vault, takeover, kill switch, limits."""

from __future__ import annotations

import json

import pytest

from friday.connectors.browser.backend import FakeBackend
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.browser.port import NetworkBlocked
from friday.connectors.session.manager import SessionManager, SessionRefused, TakeoverError
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.session.vault import InMemoryVaultStore, StorageVault
from friday.core.crypto import FieldCipher, LocalKeyProvider

POLICY = NetworkPolicy.for_hosts(["shop.test", "*.shop.test"])
COOKIE = "SESSIONCOOKIE-abc123-secret"


def make(enabled="u1,u2", **kw):
    backend = FakeBackend()
    cipher = FieldCipher(LocalKeyProvider({"k1": b"k" * 32}, index_key=b"i" * 32))
    store = InMemoryVaultStore()
    vault = StorageVault(store, cipher)
    mgr = SessionManager(backend, vault, BrowserSettings(enabled=True, enabled_users=enabled, **kw))
    return mgr, backend, vault, store


async def test_default_off_even_when_enabled_flag_names_nobody():
    mgr, *_ = make(enabled="")
    with pytest.raises(SessionRefused):
        await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    off = SessionManager(FakeBackend(), None, BrowserSettings())
    with pytest.raises(SessionRefused):
        await off.open("u1", "shop.test", "t1", policy=POLICY)


async def test_two_users_have_separate_browsers_and_logins():
    mgr, backend, vault, store = make()
    a = await mgr.open("u1", "shop.test", "ta", policy=POLICY)
    b = await mgr.open("u2", "shop.test", "tb", policy=POLICY)
    backend.sessions[0].set_cookie("sid", COOKIE)
    assert backend.sessions[0] is not backend.sessions[1]
    await mgr.close("ta")
    await mgr.close("tb")
    assert [c["name"] for c in vault.load("u1", "shop.test")["cookies"]] == ["sid"]
    assert vault.load("u2", "shop.test")["cookies"] == []
    # next task of u2 starts logged out; u1 gets the saved login back
    await mgr.open("u2", "shop.test", "tb2", policy=POLICY)
    assert backend.sessions[2].cookies == []
    assert a.info.user_id == "u1" and b.info.user_id == "u2"
    # ciphertext only on disk, and a copied slot does not decrypt for another user
    assert COOKIE not in json.dumps(list(store.data.values()))
    slot_a = vault._slot("u1", "shop.test")  # noqa: SLF001
    store.data[vault._slot("u2", "shop.test")] = dict(store.data[slot_a])  # noqa: SLF001
    assert vault.load("u2", "shop.test") is None


async def test_per_user_cap_and_kill_all():
    mgr, backend, *_ = make()
    s = await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    with pytest.raises(SessionRefused):
        await mgr.open("u1", "shop.test", "t2", policy=POLICY)
    n = await mgr.kill_all()
    assert n == 1 and backend.sessions[0].closed and s.closed
    assert mgr.active() == []
    assert [e["event"] for e in mgr.audit.entries(event="kill_all")] == ["kill_all"]


async def test_kill_all_is_latched():
    mgr, *_ = make()
    await mgr.kill_all()
    with pytest.raises(SessionRefused):
        await mgr.open("u1", "shop.test", "t9", policy=POLICY)


async def test_domain_allow_list_and_ssrf():
    mgr, *_ = make()
    s = await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    for url in ("https://evil.test/", "http://169.254.169.254/", "http://127.0.0.1:8000/",
                "file:///etc/passwd", "https://shop.test.evil.test/"):
        with pytest.raises(NetworkBlocked):
            await s.goto(url)
    await s.goto("https://www.shop.test/menu")


async def test_takeover_pauses_friday_logs_counts_not_text_and_secret_typing_stays_out():
    mgr, backend, *_ = make()
    s = await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    with pytest.raises(TakeoverError):
        await s.takeover_input({"kind": "type", "text": "x"})  # not in takeover
    s.begin_takeover()
    await s.takeover_input({"kind": "type", "text": "MyP@ssw0rd!"})
    with pytest.raises(TakeoverError):
        await s.takeover_input({"kind": "key", "key": "F12"})
    s.give_back()
    blob = json.dumps([e for e in mgr.audit.entries()], default=str)
    assert "MyP@ssw0rd" not in blob
    ev = mgr.audit.entries(event="takeover_end")[0]
    assert ev["input_events"] == 1
    await mgr.close("t1")


async def test_frames_for_the_live_view_are_always_masked():
    from friday.connectors.recorder import MASK_SELECTORS

    mgr, backend, *_ = make()
    s = await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    await s.frame()
    assert backend.sessions[0].screenshot_masks[-1] == MASK_SELECTORS
