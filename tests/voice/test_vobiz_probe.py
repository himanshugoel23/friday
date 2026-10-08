"""Read-only Vobiz account probe over recorded payloads (shapes captured live 2026-10-08,
personal fields removed). Offline: no network."""

from __future__ import annotations

import httpx
import pytest

from friday.core.interfaces import ProviderError
from friday.voice.telephony.vobiz_probe import fetch_probe, format_probe, summarize

ME = {
    "account_type": "standard",
    "postpaid": False,
    "enabled": True,
    "is_active": True,
    "is_verified": True,
    "is_trial_account": True,
    "cps_limit": 1,
    "concurrent_calls_limit": 3,
    "features": {"call_queue": True},
    "pricing_tier": {"rate_per_minute": 0.38},
    "email": "founder@example.com",
    "address": "secret street",
}
BAL = {"currency": "INR", "balance": 25, "available_balance": 25, "status": "active"}
NUMS = {
    "is_trial": True,
    "items": [
        {
            "e164": "+918065354620",
            "status": "active",
            "voice_enabled": True,
            "is_trial_number": True,
            "is_blocked": False,
            "is_spam": False,
        }
    ],
}


def handler(req: httpx.Request) -> httpx.Response:
    assert req.method == "GET"  # read-only, always
    assert req.headers["x-auth-id"] == "MA_T" and req.headers["x-auth-token"] == "tok"
    path = req.url.path
    if path.endswith("/auth/me"):
        return httpx.Response(200, json=ME)
    if path.endswith("/balance/INR"):
        return httpx.Response(200, json=BAL)
    if path.endswith("/numbers"):
        return httpx.Response(200, json=NUMS)
    return httpx.Response(404)


async def test_probe_reports_trial_queue_and_limits():
    p = await fetch_probe(
        "MA_T", "tok", transport=httpx.MockTransport(handler), caller_ids=["+918065354620"]
    )
    assert p["is_trial"] and p["call_queue"] is True and p["balance"] == 25
    assert p["cps_limit"] == 1 and p["concurrent_calls_limit"] == 3
    assert p["numbers"][0]["e164"] == "+918065354620"
    assert any("call_queue" in i for i in p["issues"])
    assert any("trial" in i for i in p["issues"])
    text = format_probe(p)
    assert "founder@example.com" not in text and "secret street" not in text and "tok" not in text
    assert "CPS 1" in text and "ISSUE" in text


def test_probe_flags_missing_caller_id_and_low_balance_and_clean_account():
    me = {**ME, "is_trial_account": False, "features": {"call_queue": False}}
    clean = summarize(me, BAL, NUMS, caller_ids=["+918065354620"])
    assert clean["issues"] == [] and "no blocking issues" in format_probe(clean)
    bad = summarize(me, {**BAL, "available_balance": 1}, NUMS, caller_ids=["+919999999999"])
    assert any("balance" in i for i in bad["issues"])
    assert any("caller ID" in i for i in bad["issues"])


async def test_probe_auth_failure_is_a_provider_error():
    with pytest.raises(ProviderError):
        await fetch_probe(
            "MA_T", "tok", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))
        )
