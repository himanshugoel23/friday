# ruff: noqa: E501
"""T08 through the real container and InboundPipeline (the child's chat is the simulator channel, the same contract the web chat uses):
"pair phone for papa" with the REAL device service (single-use code, 15 minutes, the parent never types), "what is on" and "what Robin did
today", and the production child sender. Fakes only; nothing is sent or dialled."""

from __future__ import annotations

import re

from friday.robin.models import CallResult
from tests.e2e.robin.harness import CHILD, assert_no_pii

CODE = re.compile(r"\b([A-Z0-9]{8})\b")


async def test_pair_phone_for_papa_gives_a_single_use_code_that_pairs_the_phone_once(dworld):
    w = dworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    out = await w.child_says("pair phone for papa")
    text = "\n".join(out)
    m = re.search(r"robin://pair\?code=([A-Z0-9]{8})", text)
    assert m, text
    code = m.group(1)
    assert code in text and "15 minutes" in text and "Papa" in text
    # the code works once, from the parent's phone (the child typed it there; the parent typed nothing)
    first = await w.device.client.post("/robin/device/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
    assert first.status_code == 200 and first.json()["device_token"]
    second = await w.device.client.post("/robin/device/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
    assert second.status_code != 200  # single use
    # a new command makes a new code for a new phone (the old token is replaced by the device service on re-pair)
    out2 = "\n".join(await w.child_says("pair phone for papa"))
    code2 = re.search(r"robin://pair\?code=([A-Z0-9]{8})", out2).group(1)
    assert code2 != code
    # the code is a secret: not in the family log, not in the app logs
    blob = await w.audit_blob()
    assert code not in blob and code2 not in blob
    assert_no_pii(w.logs.lines, secrets=(code, code2), what="logs")


async def test_pair_phone_is_off_when_the_device_switch_is_off(world):
    w = world
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    out = "\n".join(await w.child_says("pair phone for papa"))
    assert "not switched on" in out and not re.search(r"robin://", out)


async def test_what_is_on_and_what_robin_did_today_are_confirmed_in_the_chat(world):
    w = world
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    on = "\n".join(await w.child_says("what is on"))
    assert "What Robin sees and does for Papa" in on and "- " in on
    assert "What Robin did today" not in on  # the log is the other command
    assert "never records calls" in on
    today = "\n".join(await w.child_says("what Robin did today"))
    assert today.startswith("What Robin did today") and "Told Papa that Robin was set up" in today
    assert "never records calls" not in today  # only the log
    for words in ("what did Robin do today", "whats on"):
        assert await w.child_says(words)


async def test_the_production_child_sender_raises_when_the_notifier_says_not_delivered(world, monkeypatch):
    """build_robin's ``send``: a not-ok receipt (after the Notifier's WhatsApp -> SMS chain) must reach the ladder as an exception, and the
    alert then waits in the chat inbox and shows at the child's next message."""
    from types import SimpleNamespace

    from friday.robin.alerts import RobinAlert
    from friday.robin.models import Tier

    w = world
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    await w.consent_device()
    parent = await w.parent()
    notifier = w.f.c.get("notifier")
    real = notifier.notify_user

    async def refuse(user_id, text=None, **kw):
        return SimpleNamespace(ok=False, error="template_required")

    monkeypatch.setattr(notifier, "notify_user", refuse)
    w.script_calls(CallResult.NO_ANSWER)
    res = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "unknown caller 22 minutes", dedupe_key="held-e2e"))
    assert res.accepted
    (inc,) = [i for i in await w.incidents() if i.data["scenario"] == "S1"]
    assert inc.data["delivery_failed"] is True
    monkeypatch.setattr(notifier, "notify_user", real)
    out = "\n".join(await w.child_says("parent status"))
    assert "unknown caller 22 minutes" in out and "held" in out.lower()
    assert CHILD not in out
