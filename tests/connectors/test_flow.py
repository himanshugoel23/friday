from __future__ import annotations

import pytest

from friday.connectors.contract import (
    CartMismatch,
    ItemQty,
    LoginFailed,
    LoginRequired,
    TotalsMismatch,
)
from friday.connectors.fake_site import FakeSiteState, SimBrowserSession
from friday.connectors.food.zomato import ZomatoFoodConnector
from friday.connectors.gate import ActionGate
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.pizza_flow import WantedItem, run_pizza_flow
from friday.connectors.recorder import RecordingSession, StepRecorder
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status
from tests.connectors.conftest import OTP, TASK, make_grant

WANT = [WantedItem("margherita", 2), WantedItem("garlic")]


async def _approve(p):
    return make_grant(items=p.items, rid=p.restaurant_id)


async def _decline(p):
    return None


async def test_full_flow_stops_at_payment_handoff(registry):
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_approve)
    assert res.status == "payment_ready"
    assert res.cart.grand_total_paise == 60335
    assert res.handoff.amount_paise == res.cart.grand_total_paise
    assert res.handoff.upi_link.startswith("upi://pay") and res.handoff.qr_png
    assert res.restaurant.restaurant_id == "r-dom-1"


async def test_flow_without_grant_never_builds_cart(registry, state):
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_decline)
    assert res.status == "needs_approval" and res.cart is None
    assert all(not s.cart for s in state.sessions.values())


async def test_flow_grant_scope_mismatch_denied(registry):
    async def wrong(p):
        return make_grant(items=[ItemQty(item_id="i-coke", qty=1)], rid=p.restaurant_id)

    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=wrong)
    assert res.status == "denied" and res.cart is None


async def test_flow_over_budget_stops_before_handoff(registry):
    async def tight(p):
        return make_grant(items=p.items, rid=p.restaurant_id, max_total=50_000)

    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=tight)
    assert res.status == "denied" and res.handoff is None and res.cart is not None


async def test_flow_unknown_item(registry):
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x",
                               wanted=[WantedItem("sushi")], approve=_approve)
    assert res.status == "item_not_found"


async def test_totals_mismatch_on_page_is_rejected(otp):
    st = FakeSiteState(otp=OTP, tamper_paise=500)
    conn = ZomatoFoodConnector(SimBrowserSession(st), base_url="http://x", task_id=TASK,
                               otp_channel=otp, phone="9000000001", poll_s=0.01)
    with pytest.raises(TotalsMismatch):
        await conn.build_cart("r-dom-1", [ItemQty(item_id="i-marg", qty=1)])


async def test_tampered_page_surfaces_as_flow_error(otp):
    st = FakeSiteState(otp=OTP, tamper_paise=500)
    conn = ZomatoFoodConnector(SimBrowserSession(st), base_url="http://x", task_id=TASK,
                               otp_channel=otp, phone="9000000001", poll_s=0.01)
    reg = ConnectorRegistry()
    reg.register(Registration("zomato", "food", BackendKind.scripted_browser, Status.live, "1",
                              connector=conn))
    res = await run_pizza_flow(reg, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_approve)
    assert res.status == "error" and res.handoff is None


async def test_otp_is_single_use_and_login_reuse(connector, otp, sim):
    assert await connector.ensure_logged_in() == "logged_in"
    assert otp.take(TASK) is None  # consumed by the login
    assert "OTP" not in repr(connector)
    assert await connector.ensure_logged_in() == "reused"  # no second code needed
    # a fresh connector with no code available cannot log in
    other = ZomatoFoodConnector(SimBrowserSession(FakeSiteState(otp=OTP)), base_url="http://x",
                                task_id="t2", otp_channel=otp, phone="9000000001",
                                otp_wait_s=0.05, poll_s=0.01)
    with pytest.raises(LoginRequired):
        await other.ensure_logged_in()


async def test_wrong_code_fails_login():
    ch = OneTimeOtpChannel()
    ch.submit(TASK, "000000")
    conn = ZomatoFoodConnector(SimBrowserSession(FakeSiteState(otp=OTP)), base_url="http://x",
                               task_id=TASK, otp_channel=ch, phone="9000000001", poll_s=0.01)
    with pytest.raises(LoginFailed):
        await conn.ensure_logged_in()


async def test_cart_mismatch_detected(connector, monkeypatch):
    real = connector._read_cart

    async def short(rid):
        cart = await real(rid)
        return cart.model_copy(update={"lines": cart.lines[:1]})

    monkeypatch.setattr(connector, "_read_cart", short)
    with pytest.raises(CartMismatch):
        await connector.build_cart("r-dom-1", [ItemQty(item_id="i-marg", qty=1),
                                               ItemQty(item_id="i-garlic", qty=1)])


async def test_kill_switch_routes_away_to_in_app_link(registry):
    registry.kill("zomato", "food")
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_approve)
    assert res.status == "finish_in_app"
    assert res.deep_link.url == "https://example.invalid/app" and "app" in res.deep_link.message


async def test_killing_browser_backend_alone_falls_to_deep_link(registry):
    registry.set_status("zomato", "food", BackendKind.scripted_browser, Status.off)
    assert registry.select("zomato", "food").backend == BackendKind.deep_link
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_approve)
    assert res.status == "finish_in_app"


async def test_layout_change_degrades_and_falls_back(registry, monkeypatch):
    from friday.connectors.food import zomato

    monkeypatch.setitem(zomato.SELECTORS, "menu_item", "[data-testid=renamed-by-site]")
    res = await run_pizza_flow(registry, ActionGate(), task_id=TASK, area="x", wanted=WANT,
                               approve=_approve)
    assert res.status == "finish_in_app"
    live = registry.select("zomato", "food")
    assert live.backend == BackendKind.deep_link  # browser backend now degraded
    assert any(r["status"] == "degraded" for r in registry.describe())


async def test_recorder_captures_steps_without_values(state, otp):
    rec = StepRecorder()
    conn = ZomatoFoodConnector(RecordingSession(SimBrowserSession(state), rec),
                               base_url="http://x", task_id=TASK, otp_channel=otp,
                               phone="9000000001", poll_s=0.01)
    await conn.ensure_logged_in()
    blob = " ".join(f"{s.action} {s.url} {s.note}" for s in rec.steps)
    assert rec.steps and "9000000001" not in blob and OTP not in blob
    assert [s.n for s in rec.steps] == list(range(1, len(rec.steps) + 1))
