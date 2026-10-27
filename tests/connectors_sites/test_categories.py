# ruff: noqa: E501
"""Category loader, planner phrases for every use case, the settings gate and the link hand-over."""

from __future__ import annotations

import sys
import types
from datetime import date

import pytest

from friday.connectors import catalog
from friday.connectors.flow import BrowserFlow
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.sites import categories, sim
from friday.connectors.sites.planner import CONNECTORS, LlmPlanner, RulePlanner, classify

TODAY = date(2026, 10, 27)


@pytest.fixture(autouse=True)
def _fresh_loader():
    categories.reload()
    yield
    categories.reload()


async def plan(text):
    return await RulePlanner(today=lambda: TODAY).plan(text)


@pytest.mark.parametrize("text,connector,slots", [
    ("Blinkit se doodh mangao", "blinkit.grocery", {"items": [{"query": "doodh", "qty": 1}]}),
    ("2 doodh aur 1 bread zepto se mangao", "zepto.grocery",
     {"items": [{"query": "doodh", "qty": 2}, {"query": "bread", "qty": 1}]}),
    ("Uber book karo airport", "uber.ride", {"drop": "airport"}),
    ("ola cab to station", "ola.ride", {"drop": "station"}),
    ("Delhi se Jaipur bus", None, {"origin": "Delhi", "dest": "Jaipur"}),
    ("redbus se Delhi se Jaipur bus kal", "redbus.bus", {"origin": "Delhi", "dest": "Jaipur", "date": "2026-10-28"}),
    ("Goa mein hotel", None, {"city": "Goa"}),
    ("hotel in Jaipur for 2 nights 2 guests", None, {"city": "Jaipur", "nights": 2, "guests": 2}),
    ("agoda hotel in Goa", "agoda.hotel", {"city": "Goa"}),
    ("Delhi to Mumbai flight kal", None, {"origin": "Delhi", "dest": "Mumbai", "date": "2026-10-28"}),
    ("Book train from Pune to Goa on 5 nov", "irctc.train", {"origin": "Pune", "dest": "Goa", "date": "2026-11-05"}),
    ("Amazon se headphones kharidna", "amazon.shopping", {"query": "headphones"}),
    ("Swiggy se biryani mangao", "swiggy.food", {}),
    ("order 2 margherita from Domino's", "zomato.food", {"items": [{"query": "margherita", "qty": 2}], "restaurant": "Domino's"}),
    ("Book 2 tickets for Pixel Heist at 7 pm", "bookmyshow.movie", {"seats": 2, "title": "Pixel Heist"}),
])
async def test_phrases_pick_a_catalog_site_and_use_case(text, connector, slots):
    p = await plan(text)
    assert p.connector is not None and p.connector in CONNECTORS
    if connector:
        assert p.connector == connector
    site, use_case = p.connector.split(".")
    assert catalog.site(site) is not None and use_case in catalog.site(site).use_cases
    for k, v in slots.items():
        assert p.slots.get(k) == v, (k, p.slots)
    assert p.steps and p.site == site and p.use_case == use_case


@pytest.mark.parametrize("text", ["what is the weather", "hello", "how are you", "show me the menu",
                                  "mera room saaf hai", "I like pizza", "tum kya kar sakti ho"])
async def test_ordinary_chat_is_not_claimed(text):
    from friday.connectors.flow import _quick

    assert _quick(text) is None


@pytest.mark.parametrize("text", ["Blinkit se doodh mangao", "Uber book karo airport",
                                  "Delhi se Jaipur bus", "Goa mein hotel", "order 2 margherita from Domino's"])
def test_requests_are_claimed(text):
    from friday.connectors.flow import _quick

    assert _quick(text) is not None


def test_every_use_case_has_a_default_site_in_the_catalog():
    from friday.connectors.sites.planner import DEFAULT_SITES

    for use_case, keys in DEFAULT_SITES.items():
        for k in keys:
            assert use_case in catalog.site(k).use_cases, (k, use_case)


def test_unnamed_site_prefers_one_that_has_an_adapter(monkeypatch):
    monkeypatch.setattr(categories, "has_adapter", lambda s, u: (s, u) == ("abhibus", "bus"))
    assert classify("Delhi se Jaipur bus") == ("abhibus", "bus")


async def test_llm_planner_accepts_new_use_cases_and_drops_foreign_slots():
    from tests.connectors_sites.test_agents import FakeLLM

    p = await LlmPlanner(FakeLLM({"connector": "uber.ride", "slots": {"drop": "airport", "pay": "now"}})).plan("x")
    assert p.connector == "uber.ride" and p.slots == {"drop": "airport"}


# ---------------------------------------------------------------- loader
def _fake_package(monkeypatch, name, adapters, fakes=None):
    mod = types.ModuleType(f"friday.connectors.sites.{name}")
    mod.ADAPTERS, mod.FAKE_SITES = adapters, fakes or {}
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    monkeypatch.setattr(categories, "PACKAGES", (name,))
    categories.reload()


def test_loader_merges_packages_and_exposes_adapter_for(monkeypatch):
    class A:
        required = ("items",)

    _fake_package(monkeypatch, "grocery", {"blinkit.grocery": A}, {"blinkit.grocery": object})
    assert categories.adapter_for("Blinkit", "grocery") is A
    assert categories.adapter_for("blinkit", "ride") is None
    assert "zomato.food" in categories.all_adapters() and "blinkit.grocery" in categories.all_adapters()
    assert categories.all_fake_sites() == {"blinkit.grocery": object}
    assert categories.present_packages() == ["grocery"]


def test_loader_tolerates_missing_and_broken_packages(monkeypatch):
    monkeypatch.setattr(categories, "PACKAGES", ("nope_not_there",))
    categories.reload()
    assert categories.missing_packages() == ["nope_not_there"] and "zomato.food" in categories.all_adapters()
    def boom(name):
        raise ImportError("broken package")

    monkeypatch.setattr(categories.importlib, "import_module", boom)
    monkeypatch.setattr(categories, "PACKAGES", ("broken",))
    categories.reload()
    assert categories.failed_packages() == {"broken": "ImportError"}
    assert categories.adapter_for("zomato", "food") is not None


# ---------------------------------------------------------------- settings gate
def test_effective_mode_reads_injected_cleared_set():
    kw = dict(supervised=True, adapter=True)
    assert catalog.effective_mode("blinkit", {"blinkit"}, **kw) == "deeplink"  # not cleared
    assert catalog.effective_mode("blinkit", {"blinkit"}, cleared={"blinkit"}, **kw) == "scripted"
    assert catalog.effective_mode("blinkit", set(), cleared={"blinkit"}, **kw) == "deeplink"  # not enabled
    assert catalog.effective_mode("blinkit", {"blinkit"}, cleared={"blinkit"}, supervised=False, adapter=True) == "deeplink"
    assert catalog.effective_mode("blinkit", {"blinkit"}, cleared={"blinkit"}, supervised=True, adapter=False) == "deeplink"
    assert catalog.effective_mode("nosuchsite", {"x"}, cleared={"x"}, **kw) == "blocked"


def test_browser_settings_default_off_and_from_env(monkeypatch):
    for k in ("SITES_ENABLED", "LEGAL_CLEARED", "SUPERVISED", "ENABLED"):
        monkeypatch.delenv(f"FRIDAY_BROWSER_{k}", raising=False)
    s = BrowserSettings()
    assert not s.enabled and not s.supervised and not s.sites_enabled_set() and not s.legal_cleared_set()
    assert all(s.site_mode(x.key) in {"deeplink", "blocked"} for x in catalog.SITES)
    monkeypatch.setenv("FRIDAY_BROWSER_SITES_ENABLED", "Blinkit, uber")
    monkeypatch.setenv("FRIDAY_BROWSER_LEGAL_CLEARED", "blinkit")
    monkeypatch.setenv("FRIDAY_BROWSER_SUPERVISED", "true")
    s = BrowserSettings()
    assert s.sites_enabled_set() == {"blinkit", "uber"} and s.legal_cleared_set() == {"blinkit"}
    assert s.supervised and s.site_mode("uber") == "deeplink"  # enabled but never cleared


def test_core_settings_carry_the_browser_switches(monkeypatch):
    from friday.core.config import Settings

    monkeypatch.setenv("FRIDAY_BROWSER_SITES_ENABLED", "blinkit,uber")
    monkeypatch.setenv("FRIDAY_BROWSER_LEGAL_CLEARED", "uber")
    monkeypatch.setenv("FRIDAY_BROWSER_ENABLED_USERS", "u1,u2")
    core = Settings()
    assert core.browser_enabled is False and core.browser_supervised is False
    b = BrowserSettings.from_core(core)
    assert b.sites_enabled_set() == {"blinkit", "uber"} and b.legal_cleared_set() == {"uber"}
    assert b.enabled_users == "u1,u2" and not b.user_allowed("u1")  # master switch still off


# ---------------------------------------------------------------- hand-over
async def _flow(mode_of, msgs):
    async def send(m):
        msgs.append(m)

    return BrowserFlow(send=send, registry=sim.make_registry(), sessions=None, otp=None,  # type: ignore[arg-type]
                       profile=lambda u: sim.Profile(), login_link=lambda t: "", base_urls={},
                       enabled=lambda: True, mode_of=mode_of)


async def test_uncleared_site_gets_the_link_and_no_task(monkeypatch):
    monkeypatch.delenv("FRIDAY_BROWSER_LEGAL_CLEARED", raising=False)
    msgs: list = []
    f = await _flow(None, msgs)  # production gate: nothing cleared, nothing enabled
    assert await f.handle_text("u", "Blinkit se doodh mangao", "hi")
    assert [m.kind for m in msgs] == ["outcome"] and "https://blinkit.com" in msgs[0].text
    assert f._store.active("u") is None  # noqa: SLF001
    msgs.clear()
    assert await f.handle_text("u", "order 2 margherita from Domino's")  # zomato: same rule
    assert "zomato.com" in msgs[0].text and f._store.active("u") is None  # noqa: SLF001


async def test_scripted_mode_without_an_adapter_is_still_a_link():
    msgs: list = []
    f = await _flow(lambda s: "scripted", msgs)
    f._adapters.pop("uber.ride", None)  # noqa: SLF001
    assert await f.handle_text("u", "Uber book karo airport")
    assert [m.kind for m in msgs] == ["outcome"] and "m.uber.com" in msgs[0].text


async def test_killed_site_is_a_link():
    msgs: list = []
    f = await _flow(lambda s: "scripted", msgs)
    f._reg.kill("zomato", "food")  # noqa: SLF001
    await f.handle_text("u", "order 2 margherita from Domino's")
    assert [m.kind for m in msgs] == ["outcome"] and "zomato.com" in msgs[0].text
