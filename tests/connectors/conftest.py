from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from friday.connectors.contract import ItemQty
from friday.connectors.fake_site import FakeSiteState, SimBrowserSession
from friday.connectors.food.zomato import ZomatoFoodConnector
from friday.connectors.gate import Grant
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status

OTP = "135790"  # a fake-site test code
TASK = "t-1"


def make_grant(items=None, rid="r-dom-1", max_total=100_000, **kw) -> Grant:
    return Grant(
        task_id=kw.pop("task_id", TASK), connector="zomato.food", restaurant_id=rid,
        items=items or [ItemQty(item_id="i-marg", qty=2), ItemQty(item_id="i-garlic", qty=1)],
        max_total_paise=max_total,
        expires_at=kw.pop("expires_at", datetime.now(UTC) + timedelta(minutes=5)), **kw)


@pytest.fixture
def state() -> FakeSiteState:
    return FakeSiteState(otp=OTP)


@pytest.fixture
def otp() -> OneTimeOtpChannel:
    ch = OneTimeOtpChannel()
    ch.submit(TASK, OTP)
    return ch


@pytest.fixture
def sim(state) -> SimBrowserSession:
    return SimBrowserSession(state)


@pytest.fixture
def connector(sim, otp) -> ZomatoFoodConnector:
    return ZomatoFoodConnector(sim, base_url="http://fake.invalid", task_id=TASK,
                               otp_channel=otp, phone="9000000001", poll_s=0.01, otp_wait_s=0.2)


@pytest.fixture
def registry(connector) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(Registration("zomato", "food", BackendKind.deep_link, Status.live, "1",
                              fallback_url="https://example.invalid/app"))
    reg.register(Registration("zomato", "food", BackendKind.scripted_browser, Status.live, "1",
                              connector=connector))
    return reg
