"""Shared fixtures. Everything runs on FAKE sites and fakes; no network, no real account."""

from __future__ import annotations

import importlib.util
import logging

import pytest

from friday.connectors.fake_site import FakeSiteState, SimBrowserSession
from friday.connectors.food.zomato import ZomatoFoodConnector
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status

OTP_A = "135790"
OTP_B = "246802"


def module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def needs(name: str, why: str):
    """Skip until another team's package lands. Remove nothing: the test starts running by itself."""
    return pytest.mark.skipif(not module_exists(name), reason=f"{name} not landed yet: {why}")


@pytest.fixture(autouse=True)
def _all_logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def make_user(task_id: str, otp_code: str, phone: str, channel: OneTimeOtpChannel | None = None,
              *, registry: ConnectorRegistry | None = None):
    """One user = own fake site state, own browser session, own OTP slot, own connector."""
    state = FakeSiteState(otp=otp_code)
    ch = channel or OneTimeOtpChannel()
    ch.submit(task_id, otp_code)
    conn = ZomatoFoodConnector(SimBrowserSession(state), base_url="http://fake.invalid",
                               task_id=task_id, otp_channel=ch, phone=phone, poll_s=0.01,
                               otp_wait_s=0.3)
    reg = registry or ConnectorRegistry()
    reg.register(Registration("zomato", "food", BackendKind.deep_link, Status.live, "1",
                              fallback_url="https://example.invalid/app"))
    reg.register(Registration("zomato", "food", BackendKind.scripted_browser, Status.live, "1",
                              connector=conn))
    return state, conn, reg, ch
