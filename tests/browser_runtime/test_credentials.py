"""Website password vault: encryption, isolation, consent, blocked sites, host binding,
one-time page, autofill inside the worker only, deletion. docs/CREDENTIAL_VAULT.md"""

from __future__ import annotations

import json
import pickle
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.connectors_credentials import credentials_router
from friday.connectors.browser.fake import FakeLiveSession
from friday.connectors.session import (
    AuditLog,
    BrowserSettings,
    CredentialError,
    CredentialService,
    CredentialTokenRegistry,
    CredentialVault,
    InMemoryVaultStore,
)

from .conftest import POLICY, make_cipher

PW = "Tr0ub4dor&3-secret"
HOSTS = ["www.fake.test", "*.fake.test"]


@pytest.fixture
def cvault(clock):
    return CredentialVault(InMemoryVaultStore(), make_cipher(), clock=clock)


@pytest.fixture
def csettings():
    return BrowserSettings(enabled=True, enabled_users="*", backend="fake",
                           credentials_enabled=True, credentials_enabled_users="*")


@pytest.fixture
def svc(cvault, csettings, clock):
    return CredentialService(cvault, CredentialTokenRegistry(clock=clock), csettings,
                             AuditLog(), base_url="https://f.example")


def test_stored_encrypted_and_isolated(cvault):
    cvault.save("userA", "fake", "ravi@x.in", PW, hosts=HOSTS, consent=True)
    raw = json.dumps(cvault._store.data)
    assert PW not in raw and "ravi" not in raw and "userA" not in raw and "fake" not in raw
    assert cvault.release("userA", "fake", current_host="www.fake.test").password == PW
    assert cvault.release("userB", "fake", current_host="www.fake.test") is None
    assert cvault.release("userA", "other", current_host="www.fake.test") is None


def test_ciphertext_cannot_be_moved_to_another_user(cvault):
    cvault.save("userA", "fake", "ravi", PW, hosts=HOSTS, consent=True)
    (slot,) = cvault._store.data
    cvault._store.data[cvault._slot("userB", "fake")] = dict(cvault._store.data[slot])
    assert cvault.release("userB", "fake", current_host="www.fake.test") is None


def test_consent_required_and_blocked_sites_refused(cvault):
    with pytest.raises(CredentialError):
        cvault.save("u", "fake", "a", PW, hosts=HOSTS, consent=False)
    for site, host in [("hdfc", "netbanking.hdfcbank.com"), ("irctc", "www.irctc.co.in"),
                       ("paytm", "paytm.com"), ("upi", "upi.example"),
                       ("shop", "online.sbi")]:
        with pytest.raises(CredentialError):
            cvault.save("u", site, "a", PW, hosts=[host], consent=True)
    assert not cvault._store.data


def test_released_only_on_a_saved_host(cvault):
    cvault.save("u", "fake", "ravi", PW, hosts=HOSTS, consent=True)
    assert cvault.release("u", "fake", current_host="https://www.fake.test/login")
    assert cvault.release("u", "fake", current_host="evil.example") is None
    assert cvault.release("u", "fake", current_host="fake.test.evil.example") is None
    assert cvault.release("u", "fake", current_host="") is None


def test_credential_cannot_leak_through_print_pickle_format(cvault):
    cvault.save("u", "fake", "ravi", PW, hosts=HOSTS, consent=True)
    cred = cvault.release("u", "fake", current_host="www.fake.test")
    for out in (repr(cred), str(cred), f"{cred}", "%s" % cred):  # noqa: UP031
        assert PW not in out and "ravi" not in out
    with pytest.raises(TypeError):
        pickle.dumps(cred)


def test_saved_list_shows_masked_username_never_password(cvault):
    cvault.save("u", "fake", "ravi@x.in", PW, hosts=HOSTS, consent=True)
    cvault.save("u", "shop", "meena", PW, hosts=["shop.test"], consent=True)
    (a, b) = cvault.saved_logins("u")
    assert (a.site, a.username_hint) == ("fake", "ra***") and b.site == "shop"
    assert PW not in repr(cvault.saved_logins("u")) and cvault.saved_logins("other") == []


def test_expiry_and_delete(cvault, clock):
    cvault.save("u", "fake", "r", PW, hosts=HOSTS, consent=True)
    cvault.save("u", "shop", "r", PW, hosts=["shop.test"], consent=True)
    cvault.delete("u", "shop")
    assert not cvault.has("u", "shop") and cvault.has("u", "fake")
    clock.t += 91 * 86400
    assert not cvault.has("u", "fake")
    cvault.save("u", "fake", "r", PW, hosts=HOSTS, consent=True)
    assert cvault.delete_user("u") == 1 and cvault.saved_logins("u") == []


# ---------------------------------------------------------------- service + page
def page(svc, cvault):
    app = FastAPI()
    app.include_router(credentials_router(svc.tokens, cvault), prefix="/connectors")
    return TestClient(app)


def token_of(link: str) -> str:
    return link.rsplit("/", 1)[1]


def test_off_by_default_and_blocked_site_gets_no_link(cvault, clock):
    off = CredentialService(cvault, CredentialTokenRegistry(clock=clock), BrowserSettings(),
                            base_url="https://f.example")
    with pytest.raises(CredentialError):
        off.request_link("u", "fake", HOSTS)


def test_link_refused_for_bank(svc):
    with pytest.raises(CredentialError):
        svc.request_link("u", "icici", ["www.icicibank.com"])


def test_secure_page_saves_once_and_never_echoes(svc, cvault):
    c = page(svc, cvault)
    tok = token_of(svc.request_link("u", "fake", HOSTS))
    r = c.get(f"/connectors/credentials/{tok}")
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    body = urlencode({"u": "ravi", "p": PW, "c": "1"})
    r = c.post(f"/connectors/credentials/{tok}", content=body,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and PW not in r.text and "ravi" not in r.text
    assert cvault.release("u", "fake", current_host="www.fake.test").password == PW
    assert c.get(f"/connectors/credentials/{tok}").status_code == 404  # single use


def test_page_requires_consent_and_burns_after_attempts(svc, cvault):
    c = page(svc, cvault)
    tok = token_of(svc.request_link("u", "fake", HOSTS))
    for i in range(5):
        r = c.post(f"/connectors/credentials/{tok}", content=urlencode({"u": "a", "p": PW}))
        assert r.status_code == (400 if i < 4 else 429)
        assert PW not in r.text
    assert c.get(f"/connectors/credentials/{tok}").status_code == 404
    assert not cvault._store.data


def test_page_rejects_cross_site_oversize_and_unknown(svc, cvault):
    c = page(svc, cvault)
    tok = token_of(svc.request_link("u", "fake", HOSTS))
    r = c.post(f"/connectors/credentials/{tok}", content="u=a&p=b&c=1",
               headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post(f"/connectors/credentials/{tok}", content="p=" + "x" * 5000).status_code == 413
    assert c.get("/connectors/credentials/nope").status_code == 404


def test_forget_removes_everything_and_links(svc, cvault):
    cvault.save("u", "fake", "r", PW, hosts=HOSTS, consent=True)
    tok = token_of(svc.request_link("u", "shop", ["shop.test"]))
    assert svc.forget("u") == 1
    assert svc.saved("u") == [] and svc.tokens.get(tok) is None


# ---------------------------------------------------------------- autofill in the worker
async def test_autofill_fills_site_fields_and_audits_without_values(svc, cvault, mgr,
                                                                    monkeypatch):
    filled = []

    async def fill(self, selector, value):
        filled.append((selector, value))

    monkeypatch.setattr(FakeLiveSession, "fill", fill)
    cvault.save("u1", "fake", "ravi", PW, hosts=HOSTS, consent=True)
    async with mgr.session("u1", "fake", "t1", policy=POLICY) as s:
        assert await svc.autofill(s, username_selector="#u", password_selector="#p") is False
        await s.goto("https://www.fake.test/login")
        assert await svc.autofill(s, username_selector="#u", password_selector="#p",
                                  submit_selector="#go") is True
    assert filled == [("#u", "ravi"), ("#p", PW)]
    blob = json.dumps(svc.audit.entries()) + json.dumps(mgr.audit.entries())
    assert PW not in blob and "ravi" not in blob
    assert svc.audit.entries(event="credential_autofill")


async def test_autofill_refuses_other_users_site_and_disabled(svc, cvault, mgr, csettings):
    cvault.save("u1", "fake", "ravi", PW, hosts=HOSTS, consent=True)
    async with mgr.session("u2", "fake", "t2", policy=POLICY) as s:  # another user
        await s.goto("https://www.fake.test/login")
        assert await svc.autofill(s, username_selector="#u", password_selector="#p") is False
    csettings.credentials_enabled = False
    async with mgr.session("u1", "fake", "t3", policy=POLICY) as s:
        await s.goto("https://www.fake.test/login")
        assert await svc.autofill(s, username_selector="#u", password_selector="#p") is False
