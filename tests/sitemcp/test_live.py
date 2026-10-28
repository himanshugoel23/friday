# ruff: noqa: E501
"""The anonymous live run, drift probe, scheduler, ops-status routes, doctor lines and CLI: all on fakes, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.opsstatus import ops_status_router
from friday.core.config import Settings
from friday.sitemcp import doctor
from friday.sitemcp.fakes.htmlsession import HtmlFakeFactory
from friday.sitemcp.fakes.store import FakeStore, fake_kb
from friday.sitemcp.guard import MemoryGuard
from friday.sitemcp.live import render_report, run_live
from friday.sitemcp.probe import render, run_drift
from friday.sitemcp.probestore import ProbeStore, safe_site
from friday.sitemcp.scheduler import ProbeJob

PNG = b"\x89PNG"


@pytest.fixture
def store_env(tmp_path):
    st = FakeStore("testid")
    kb = fake_kb("zepto", st.start(), "testid")
    yield st, kb, ProbeStore(tmp_path / "sitemcp")
    st.stop()


async def test_live_run_ok_records_steps_counts_and_closes_the_browser(store_env):
    st, kb, ps = store_env
    f = HtmlFakeFactory()
    r = await run_live(kb, f, ps, query="atta", pincode="560034")
    assert r["overall"] == "ok" and r["items_found"] == 3 and r["priced"] == 3
    assert [s["step"] for s in r["steps"]] == ["home+set_location", "search", "parse_prices"]
    assert all(s["status"] == "ok" and s["ms"] >= 0 for s in r["steps"])
    assert r["screenshot"] and ps.shot("zepto")
    assert f.live() == 0  # browser closed right after
    assert r["sample"][0]["title"] and "phone" not in json.dumps(r).lower()
    assert ps.live_all()["zepto"]["overall"] == "ok"


@pytest.mark.parametrize("mode,reason", [("challenge", "challenge"), ("denied", "http_403")])
async def test_live_run_blocked_stops_and_keeps_a_screenshot_of_the_public_page(store_env, mode, reason):
    st, kb, ps = store_env
    st.mode = mode
    r = await run_live(kb, HtmlFakeFactory(), ps, query="atta", pincode="560034")
    assert r["overall"] == "blocked" and len(r["steps"]) == 1 and r["steps"][0]["detail"] == reason
    assert r["screenshot"] and ps.shot("zepto")
    assert len(st.hits) <= 3  # no retry loop


async def test_live_run_location_not_found_and_changed(store_env):
    st, kb, ps = store_env
    assert (await run_live(kb, HtmlFakeFactory(), ps, query="atta", pincode="999999"))["overall"] == "location_not_found"
    kb2 = json.loads(json.dumps(kb))
    kb2["search"]["row"] = ".gone"  # the site changed its markup
    r = await run_live(kb2, HtmlFakeFactory(), ps, query="atta", pincode="560034")
    assert r["overall"] == "changed" and r["steps"][1]["step"] == "search"
    kb3 = json.loads(json.dumps(kb))
    kb3["location"]["input"] = ".gone"
    assert (await run_live(kb3, HtmlFakeFactory(), ps, query="atta", pincode="560034"))["overall"] == "changed"


async def test_live_run_low_memory_and_missing_browser(store_env):
    st, kb, ps = store_env
    r = await run_live(kb, HtmlFakeFactory(), ps, query="atta", pincode="560034", memory=MemoryGuard(250, lambda: 10.0))
    assert r["overall"] == "unavailable" and r["steps"][0]["detail"] == "low_memory"
    assert st.hits == []

    class NoBrowser(HtmlFakeFactory):
        async def open(self, kb, state):
            raise RuntimeError("x")

    assert (await run_live(kb, NoBrowser(), ps, query="atta", pincode="560034"))["overall"] == "browser_unavailable"


async def test_report_text_has_statuses_and_no_personal_data(store_env):
    st, kb, ps = store_env
    await run_live(kb, HtmlFakeFactory(), ps, query="atta", pincode="560034")
    st.mode = "challenge"
    await run_live({**kb, "site": "blinkit"}, HtmlFakeFactory(), ps, query="atta", pincode="560034")
    txt = render_report(ps)
    assert "zepto: overall=ok" in txt and "blinkit: overall=blocked" in txt and "/ops-status/<token>/shot/zepto" in txt
    assert "search: ok" in txt and "kb v1 unverified" in txt
    assert render_report(ProbeStore(ps.root / "none")) == "no site MCP probe has run yet\n"


async def test_drift_probe_counts_only(store_env):
    st, kb, ps = store_env
    rep = await run_drift(kb, HtmlFakeFactory(), ps)
    assert rep["status"] == "ok" and rep["matched"] == rep["checked"] >= 3
    kb2 = json.loads(json.dumps(kb))
    kb2["probe"]["public_pages"][0]["selectors"].append(".vanished")
    rep = await run_drift(kb2, HtmlFakeFactory(), ps)
    assert rep["status"] == "drift" and rep["missing"] == 1 and "1 missing" in render(rep)
    st.mode = "challenge"
    assert (await run_drift(kb, HtmlFakeFactory(), ps))["status"] == "blocked"
    assert (await run_drift(kb, HtmlFakeFactory(), ps, memory=MemoryGuard(250, lambda: 1.0)))["status"] == "skipped_low_memory"
    assert ps.drift_all()["zepto"]["status"] == "skipped_low_memory"


# ------------------------------------------------------------------ scheduler
def _settings(tmp_path, **kw):
    return SimpleNamespace(site_mcp_sites=["zepto", "blinkit"], site_mcp_probe_pincode="560034", site_mcp_probe_query="atta",
                           site_mcp_min_free_mb=250, site_mcp_probe_interval_h=12.0, **kw)


async def test_scheduler_records_browser_unavailable_when_prerequisites_are_missing(tmp_path):
    ps = ProbeStore(tmp_path)
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)

    out = await ProbeJob(_settings(tmp_path), ps, available=lambda: False, sleep=sleep).run_all()
    assert [r["overall"] for r in out] == ["browser_unavailable"] * 2
    assert "friday doctor" in ps.live_all()["zepto"]["steps"][0]["detail"]
    assert sleeps == [30.0]  # one gap between the two sites


async def test_scheduler_skips_on_low_memory_and_loop_waits_then_repeats(tmp_path):
    ps = ProbeStore(tmp_path)
    sleeps: list[float] = []

    class Stop(Exception):
        pass

    async def sleep(s):
        sleeps.append(s)
        if len(sleeps) > 4:
            raise Stop

    job = ProbeJob(_settings(tmp_path), ps, available=lambda: True, sleep=sleep, memory=MemoryGuard(250, lambda: 5.0))
    with pytest.raises(Stop):
        await job.loop()
    assert sleeps[0] == 90.0 and 12 * 3600 in sleeps
    assert ps.live_all()["blinkit"]["overall"] == "skipped_low_memory"


async def test_scheduler_runs_a_real_probe_path_on_fakes(store_env, tmp_path):
    st, kb, ps = store_env
    import friday.sitemcp.scheduler as sch

    sch.load_knowledge = lambda: {"zepto": kb}  # type: ignore[assignment]
    try:
        async def nosleep(s):
            return None

        out = await ProbeJob(_settings(tmp_path), ps, factory_maker=HtmlFakeFactory, available=lambda: True, sleep=nosleep,
                             memory=MemoryGuard(1, lambda: 999.0)).run_all()
    finally:
        from friday.sitemcp.knowledge import load_knowledge

        sch.load_knowledge = load_knowledge  # type: ignore[assignment]
    assert out[0]["overall"] in ("ok", "blocked")  # pincode setting 560034 is served by the fake store
    assert out[0]["overall"] == "ok"


# ------------------------------------------------------------------ ops-status routes
def _client(enabled: bool, tmp_path):
    app = FastAPI()
    app.state.container = SimpleNamespace(settings=SimpleNamespace(site_mcp_probe_enabled=enabled, site_mcp_dir=str(tmp_path / "sitemcp")))
    app.include_router(ops_status_router(), prefix="/ops-status")
    return TestClient(app)


def _seed(tmp_path):
    ps = ProbeStore(tmp_path / "sitemcp")
    r = {"site": "zepto", "kb_version": 1, "kb_status": "unverified", "finished_at": "2026-10-29T10:00:00", "overall": "blocked", "items_found": 0,
         "priced": 0, "sample": [], "screenshot": True, "steps": [{"step": "home+set_location", "status": "blocked", "ms": 1200, "detail": "challenge"}]}
    ps.save_live(r, PNG + b"data")


def test_probe_routes_need_token_and_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", "t" * 20)
    _seed(tmp_path)
    tok = "t" * 20
    on, off = _client(True, tmp_path), _client(False, tmp_path)
    assert on.get(f"/ops-status/{'x' * 20}/probe").status_code == 404
    assert on.get(f"/ops-status/{'x' * 20}/shot/zepto").status_code == 404
    r = on.get(f"/ops-status/{tok}/probe")
    assert r.status_code == 200 and "zepto: overall=blocked" in r.text and "challenge" in r.text
    s = on.get(f"/ops-status/{tok}/shot/zepto")
    assert s.status_code == 200 and s.headers["content-type"] == "image/png" and s.content.startswith(PNG)
    assert on.get(f"/ops-status/{tok}/shot/nosuch").status_code == 404
    assert on.get(f"/ops-status/{tok}/shot/..%2Fx").status_code == 404
    assert off.get(f"/ops-status/{tok}/probe").status_code == 404 and off.get(f"/ops-status/{tok}/shot/zepto").status_code == 404


def test_only_safe_site_names_reach_the_filesystem(tmp_path):
    ps = ProbeStore(tmp_path)
    assert safe_site("zepto") == "zepto" and safe_site("../etc") is None and safe_site("") is None and safe_site("A") is None
    assert ps.shot("../../etc/passwd") is None


# ------------------------------------------------------------------ doctor
def test_doctor_warns_with_exact_install_commands_when_prerequisites_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "playwright_installed", lambda: False)
    monkeypatch.setattr(doctor, "find_chromium", lambda: None)
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    s = SimpleNamespace(site_mcp_enabled=False, site_mcp_probe_enabled=True, site_mcp_min_free_mb=250, site_mcp_dir=str(tmp_path))
    lines = doctor.check(s, mem_reader=lambda: 600.0)
    warns = [m for lv, m in lines if lv == "warn"]
    text = " ".join(warns)
    assert "playwright python package MISSING" in text and "Chromium binary MISSING" in text and "Xvfb MISSING" in text
    for cmd in ("apt-get install -y xvfb", "uv sync --extra browser", "playwright install chromium --with-deps"):
        assert cmd in text
    off = doctor.check(SimpleNamespace(site_mcp_enabled=False, site_mcp_probe_enabled=False, site_mcp_min_free_mb=250, site_mcp_dir=str(tmp_path)), mem_reader=lambda: 600.0)
    assert not [1 for lv, m in off if lv == "warn" and "MISSING" in m]  # silent while both switches are off


def test_doctor_shows_last_probe_and_low_ram(tmp_path, monkeypatch):
    _seed(tmp_path)
    s = SimpleNamespace(site_mcp_enabled=True, site_mcp_probe_enabled=True, site_mcp_min_free_mb=250, site_mcp_dir=str(tmp_path / "sitemcp"))
    lines = doctor.check(s, mem_reader=lambda: 100.0, now=datetime(2026, 10, 29, 12, tzinfo=UTC))
    msgs = [m for _, m in lines]
    assert any("last live probe zepto: blocked" in m and "2 h ago" in m for m in msgs)
    assert ("warn", "site MCP: 100 MB RAM available (new browser sessions are refused below 250 MB; one Chromium needs about 300-500 MB)") in lines


async def test_doctor_section_includes_site_mcp_lines():
    from friday.ops.doctor import run_sections

    secs = await run_sections(Settings(_env_file=None), offline=True, only="browser")
    assert any("site MCP" in c.message for c in secs[0].checks)


# ------------------------------------------------------------------ cli + names
def test_cli_tools_and_report_are_offline(tmp_path, capsys):
    from friday.cli import main

    assert main(["sitemcp", "tools"]) == 0
    assert capsys.readouterr().out.split() == ["set_location", "search_products", "get_product", "add_to_cart", "view_cart", "checkout_preview",
                                              "login_start", "login_status", "logout"]
    assert main(["sitemcp", "report", "--out", str(tmp_path)]) == 0
    assert "no site MCP probe has run yet" in capsys.readouterr().out


def test_cli_live_stops_with_the_install_commands_when_playwright_is_missing(capsys, monkeypatch):
    from friday.cli import main
    from friday.sitemcp import chromium

    monkeypatch.setattr(chromium.SharedChromium, "available", staticmethod(lambda: False))
    assert main(["sitemcp", "live", "zepto"]) == 3
    assert "install chromium --with-deps" in capsys.readouterr().out
    assert main(["sitemcp", "live", "nosuch"]) == 2


def test_enable_web_test_lists_the_new_switch_names():
    text = Path(__file__).resolve().parents[2].joinpath("deploy", "enable-web-test.sh").read_text()
    assert "FRIDAY_SITE_MCP_ENABLED" in text and "FRIDAY_SITE_MCP_PROBE_ENABLED" in text


# ------------------------------------------------------------------ real Playwright (skips cleanly when it is not installed)
async def test_real_chromium_runs_the_live_probe_against_the_local_fake_store(tmp_path, monkeypatch):
    from friday.sitemcp.chromium import SharedChromium

    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(k, raising=False)  # a sandbox agent proxy must not intercept the loopback fake store

    import os

    if os.environ.get("FRIDAY_TEST_REAL_CHROMIUM") != "1":
        pytest.skip("opt-in: set FRIDAY_TEST_REAL_CHROMIUM=1 (loopback to the fake store fails in some sandboxes)")
    if not SharedChromium.available():
        pytest.skip("Playwright or Chromium not installed here")
    st = FakeStore("testid")
    kb = fake_kb("zepto", st.start(), "testid")
    try:
        r = await run_live(kb, SharedChromium(), ProbeStore(tmp_path), query="atta", pincode="560034")
    finally:
        st.stop()
    assert r["overall"] == "ok" and r["items_found"] == 3
