from __future__ import annotations

import asyncio
import json

import pytest

from friday.connectors.browser.policy import NetworkPolicy, ResourceLimits
from friday.connectors.browser.port import LimitExceeded, NetworkBlocked
from friday.connectors.recorder import MASK_SELECTORS, StepRecorder
from friday.connectors.session import (
    BrowserSettings,
    FileVaultStore,
    LiveViewHttp,
    PauseWatcher,
    SessionClosed,
    SessionManager,
    SessionRefused,
    StorageVault,
    TakeoverError,
)

from .conftest import POLICY, make_cipher

STATE = {"cookies": [{"name": "sid", "value": "SECRETCOOKIE123", "domain": "fake.test"}],
         "origins": []}


# ---------------- vault
def test_vault_round_trip_encrypted_and_isolated(vault):
    vault.save("userA", "zomato", STATE)
    raw = json.dumps(vault._store.data)  # what is on disk
    assert "SECRETCOOKIE123" not in raw and "userA" not in raw and "zomato" not in raw
    assert vault.load("userA", "zomato") == STATE
    assert vault.load("userB", "zomato") is None
    assert vault.load("userA", "swiggy") is None


def test_vault_ciphertext_cannot_be_moved_to_another_user(vault):
    vault.save("userA", "zomato", STATE)
    store = vault._store
    (slot_a,) = store.data
    store.data[vault._slot("userB", "zomato")] = dict(store.data[slot_a])
    assert vault.load("userB", "zomato") is None  # AAD mismatch -> fail closed


def test_vault_expiry_and_disconnect(vault, clock):
    vault.save("u", "s", STATE)
    vault.save("u", "t", STATE)
    assert vault.disconnect_user("u") == 2 and vault.load("u", "s") is None
    vault.save("u", "s", STATE)
    clock.t += 31 * 86400
    assert vault.load("u", "s") is None


def test_vault_other_key_cannot_read(vault, clock):
    vault.save("u", "s", STATE)
    other = StorageVault(vault._store, make_cipher(), clock=clock)
    assert other.load("u", "s") is None


def test_file_store_is_private(tmp_path, clock):
    v = StorageVault(FileVaultStore(tmp_path / "v"), make_cipher(), clock=clock)
    v.save("u", "s", STATE)
    f = next((tmp_path / "v").glob("*.json"))
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert "SECRETCOOKIE123" not in f.read_text() and v.load("u", "s") == STATE


# ---------------- policy
def test_policy_default_deny_and_ssrf():
    p = NetworkPolicy.for_hosts({"a.test", "*.b.test"})
    assert p.check("https://a.test/x") is None and p.check("https://x.b.test/") is None
    assert p.check("https://evil.test/") and p.check("file:///etc/passwd")
    assert p.check("http://127.0.0.1/") and p.check("http://169.254.169.254/latest")
    assert p.check("http://localhost:80/") and p.check("https://b.test.evil.com/")
    assert NetworkPolicy().check("https://a.test/")  # empty list denies all
    assert p.check_resolved("a.test", ["10.0.0.5"])
    assert NetworkPolicy.for_hosts({"127.0.0.1"}).check("http://127.0.0.1:9/")  # loopback off
    assert NetworkPolicy.for_hosts({"127.0.0.1"}, allow_loopback=True).check(
        "http://127.0.0.1:9/") is None


# ---------------- manager
async def test_off_by_default_and_named_users(backend, vault):
    off = SessionManager(backend, vault, BrowserSettings())
    with pytest.raises(SessionRefused):
        await off.open("u", "s", "t1", policy=POLICY)
    s = BrowserSettings(enabled=True)  # enabled but nobody named
    assert not s.user_allowed("u")
    named = SessionManager(backend, vault, BrowserSettings(enabled=True, enabled_users="a, b"))
    assert (await named.open("a", "s", "t", policy=POLICY)).info.user_id == "a"
    with pytest.raises(SessionRefused):
        await named.open("c", "s", "t2", policy=POLICY)


async def test_fresh_context_and_login_restored_only_for_same_user(mgr, backend, vault):
    s = await mgr.open("A", "site", "t1", policy=POLICY)
    backend.sessions[0].set_cookie("sid", "A-LOGIN")
    await s.close()
    assert vault.load("A", "site")["cookies"][0]["value"] == "A-LOGIN"
    b = await mgr.open("B", "site", "t2", policy=POLICY)
    assert backend.sessions[1].cookies == [] and b.info.user_id == "B"  # B never sees A's
    await b.close()
    a2 = await mgr.open("A", "site", "t3", policy=POLICY)
    assert backend.sessions[2].cookies[0]["value"] == "A-LOGIN"
    assert backend.sessions[2] is not backend.sessions[0]
    await a2.close()


async def test_concurrency_caps(mgr):
    await mgr.open("A", "s", "t1", policy=POLICY)
    with pytest.raises(SessionRefused, match="per-user"):
        await mgr.open("A", "s", "t2", policy=POLICY)
    await mgr.open("B", "s", "t3", policy=POLICY)
    with pytest.raises(SessionRefused, match="global"):
        await mgr.open("C", "s", "t4", policy=POLICY)


async def test_racing_opens_cannot_exceed_cap(mgr):
    res = await asyncio.gather(*(mgr.open("A", "s", f"t{i}", policy=POLICY) for i in range(5)),
                               return_exceptions=True)
    assert sum(not isinstance(r, Exception) for r in res) == 1


async def test_network_allow_list_blocks_goto_and_is_audited(mgr):
    s = await mgr.open("A", "s", "t1", policy=POLICY)
    await s.goto("https://fake.test/menu")
    with pytest.raises(NetworkBlocked):
        await s.goto("https://evil.example/steal")
    with pytest.raises(NetworkBlocked):
        await s.goto("http://169.254.169.254/")
    ev = mgr.audit.entries(task_id="t1", event="network_blocked")
    assert len(ev) == 2


async def test_limits_trip_closes_session(mgr, backend):
    s = await mgr.open("A", "s", "t1", policy=POLICY,
                       limits=ResourceLimits(max_pages=1, max_downloads=0))
    # the backend reports a popup and a download attempt
    spec_counter = s._counter
    spec_counter.note_page()
    spec_counter.note_page()
    with pytest.raises(LimitExceeded):
        await s.goto("https://fake.test/")
    assert mgr.get("t1") is None and backend.sessions[0].closed
    assert mgr.vault.load("A", "s") is None  # no persist after a limit


async def test_download_limit(mgr):
    s = await mgr.open("A", "s", "t1", policy=POLICY)
    s._counter.note_download()
    with pytest.raises(LimitExceeded):
        await s.click("#x")


async def test_deadline_auto_cleanup(mgr, backend):
    await mgr.open("A", "s", "t1", policy=POLICY, limits=ResourceLimits(max_seconds=0.05))
    await asyncio.sleep(0.15)
    assert mgr.get("t1") is None and backend.sessions[0].closed
    assert mgr.audit.entries(event="session_close")[0]["reason"] == "deadline"


async def test_context_manager_closes_on_error(mgr, backend):
    with pytest.raises(RuntimeError):
        async with mgr.session("A", "s", "t1", policy=POLICY):
            raise RuntimeError("boom")
    assert backend.sessions[0].closed and not mgr.active()


async def test_closed_session_rejects_calls(mgr):
    s = await mgr.open("A", "s", "t1", policy=POLICY)
    await s.close()
    with pytest.raises(SessionClosed):
        await s.goto("https://fake.test/")


async def test_recorder_hook_masks_and_hides_values(mgr):
    rec = StepRecorder()
    s = await mgr.open("A", "s", "t1", policy=POLICY, recorder=rec)
    await s.goto("https://fake.test/login")
    await s.fill("input[name=otp]", "246810")
    notes = " ".join(st.note for st in rec.steps)
    assert "246810" not in notes and rec.steps[-1].screenshot
    audit = json.dumps(mgr.audit.entries(task_id="t1"))
    assert "246810" not in audit


async def test_audit_never_holds_secrets(mgr):
    mgr.audit.record("x", task_id="t", password="hunter2", note="otp is 123456 call 9876543210")
    dump = json.dumps(mgr.audit.entries(task_id="t"))
    assert "hunter2" not in dump and "123456" not in dump and "9876543210" not in dump


# ---------------- kill switch
async def test_kill_all_task_user_and_pause(mgr, backend, live):
    await mgr.open("A", "s", "t1", policy=POLICY)
    await mgr.open("B", "s", "t2", policy=POLICY)
    token = live.create_link("t1")
    assert await mgr.kill_task("t1") and mgr.get("t1") is None
    assert live.open_view(token) is None  # link revoked with the task
    assert await mgr.kill_user("B") == 1
    assert not mgr.active() and all(s.closed for s in backend.sessions)
    assert mgr.vault.load("B", "s") is None  # kill never writes the vault


async def test_pause_watcher_closes_everything_and_blocks_opens(backend, vault, settings):
    paused = {"v": False}
    m = SessionManager(backend, vault, settings, paused=lambda: paused["v"])
    await m.open("A", "s", "t1", policy=POLICY)
    w = PauseWatcher(m, lambda: paused["v"], interval=0.02)
    assert await w.check_once() == 0
    paused["v"] = True
    assert await w.check_once() == 1 and not m.active()
    with pytest.raises(SessionRefused, match="paused"):
        await m.open("A", "s", "t2", policy=POLICY)


async def test_pause_watcher_loop(backend, vault, settings):
    paused = {"v": False}
    m = SessionManager(backend, vault, settings)
    await m.open("A", "s", "t1", policy=POLICY)
    w = PauseWatcher(m, lambda: paused["v"], interval=0.02)
    w.start()
    paused["v"] = True
    await asyncio.sleep(0.1)
    await w.stop()
    assert not m.active()


# ---------------- live view + takeover
async def test_link_is_single_use_and_expires(mgr, live, clock):
    await mgr.open("A", "s", "t1", policy=POLICY)
    tok = live.create_link("t1")
    vh = live.open_view(tok)
    assert vh and live.open_view(tok) is None
    tok2 = live.create_link("t1", ttl=60)
    clock.t += 61
    assert live.open_view(tok2) is None
    tok3 = live.create_link("t1")
    vh3 = live.open_view(tok3)
    clock.t += 10_000
    assert await live.frame(vh3.view_id) is None  # view expired


async def test_frames_are_masked_and_rate_limited(mgr, live, backend, clock):
    await mgr.open("A", "s", "t1", policy=POLICY)
    v = live.open_view(live.create_link("t1"))
    png = await live.frame(v.view_id)
    assert png.startswith(b"\x89PNG")
    assert backend.sessions[0].screenshot_masks[-1] == MASK_SELECTORS
    assert "input[type=password]" in MASK_SELECTORS
    await live.frame(v.view_id)
    assert len(backend.sessions[0].screenshot_masks) == 1  # cached inside the interval
    clock.t += 5
    await live.frame(v.view_id)
    assert len(backend.sessions[0].screenshot_masks) == 2


async def test_takeover_pauses_friday_and_give_back_resumes(mgr, live, backend):
    s = await mgr.open("A", "s", "t1", policy=POLICY)
    v = live.open_view(live.create_link("t1"))
    with pytest.raises(TakeoverError):
        await live.send_input(v.view_id, {"kind": "click", "x": 1, "y": 1})  # not in takeover
    assert await live.start_takeover(v.view_id) and s.takeover_active
    waiter = asyncio.create_task(s.click("#go"))
    await asyncio.sleep(0.05)
    assert not waiter.done()  # Friday is paused
    await live.send_input(v.view_id, {"kind": "type", "text": "MySecretPass1"})
    await live.send_input(v.view_id, {"kind": "click", "x": 10, "y": 10})
    await live.send_input(v.view_id, {"kind": "key", "key": "Enter"})
    assert not waiter.done()
    assert await live.give_back(v.view_id)
    await asyncio.wait_for(waiter, 1)
    assert ("click", "#go") in backend.sessions[0].steps
    dump = json.dumps(mgr.audit.entries(task_id="t1"))
    assert "MySecretPass1" not in dump and '"input_events": 3' in dump
    assert ("type", 13) in backend.sessions[0].inputs  # content never even kept


async def test_takeover_rejects_bad_input(mgr, live):
    await mgr.open("A", "s", "t1", policy=POLICY)
    v = live.open_view(live.create_link("t1"))
    await live.start_takeover(v.view_id)
    for bad in ({"kind": "click", "x": -1, "y": 0}, {"kind": "click", "x": 5000, "y": 0},
                {"kind": "key", "key": "Control+a"}, {"kind": "type", "text": "x" * 500},
                {"kind": "eval", "js": "1"}, {"kind": "click", "x": "1", "y": 2}):
        with pytest.raises(TakeoverError):
            await live.send_input(v.view_id, bad)


async def test_takeover_disabled_link(mgr, live):
    await mgr.open("A", "s", "t1", policy=POLICY)
    v = live.open_view(live.create_link("t1", allow_takeover=False))
    assert not await live.start_takeover(v.view_id)


async def test_takeover_timeout_closes_without_saving(backend, vault):
    m = SessionManager(backend, vault, BrowserSettings(
        enabled=True, enabled_users="*", takeover_max_seconds=0.05))
    lv = __import__("friday.connectors.session", fromlist=["x"]).LiveViewService(m)
    await m.open("A", "s", "t1", policy=POLICY)
    v = lv.open_view(lv.create_link("t1"))
    await lv.start_takeover(v.view_id)
    await asyncio.sleep(0.2)
    assert m.get("t1") is None and vault.load("A", "s") is None


async def test_http_flow(mgr, live):
    await mgr.open("A", "s", "t1", policy=POLICY)
    http = LiveViewHttp(live)
    tok = live.create_link("t1")
    page = await http.handle("GET", f"/live/{tok}")
    assert page.status == 200 and b"Take over" in page.body
    assert "Content-Security-Policy" in page.headers and page.headers["Cache-Control"] == "no-store"
    assert (await http.handle("GET", f"/live/{tok}")).status == 404  # single use
    view = page.body.decode().split('const V="')[1].split('"')[0]
    assert (await http.handle("GET", f"/live/f/{view}")).content_type == "image/png"
    assert (await http.handle("POST", f"/live/takeover/{view}")).status == 200
    r = await http.handle("POST", f"/live/i/{view}", b'{"kind":"key","key":"Tab"}')
    assert r.status == 200
    assert (await http.handle("POST", f"/live/i/{view}", b"nope")).status == 400
    bad_key = await http.handle("POST", f"/live/i/{view}", b'{"kind":"key","key":"F12"}')
    assert bad_key.status == 400
    assert (await http.handle("POST", f"/live/giveback/{view}")).status == 200
    assert (await http.handle("GET", "/live/f/guess")).status == 404
    await mgr.kill_all()
    assert (await http.handle("GET", f"/live/f/{view}")).status == 404
