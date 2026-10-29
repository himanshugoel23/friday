# ruff: noqa: E501
"""Stores, the sitemcp-runtime provider (limits, robots, blocks), observation size, housekeeping tick. No network, no Chromium."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from friday.browser_agent import pwpage
from friday.browser_agent.errors import ActionFailed, Blocked, Busy
from friday.browser_agent.jobapply import JobApplyService, JobLedger
from friday.browser_agent.observe import MAX_ELEMENTS, SYSTEM, render_page
from friday.browser_agent.stores import FileRefs, JsonRunStore, ProofStore
from friday.browser_agent.types import Element, PageSnapshot, RunSpec, RunState, Status
from friday.core.clock import FakeClock
from friday.sitemcp.guard import MemoryGuard, RobotsPolicy
from friday.sitemcp.runtime import SessionPool
from tests.browser_agent.fakes import A, TickClock, make_rig, spec
from tests.browser_agent.sites import JOB, job_site


# ----------------------------------------------------------------------------- stores
def test_run_store_is_atomic_and_erasable(tmp_path):
    st = JsonRunStore(tmp_path)
    s = RunState(id="a" * 16, user_id="u1", spec=RunSpec(goal="g", allowed_domains=["x.com"]), updated_at="2026-10-29T10:00:00+00:00")
    st.save(s)
    assert st.load("a" * 16).spec.goal == "g" and not list((tmp_path / "runs").glob("*.tmp"))
    assert st.active_for("u1").id == "a" * 16 and [x.id for x in st.list_open()] == ["a" * 16]
    assert st.load("../../etc/passwd") is None  # run ids are strict hex
    assert st.delete_user("u1") == 1 and st.list_open() == []


def test_proofs_are_small_expire_and_never_keep_the_query_string(tmp_path):
    clock = FakeClock()
    ps = ProofStore(tmp_path, ttl_days=14, clock=clock)
    pid, path = ps.save("u1", "r1", "clicked Submit", "https://jobs.example.com/done?token=SECRET123#x", b"\xff\xd8\xff" + b"x" * 100)
    meta = ps.list_for("u1")[0]
    assert meta["where"] == "jobs.example.com/done" and "SECRET123" not in json.dumps(meta) and path.endswith(".jpg")
    big_id, big_path = ps.save("u1", "r1", "huge", "https://jobs.example.com/", b"\xff\xd8\xff" + b"x" * 900_000)
    assert big_path.endswith(".json") and [m for m in ps.list_for("u1") if m["id"] == big_id][0]["image"] == ""  # too big: meta only
    clock._now += timedelta(days=15)
    assert ps.purge() == 2 and ps.list_for("u1") == []


def test_file_refs_are_user_private_typed_and_never_free_paths(tmp_path):
    src = tmp_path / "cv.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    fr = FileRefs(tmp_path / "agent")
    assert fr.store("u1", "resume", src) and fr.resolve("u1", "resume").endswith("resume.pdf")
    assert fr.resolve("u2", "resume") is None  # another user's file is invisible
    for bad in ("../resume", "/etc/passwd", "RESUME", "a" * 40, ""):
        assert fr.resolve("u1", bad) is None
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    assert not fr.store("u1", "tool", exe)
    assert fr.names("u1") == ["resume"] and fr.delete_user("u1") == 1 and fr.resolve("u1", "resume") is None


# ----------------------------------------------------------------------------- observation
def test_observation_is_compact_text_not_html_and_bounded():
    els = [Element(id=f"e{i}", role="textbox", name=f"Field number {i} with a fairly long label " * 3, required=True) for i in range(1, 201)]
    snap = PageSnapshot(url="https://jobs.example.com/apply?session=abc", title="Apply", text="word " * 2000, elements=els)
    out = render_page(snap)
    assert len(out) < 9000 and f"e{MAX_ELEMENTS}" in out and f"e{MAX_ELEMENTS + 1} " not in out and "more elements not shown" in out
    assert "<html" not in out.lower() and "session=abc" not in out  # no query string, no markup
    assert "page_untrusted" in out and "page_untrusted" in SYSTEM


# ----------------------------------------------------------------------------- provider over the sitemcp runtime
class StubInner:
    def __init__(self) -> None:
        self.last_status: int | None = 200
        self.urls: list[str] = []
        self.clicked: list[str] = []
        self._page = SimpleNamespace(url="about:blank", evaluate=self._eval, locator=lambda s: s)

    async def _eval(self, js: str):  # noqa: ANN202
        return {"title": "T", "text": "hello", "captcha": False, "elements": [{"id": "e1", "role": "button", "name": "Go", "type": "", "autocomplete": "", "placeholder": "", "value": "", "required": False, "checked": None, "disabled": False, "options": [], "group": "", "href_host": "", "submit": False}]}

    async def goto(self, url: str) -> None:
        self.urls.append(url)
        self._page.url = url

    async def click(self, sel: str) -> None:
        self.clicked.append(sel)

    async def fill(self, sel: str, value: str) -> None:
        pass

    async def text(self, sel: str) -> str:
        return "ok page"

    async def query_all(self, sel, fields=None):  # noqa: ANN001, ANN202
        return []

    async def wait_for(self, sel, t=0):  # noqa: ANN001, ANN202
        pass

    async def screenshot(self, m=()):  # noqa: ANN001, ANN202
        return b"png"

    async def storage_state(self) -> dict:
        return {}

    def current_url(self) -> str:
        return self._page.url

    async def close(self) -> None:
        pass


class StubFactory:
    def __init__(self) -> None:
        self.inner = StubInner()
        self.opened = 0

    async def open(self, kb, state):  # noqa: ANN001, ANN201
        self.opened += 1
        return self.inner

    async def aclose(self) -> None:
        pass


def provider(*, mem=4000.0, robots=None):  # noqa: ANN001, ANN201
    f = StubFactory()
    pool = SessionPool(f, robots=robots, memory=MemoryGuard(250.0, reader=lambda: mem), max_sessions=2, idle_s=240)
    return pwpage.PoolPageProvider(pool, min_interval_s=0.0, per_user_s=0.0, max_wait_s=1.0), f


async def test_provider_snapshots_and_keeps_the_allow_list_and_payment_guards():
    prov, f = provider()
    sp = spec(domains=["jobs.example.com"])
    async with prov.session("u1", sp, ["jobs.example.com"]) as page:
        await page.goto("https://jobs.example.com/apply")
        snap = await page.snapshot()
        assert snap.url == "https://jobs.example.com/apply" and snap.elements[0].id == "e1" and snap.http_status == 200
        await page.click("e1")
        assert f.inner.clicked == ['[data-fa-id="e1"]']
        with pytest.raises(ActionFailed):
            await page.goto("https://evil.example.net/")  # outside the domains: refused by the shared SafeSession
        with pytest.raises(ActionFailed):
            await page.goto("https://jobs.example.com/payment/card")
        with pytest.raises(ActionFailed):
            await page.click("e1; drop")  # element ids are strict
    assert f.inner.urls == ["https://jobs.example.com/apply"]


async def test_provider_maps_low_memory_robots_and_challenges():
    prov, _ = provider(mem=100.0)
    with pytest.raises(Busy):
        async with prov.session("u1", spec(), ["jobs.example.com"]):
            pass

    async def fetch(url: str):  # noqa: ANN202
        return 200, "User-agent: *\nDisallow: /apply"

    prov2, _ = provider(robots=RobotsPolicy(fetch=fetch))
    with pytest.raises(Blocked) as e:
        async with prov2.session("u1", spec(), ["jobs.example.com"]) as page:
            await page.goto("https://jobs.example.com/apply")
    assert e.value.reason == "robots"
    prov3, f3 = provider()
    f3.inner.last_status = 403
    with pytest.raises(Blocked) as e2:
        async with prov3.session("u1", spec(), ["jobs.example.com"]) as page:
            await page.goto("https://jobs.example.com/")
    assert e2.value.reason == "http_403"


async def test_session_cap_is_shared_and_reopen_closes_the_context():
    prov, f = provider()
    sp = spec()
    async with prov.session("u1", sp, ["jobs.example.com"]):
        pass
    async with prov.session("u1", sp, ["jobs.example.com"]):
        pass
    assert f.opened == 1  # the idle context is reused (RAM: one Chromium context per user)
    await prov.reopen("u1", sp)
    async with prov.session("u1", sp, ["jobs.example.com", "ats.example.net"]):
        pass
    assert f.opened == 2


def test_playwright_snapshot_script_is_present_and_playwright_absent_is_fine():
    assert "data-fa-id" in pwpage.SNAPSHOT_JS and "recaptcha" in pwpage.SNAPSHOT_JS
    assert pwpage.sel("e12") == '[data-fa-id="e12"]'
    with pytest.raises(ActionFailed):
        pwpage.sel("button[type=submit]")


# ----------------------------------------------------------------------------- housekeeping
class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def notify_user(self, user_id, text, buttons=(), task_id=None):  # noqa: ANN001, ANN201
        self.sent.append((user_id, text))


class FakePipeline:
    def __init__(self, clock) -> None:  # noqa: ANN001
        self.clock, self.notifier = clock, FakeNotifier()
        self.repos = SimpleNamespace(users=SimpleNamespace(get=self._get))

    async def _get(self, uid):  # noqa: ANN001, ANN202
        return SimpleNamespace(id=uid)

    async def _reply_lang(self, user):  # noqa: ANN001, ANN202
        return "en"

    async def audit(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
        pass


async def test_tick_closes_timed_out_questions_resumes_busy_runs_and_sends_one_evening_summary(tmp_path):
    from friday.browser_agent.gateway import BrowserAgentGateway

    rig = make_rig(job_site(), [A("click", target="e1"), A("fill", target="e2", value_source="fact:email"), A("click", target="e5"), A("finish", result="resumed")], start=JOB, busy="low_memory")
    pipe = FakePipeline(rig.clock)
    js = JobApplyService(rig.agent, rig.facts, JobLedger(tmp_path / "l.jsonl"), rig.files, now=rig.clock.now)
    gw = BrowserAgentGateway(pipe, rig.agent, jobs=js, settings=SimpleNamespace(), proofs=None)
    gw.sync = True
    first = await rig.agent.start("u1", spec(start_url=JOB))
    assert first.status == Status.BUSY
    rig.provider.busy = ""
    await gw.tick()  # the busy run is picked up again, runs to the question, and the user gets it
    assert any("Email" in t for _, t in pipe.notifier.sent) and rig.store.load(first.run_id).status == Status.WAITING_USER
    rig.clock.advance(hours=25)
    pipe.notifier.sent.clear()
    await gw.tick()
    assert any("Nothing was submitted" in t for _, t in pipe.notifier.sent) and rig.store.load(first.run_id).status == Status.EXPIRED
    # evening summary: only after 20:00 IST (14:30 UTC), once per day, only with an application
    js.ledger.record("u1", now=rig.clock.now(), host="jobs.example.com", where="jobs.example.com/done", what="Backend Engineer at Acme", proof_id="p1", status="applied")
    pipe.notifier.sent.clear()
    rig.clock.t = rig.clock.t.replace(hour=10, minute=0)
    await gw.tick()
    assert pipe.notifier.sent == []  # too early
    rig.clock.t = rig.clock.t.replace(hour=15, minute=0)
    await gw.tick()
    await gw.tick()
    assert len([1 for _, t in pipe.notifier.sent if "Your applications today" in t]) == 1


def test_tickclock_is_a_core_clock():
    assert TickClock().now().tzinfo is not None
