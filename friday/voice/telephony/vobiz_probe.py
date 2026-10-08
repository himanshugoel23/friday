"""Read-only Vobiz account probe (never places a call, never spends money).

Calls three GET endpoints (verified live 2026-10-08; docs: vobiz.ai/docs/api-reference/
authentication, /docs/account/account-object, /docs/account-phone-number):

  * ``GET /auth/me``                          account object (type, trial, CPS, features)
  * ``GET /Account/{auth_id}/balance/INR``    prepaid balance
  * ``GET /Account/{auth_id}/numbers``        numbers on the account

``summarize`` keeps only operational fields: no name, email, address or token is ever returned
or printed. ``issues`` lists what must be fixed before a real call.
"""

from __future__ import annotations

from typing import Any

import httpx

from friday.core.interfaces import ProviderError
from friday.voice._http import VendorHTTP

DEFAULT_BASE_URL = "https://api.vobiz.ai/api/v1"
MIN_BALANCE_INR = 5.0  # rough floor: one short call at 0.44 INR/min API-streaming rate


async def fetch_probe(
    auth_id: str,
    auth_token: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    transport: httpx.AsyncBaseTransport | None = None,
    caller_ids: list[str] | None = None,
) -> dict[str, Any]:
    http = VendorHTTP(
        "vobiz",
        base_url=base_url.rstrip("/"),
        headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token},
        retries=1,
        transport=transport,
    )
    try:
        me = (await http.request("GET", "/auth/me")).json()
        bal = (await http.request("GET", f"/Account/{auth_id}/balance/INR")).json()
        nums = (await http.request("GET", f"/Account/{auth_id}/numbers")).json()
    except ValueError as e:
        raise ProviderError("vobiz", "invalid JSON from the account API") from e
    finally:
        await http.aclose()
    return summarize(me, bal, nums, caller_ids=caller_ids or [])


def summarize(
    me: dict[str, Any],
    balance: dict[str, Any],
    numbers: dict[str, Any],
    *,
    caller_ids: list[str] | None = None,
) -> dict[str, Any]:
    features = me.get("features") or {}
    items = numbers.get("items") or []
    out: dict[str, Any] = {
        "account_type": me.get("account_type"),
        "is_trial": bool(me.get("is_trial_account")),
        "postpaid": bool(me.get("postpaid")),
        "enabled": bool(me.get("enabled")) and bool(me.get("is_active", True)),
        "verified": bool(me.get("is_verified")),
        "balance": balance.get("available_balance", balance.get("balance")),
        "currency": balance.get("currency", "INR"),
        "balance_status": balance.get("status"),
        "cps_limit": me.get("cps_limit"),
        "concurrent_calls_limit": me.get("concurrent_calls_limit"),
        "call_queue": features.get("call_queue"),
        "rate_per_minute": (me.get("pricing_tier") or {}).get("rate_per_minute"),
        "numbers": [
            {
                "e164": n.get("e164"),
                "status": n.get("status"),
                "voice": bool(n.get("voice_enabled")),
                "trial": bool(n.get("is_trial_number")),
                "blocked": bool(n.get("is_blocked")),
                "spam": bool(n.get("is_spam")),
            }
            for n in items
        ],
    }
    out["issues"] = issues(out, caller_ids or [])
    return out


def issues(p: dict[str, Any], caller_ids: list[str]) -> list[str]:
    """What blocks or endangers a real call."""
    found: list[str] = []
    if not p.get("enabled"):
        found.append("account is disabled")
    if p.get("call_queue"):
        found.append(
            "features.call_queue is ON: outbound calls are queued and may be marked failed; "
            "ask Vobiz support / the console to turn it OFF before real calls"
        )
    if p.get("is_trial"):
        found.append("trial account: shared trial number, possible destination restrictions")
    bal = p.get("balance")
    if isinstance(bal, int | float) and bal < MIN_BALANCE_INR:
        found.append(f"balance {bal} {p.get('currency')} is below {MIN_BALANCE_INR}")
    nums = p.get("numbers") or []
    if not any(n["voice"] and n["status"] == "active" and not n["blocked"] for n in nums):
        found.append("no active voice-enabled number on the account")
    if any(n["spam"] for n in nums):
        found.append("a number is flagged spam")
    owned = {n["e164"] for n in nums}
    for cid in caller_ids:
        if cid not in owned:
            found.append("a configured caller ID is not a number on this account")
            break
    return found


def format_probe(p: dict[str, Any]) -> str:
    lines = [
        f"account: type={p['account_type']} trial={p['is_trial']} postpaid={p['postpaid']} "
        f"enabled={p['enabled']} verified={p['verified']}",
        f"balance: {p['balance']} {p['currency']} ({p['balance_status']}), "
        f"rate {p['rate_per_minute']} /min",
        f"limits: CPS {p['cps_limit']}, concurrent calls {p['concurrent_calls_limit']}",
        f"features.call_queue: {p['call_queue']}",
    ]
    for n in p["numbers"]:
        lines.append(
            f"number: {n['e164']} status={n['status']} voice={n['voice']} trial={n['trial']} "
            f"blocked={n['blocked']} spam={n['spam']}"
        )
    lines += [f"ISSUE: {i}" for i in p["issues"]] or ["no blocking issues"]
    return "\n".join(lines)


async def probe_from_settings(settings: Any) -> dict[str, Any]:
    if not (settings.sarvam_telephony_auth_id and settings.sarvam_telephony_auth_token):
        raise ProviderError("vobiz", "SARVAM_TELEPHONY_AUTH_ID / _AUTH_TOKEN not set")
    return await fetch_probe(
        settings.sarvam_telephony_auth_id,
        settings.sarvam_telephony_auth_token.get_secret_value(),
        base_url=settings.sarvam_telephony_base_url or DEFAULT_BASE_URL,
        caller_ids=list(settings.sarvam_caller_ids or settings.friday_numbers or []),
    )


def run_live_check(settings: Any) -> int:
    """``friday check --live``: read-only Vobiz probe; exit 1 when it cannot run or finds issues."""
    import asyncio

    try:
        p = asyncio.run(probe_from_settings(settings))
    except ProviderError as e:
        print(f"vobiz probe failed: {e}")
        return 1
    print(format_probe(p))
    return 1 if p["issues"] else 0
