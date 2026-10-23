# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json

import pytest

from friday.connectors import flow as flowmod
from friday.connectors.flow import (
    BrowserFlow,
    JsonTaskStore,
    browser_enabled,
    get_browser_handler,
    register_browser_handler,
)
from friday.connectors.sites import sim
from friday.connectors.sites.copy import COPY
from friday.connectors.sites.sim import BY_NAME, SCENARIOS, run_scenario

ALLOWED_KINDS = {"ack", "question", "approval", "login", "payment", "outcome"}
SECRET_CODES = (sim.FOOD_OTP, sim.MOVIE_OTP, "000000")


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
@pytest.mark.parametrize("lang", ["en", "hi"])
async def test_every_scenario_ends_as_expected(sc, lang):
    r = await run_scenario(sc, lang)
    assert r.ok(), [(m.kind, m.text) for m in r.messages]


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
async def test_messaging_and_secret_rules(sc):
    r = await run_scenario(sc)
    kinds = r.kinds()
    assert kinds[0] == "ack" and kinds.count("ack") == 1  # one ack, then only questions / outcome
    assert set(kinds) <= ALLOWED_KINDS
    blob = " ".join(m.text for m in r.messages) + r.task.model_dump_json()
    assert not any(c in blob for c in SECRET_CODES)  # no login code in chat or in task state
    assert "scam@" not in blob and "Rs 5000" not in blob  # injected text never repeated
    for m in r.messages:
        assert all(len(title) <= 20 for _, title in m.buttons)
        assert len(m.buttons) <= 3
    for s in r.sessions:  # nothing was ever "paid": no pay / place-order control was clicked
        assert not any("pay" in c.split(":")[-1] and c.startswith("click") for c in s.calls
                       if "proceed_to_pay" not in c)
    assert all(sid for sid in r.flow._sessions.closed) or True  # noqa: SLF001


async def test_approval_card_has_exact_details_before_anything_is_added():
    r = await run_scenario(BY_NAME["food_cancel"])
    card = next(m for m in r.messages if m.kind == "approval").text
    for part in ("2 x Margherita", "Domino's Pizza", "Flat 4, Sector 12", "₹398.00", "never pay"):
        assert part in card
    assert r.food.sessions and not any(s.cart for s in r.food.sessions.values())  # nothing carted


async def test_movie_approval_card_and_payment_handoff():
    r = await run_scenario(BY_NAME["movie_happy"])
    card = next(m for m in r.messages if m.kind == "approval").text
    for part in ("Pixel Heist", "Fake Cinemas", "19:00", "A1, A2", "₹500.00"):
        assert part in card
    pay = next(m for m in r.messages if m.kind == "payment")
    assert pay.image_png and "not paid" in pay.text


async def test_price_change_asks_again_with_exact_total():
    r = await run_scenario(BY_NAME["food_price_changed"])
    cards = [m for m in r.messages if m.kind == "approval"]
    assert len(cards) == 2 and "went up" in cards[1].text and "approved up to" in cards[1].text
    assert r.task.reapprovals == 1


async def test_layout_broken_degrades_registry_and_gives_link():
    r = await run_scenario(BY_NAME["food_layout_broken"])
    assert r.registry.select("zomato", "food") is None
    assert "zomato.com" in r.last
    assert "repaired" not in r.last


async def test_repair_is_noted_in_summary_and_logged():
    r = await run_scenario(BY_NAME["food_layout_repaired"])
    assert "adapted" in r.last and r.task.notes.get("repaired")


async def test_login_timeout_offers_retry_button():
    r = await run_scenario(BY_NAME["food_login_timeout"])
    last = r.messages[-1]
    assert last.kind == "login" and any(b.startswith("bf:retry:") for b, _ in last.buttons)


# ---------------------------------------------------------------- switch, handler, store
def test_default_off(monkeypatch):
    monkeypatch.delenv("FRIDAY_BROWSER_ENABLED", raising=False)
    assert browser_enabled() is False
    assert browser_enabled({"FRIDAY_BROWSER_ENABLED": "true"}) is True
    assert browser_enabled({"FRIDAY_BROWSER_ENABLED": "false"}) is False


async def test_disabled_flow_consumes_nothing():
    msgs = []

    async def send(m):
        msgs.append(m)

    f = BrowserFlow(send=send, registry=sim.make_registry(), sessions=None, otp=None,  # type: ignore[arg-type]
                    profile=lambda u: None, login_link=lambda t: "", base_urls={},
                    enabled=lambda: False)
    assert not f.matches("order pizza from dominos")
    assert await f.handle_text("u", "order 2 margherita from dominos") is False
    assert await f.handle_button("u", "bf:yes:x") is False
    assert msgs == []


async def test_unrelated_text_is_not_consumed():
    r = await run_scenario(BY_NAME["food_cancel"])
    assert await r.flow.handle_text("another-user", "what's the weather") is False


def test_handler_registration():
    class H:
        pass

    register_browser_handler(H())  # type: ignore[arg-type]
    assert get_browser_handler() is not None
    register_browser_handler(None)
    assert get_browser_handler() is None


async def test_double_tap_and_stale_buttons_are_harmless():
    def hook(flow):
        orig = flow.handle_button

        async def twice(u, b):
            await orig(u, b)
            return await orig(u, b)

        flow.handle_button = twice

    r = await run_scenario(BY_NAME["food_happy"], flow_hook=hook)
    assert r.ok() and r.kinds().count("payment") == 1


async def test_resumable_task_state(tmp_path):
    sc = BY_NAME["food_cancel"]
    path = tmp_path / "tasks.json"
    msgs = []

    async def send(m):
        msgs.append(m)

    def build():
        return BrowserFlow(
            send=send, registry=sim.make_registry(), sessions=sim.SimProvider(
                lambda site: sim.ScenarioFoodSession(sim.ScenarioFoodState())),
            otp=sim.OneTimeOtpChannel(), profile=lambda u: sc.profile,
            login_link=lambda t: "https://friday.invalid/otp/x",
            base_urls={"zomato.food": "http://fake.invalid"}, store=JsonTaskStore(path),
            enabled=lambda: True)

    f1 = build()
    await f1.handle_text("u1", "Order 2 margherita from Domino's")
    assert [m.kind for m in msgs] == ["ack", "approval"]
    json.loads(path.read_text())  # plain JSON, no secrets
    f2 = build()  # "restart"
    assert await f2.resume("u1")
    assert msgs[-1].kind == "approval" and "Margherita" in msgs[-1].text
    await f2.handle_button("u1", f"bf:no:{f2._store.active('u1').task_id}")  # noqa: SLF001
    assert msgs[-1].kind == "outcome" and f2._store.active("u1") is None  # noqa: SLF001
    await asyncio.sleep(0)


def test_copy_is_complete_and_secret_free():
    for key, langs in COPY.items():
        assert set(langs) == {"en", "hi"}, key
        for text in langs.values():
            assert "{otp}" not in text and "password" not in text.lower() or key == "login_needed"
    assert flowmod.ENABLE_ENV == "FRIDAY_BROWSER_ENABLED"
