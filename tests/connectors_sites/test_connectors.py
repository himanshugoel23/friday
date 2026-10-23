# ruff: noqa: E501
from __future__ import annotations

import pytest

from friday.connectors.contract import ItemQty, LayoutChanged, LoginRequired, TotalsMismatch
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.fakes.food_site import ScenarioFoodSession, ScenarioFoodState
from friday.connectors.sites.fakes.movie_site import OTP, FakeMovieState, MovieSimSession
from friday.connectors.sites.movies import bookmyshow as bms
from friday.connectors.sites.movies.contract import SeatHold, SeatLine
from friday.connectors.sites.zomato_agent import AgentZomatoConnector, build_kit

BASE = "http://fake.invalid"


def food(state=None, code="246810"):
    st = state or ScenarioFoodState()
    sim = ScenarioFoodSession(st)
    kit = build_kit(sim, task_id="t")
    otp = OneTimeOtpChannel()
    if code:
        otp.submit("t", code)
    return AgentZomatoConnector(kit.session, base_url=BASE, task_id="t", otp_channel=otp,
                                phone="9000000001", poll_s=0, otp_wait_s=0.05), kit, st


async def test_food_search_menu_sold_out_cart_and_handoff_without_paying():
    c, kit, st = food(ScenarioFoodState(sold_out={"i-coke"}))
    rs = await c.search_restaurants("Domino's", "Sector 12")
    assert rs and (await c.get_menu(rs[0].restaurant_id)).items
    assert await c.sold_out_ids(rs[0].restaurant_id) == {"i-coke"}
    cart = await c.build_cart("r-dom-1", [ItemQty(item_id="i-marg", qty=2)])
    assert await c.delivery_address() == "Flat 4, Sector 12"
    with pytest.raises(Exception, match="approval"):  # checkout is irreversible: not armed
        await c.get_payment_handoff(cart)
    with kit.safety.approved("checkout_button"):
        h = await c.get_payment_handoff(cart)
    assert h.amount_paise == cart.grand_total_paise and h.qr_png and h.upi_link.startswith("upi://pay")


async def test_food_out_of_stock_adds_nothing():
    c, _, st = food(ScenarioFoodState(sold_out={"i-marg"}))
    with pytest.raises(OutOfStock) as e:
        await c.build_cart("r-dom-1", [ItemQty(item_id="i-marg", qty=1)])
    assert e.value.names == ["i-marg"]
    assert all(not s.cart for s in st.sessions.values())


async def test_food_login_needs_code_and_announces_wait_once():
    st = ScenarioFoodState()
    kit = build_kit(ScenarioFoodSession(st), task_id="t")
    seen = []

    async def waiting():
        seen.append(1)

    c = AgentZomatoConnector(kit.session, base_url=BASE, task_id="t", otp_channel=OneTimeOtpChannel(),
                             phone="9000000001", poll_s=0, otp_wait_s=0.02, on_code_wait=waiting)
    with pytest.raises(LoginRequired):
        await c.ensure_logged_in()
    assert seen == [1]


async def test_food_tampered_total_is_rejected():
    c, _, _ = food(ScenarioFoodState(tamper_paise=500))
    with pytest.raises(TotalsMismatch):
        await c.build_cart("r-dom-1", [ItemQty(item_id="i-marg", qty=1)])


# ---------------------------------------------------------------- movie
def movie(state=None, code=OTP):
    st = state or FakeMovieState()
    kit = bms.build_kit(MovieSimSession(st), task_id="t")
    otp = OneTimeOtpChannel()
    if code:
        otp.submit("t", code)
    c = bms.BookMyShowConnector(kit.session, base_url=BASE, task_id="t", otp_channel=otp,
                                phone="9000000001", poll_s=0, otp_wait_s=0.05)
    return c, kit, st


async def test_movie_search_seats_hold_and_handoff():
    c, kit, _ = movie()
    shows = await c.search_shows("Pixel Heist", "Sector 12")
    assert {s.show_id for s in shows} == {"s-1", "s-2"} and shows[0].minutes == 19 * 60
    seats = await c.get_seats("s-1")
    assert len(seats) == 8 and all(s.available for s in seats)
    hold = await c.hold_seats("s-1", ["s-1-A1", "s-1-A2"])
    assert hold.subtotal_paise == 50000 and hold.total_paise == 50000 + 6000 + 1080
    with pytest.raises(Exception, match="approval"):
        await c.get_payment_handoff(hold)
    with kit.safety.approved("proceed_to_pay"):
        h = await c.get_payment_handoff(hold)
    assert h.amount_paise == hold.total_paise and h.qr_png


async def test_movie_taken_seat_and_tampered_hold():
    c, _, _ = movie(FakeMovieState(taken={"s-1-A1"}))
    with pytest.raises(OutOfStock):
        await c.hold_seats("s-1", ["s-1-A1"])
    with pytest.raises(ValueError):
        SeatHold(show_id="s", lines=[SeatLine(seat_id="a", label="A1", price_paise=100)],
                 subtotal_paise=100, total_paise=999)


async def test_movie_layout_change_without_alternate_is_layout_error():
    st = FakeMovieState()
    kit = bms.build_kit(MovieSimSession(st, {"seat": "[data-testid=chair]"}), task_id="t")
    c = bms.BookMyShowConnector(kit.session, base_url=BASE, task_id="t")
    with pytest.raises(LayoutChanged):
        await c.get_seats("s-1")
