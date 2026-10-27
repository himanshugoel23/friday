"""EM review findings (docs/PRIVATE_BROWSER.md section 7): each fixed finding has a test here."""

from __future__ import annotations

import json

import pytest

from friday.connectors.browser.backend import FakeBackend
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.browser.port import BrowserError, ElementNotFound
from friday.connectors.session.audit import AuditLog, JsonlAuditSink
from friday.connectors.session.killswitch import PauseWatcher
from friday.connectors.session.manager import SessionManager, SessionRefused
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.session.vault import FileVaultStore, InMemoryVaultStore, StorageVault
from friday.connectors.sites.errors import UnsafeAction
from friday.connectors.sites.fakes.food_site import ScenarioFoodSession, ScenarioFoodState
from friday.connectors.sites.locator import FakeRepairer
from friday.connectors.sites.zomato_agent import build_kit
from friday.core.crypto import FieldCipher, LocalKeyProvider

POLICY = NetworkPolicy.for_hosts(["shop.test"])


def cipher():
    return FieldCipher(LocalKeyProvider({"k1": b"k" * 32}, index_key=b"i" * 32))


def make(paused=None, **kw):
    backend = FakeBackend()
    vault = StorageVault(InMemoryVaultStore(), cipher())
    mgr = SessionManager(backend, vault, BrowserSettings(enabled=True, enabled_users="u1,u2", **kw),
                         paused=paused)
    return mgr, backend


# ------------------------------------------------------------------ A1: kill_all latches
async def test_kill_all_latches_until_revive():
    mgr, _ = make()
    await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    await mgr.kill_all("operator")
    assert mgr.latched == "operator"
    for tid in ("t2", "t3"):
        with pytest.raises(SessionRefused):
            await mgr.open("u2", "shop.test", tid, policy=POLICY)
    assert mgr.revive() is True and mgr.latched is None
    assert mgr.revive() is False
    s = await mgr.open("u1", "shop.test", "t4", policy=POLICY)
    assert not s.closed
    assert mgr.audit.entries(event="revive")


async def test_kill_all_with_no_sessions_still_latches():
    mgr, _ = make()
    assert await mgr.kill_all() == 0
    with pytest.raises(SessionRefused):
        await mgr.open("u1", "shop.test", "t1", policy=POLICY)


async def test_pause_watcher_revives_only_its_own_latch():
    flag = {"on": True}
    mgr, _ = make(paused=lambda: flag["on"])
    w = PauseWatcher(mgr, lambda: flag["on"])
    await w.check_once()
    assert mgr.latched == "paused"
    flag["on"] = False
    await w.check_once()
    assert mgr.latched is None  # `friday pause --resume` lifts what the pause latched
    await mgr.kill_all("operator")
    await w.check_once()
    assert mgr.latched == "operator"  # a manual kill stays until an operator revives


# ------------------------------------------------------------------ A2: no typing into password fields
async def test_fill_refuses_a_password_field_unless_the_credential_path_says_so():
    mgr, backend = make()
    s = await mgr.open("u1", "shop.test", "t1", policy=POLICY)
    raw = backend.sessions[0]
    seen = []

    async def q(selector, fields=None):
        return [{"t": "password" if selector == "#p" else "text"}]

    raw.query_all = q
    orig = raw.fill

    async def spy(selector, value):
        seen.append(selector)
        await orig(selector, value)

    raw.fill = spy
    with pytest.raises(BrowserError):
        await s.fill("#p", "hunter2")
    await s.fill("#name", "asha")
    await s.fill("#p", "hunter2", allow_secret_field=True)
    assert seen == ["#name", "#p"]
    blob = json.dumps(mgr.audit.entries())
    assert "hunter2" not in blob and mgr.audit.entries(event="fill_refused")


# ------------------------------------------------------------------ A3 / A4: vault + audit
def test_unreadable_vault_file_is_audited_without_content(tmp_path):
    audit = AuditLog()
    store = FileVaultStore(tmp_path)
    v = StorageVault(store, cipher(), audit=audit)
    v.save("u1", "shop", {"cookies": []})
    for f in tmp_path.glob("*.json"):
        f.write_text("{not json")
    assert v.load("u1", "shop") is None
    ev = audit.entries(event="vault_unreadable")
    assert len(ev) == 1 and "u1" not in json.dumps(ev)


def test_vault_decrypt_failure_is_audited():
    audit, store = AuditLog(), InMemoryVaultStore()
    v = StorageVault(store, cipher(), audit=audit)
    v.save("u1", "shop", {"cookies": []})
    slot = next(iter(store.data))
    store.data[slot]["ct"] = store.data[slot]["ct"][:-4] + "AAAA"
    assert v.load("u1", "shop") is None and audit.entries(event="vault_unreadable")


def test_audit_has_a_durable_scrubbed_sink(tmp_path):
    path = tmp_path / "audit" / "a.jsonl"
    audit = AuditLog(sink=JsonlAuditSink(path))
    audit.record("step", task_id="t", user_id="u", site="s", action="fill", selector="#x",
                 password="hunter2", code="123456")
    audit.record("kill_all", reason="x", count=1)
    lines = path.read_text().splitlines()
    assert [json.loads(x)["event"] for x in lines] == ["step", "kill_all"]
    assert "hunter2" not in path.read_text() and oct(path.stat().st_mode & 0o777) == "0o600"


# ------------------------------------------------------------------ B1 / B2 / B3: the guarded session
def guarded(repairs=None):
    kit = build_kit(ScenarioFoodSession(ScenarioFoodState()), task_id="t",
                    repairer=FakeRepairer(repairs) if repairs is not None else None)
    return kit


class _Stub:
    """Inner session: every selector is missing except those in ``present``; records clicks/fills."""

    def __init__(self, present=()):
        self.present, self.calls = set(present), []

    async def click(self, selector):
        self.calls.append(("click", selector))
        if selector not in self.present:
            raise ElementNotFound(selector)

    async def fill(self, selector, value):
        self.calls.append(("fill", selector))
        if selector not in self.present:
            raise ElementNotFound(selector)

    async def text(self, selector):
        raise ElementNotFound(selector)

    async def query_all(self, selector, fields=None):
        return []

    async def wait_for(self, selector, timeout_ms=5000):
        return None

    async def goto(self, url):
        return None

    async def screenshot(self, mask=()):
        return b""

    async def close(self):
        return None


def stub_guard(present, repairs):
    from friday.connectors.sites.executor import GuardedSession
    from friday.connectors.sites.locator import ElementLocator, RepairLog
    from friday.connectors.sites.reader import PageReader
    from friday.connectors.sites.safety import SiteSafety
    from friday.connectors.sites.verifier import Verifier

    inner = _Stub(present)
    log = RepairLog()
    loc = ElementLocator({"add": "[data-testid=add]", "phone_input": "[data-testid=phone]"}, {},
                         repairer=FakeRepairer(repairs), log=log, task_id="t")
    return GuardedSession(inner, SiteSafety(frozenset({"shop.test"})), loc, PageReader(), Verifier({})), inner, log


async def test_a_repaired_click_is_checked_like_any_other_click():
    g, inner, log = stub_guard({"[data-testid=place-order]"}, {"add": "[data-testid=place-order]"})
    with pytest.raises(UnsafeAction):
        await g.click("[data-testid=add]")
    assert ("click", "[data-testid=place-order]") not in inner.calls


async def test_a_harmless_repaired_click_still_works():
    g, inner, log = stub_guard({"[data-testid=plus]"}, {"add": "[data-testid=plus]"})
    await g.click("[data-testid=add]")
    assert inner.calls[-1] == ("click", "[data-testid=plus]") and len(log.records) == 1


async def test_click_on_an_unknown_key_is_never_repaired():
    g, inner, log = stub_guard({"[data-testid=checkout]"}, {"anything": "[data-testid=checkout]"})
    with pytest.raises(ElementNotFound):
        await g.click("[data-testid=totally-unknown]")
    assert log.records == [] and ("click", "[data-testid=checkout]") not in inner.calls


async def test_a_fill_is_never_repaired():
    g, inner, log = stub_guard({"input[type=password]"}, {"phone_input": "input[type=password]"})
    with pytest.raises(ElementNotFound):
        await g.fill("[data-testid=phone]", "9000000001")
    assert log.records == [] and ("fill", "input[type=password]") not in inner.calls


async def test_fill_into_an_unknown_field_is_refused():
    kit = build_kit(ScenarioFoodSession(ScenarioFoodState()), task_id="t")
    with pytest.raises(UnsafeAction):
        await kit.session.fill("input[name=whatever]", "S3cretPassw0rd")
    assert any(e.detail.endswith("unknown field") for e in kit.safety.events)


def test_known_login_fields_are_still_allowed():
    kit = build_kit(ScenarioFoodSession(ScenarioFoodState()), task_id="t")
    kit.safety.check_fill("phone_input", "9000000001")
    kit.safety.check_fill("otp_input", "135790")
