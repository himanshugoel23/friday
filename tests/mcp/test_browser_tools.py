from __future__ import annotations

import json
import re

import pytest

from friday.mcp import BROWSER_TOOLS, CallContext, Level, ToolError, build_browser_registry
from friday.mcp.fakes import FakeApprovals, FakeBrowserBackend

A = CallContext("user-a", "t1")
B = CallContext("user-b", "t2")


def make(users=("user-a", "user-b")):
    be = FakeBrowserBackend({"shop.test"}, {"https://shop.test/": ["Margherita Rs 249"]})
    reg = build_browser_registry(be.handlers(), approvals=FakeApprovals(be), enabled_users=set(users))
    return be, reg


def test_six_tools_with_levels():
    assert {t.name for t in BROWSER_TOOLS} == {
        "browser.open_task", "browser.read_page", "browser.act", "browser.request_user_login",
        "browser.request_approval", "browser.get_summary"}
    assert {t.name: t.level for t in BROWSER_TOOLS}["browser.read_page"] is Level.read


def test_no_schema_field_can_carry_a_secret():
    bad = re.compile(r"(?i)otp|password|passwd|passcode|cvv|card|cookie|token")
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "properties":
                    yield from v.keys()
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    for t in BROWSER_TOOLS:
        assert not [k for k in keys(t.input) if bad.search(k)], t.name
        assert not [k for k in keys(t.output) if bad.search(k)], t.name


async def test_default_off_for_everyone():
    _, reg = make(users=())
    assert reg.catalogue("user-a") == []
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "pizza"})
    assert e.value.code == "disabled"


async def test_happy_path_and_audit():
    be, reg = make()
    r = await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "pizza"})
    tid = r["browser_task_id"]
    page = await reg.call(A, "browser.read_page", {"browser_task_id": tid})
    assert page["untrusted"] is True
    await reg.call(A, "browser.act", {"browser_task_id": tid, "action": "click", "target": "#add",
                                      "intent": "edit"})
    entries = reg.audit.entries("user-a")
    assert [e.decision for e in entries] == ["allow"] * 3
    assert all(e.args_hash and e.result_status == "ok" for e in entries)


async def test_commit_needs_approval_then_works_once_user_pressed():
    be, reg = make()
    tid = (await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x"}))["browser_task_id"]
    commit = {"browser_task_id": tid, "action": "click", "target": "#place", "intent": "commit"}
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.act", commit)
    assert e.value.code == "needs_approval" and be.committed == []
    ap = await reg.call(A, "browser.request_approval", {
        "browser_task_id": tid, "merchant": "Shop", "max_total_paise": 50000,
        "items": [{"item_id": "i1", "qty": 1}]})
    with pytest.raises(ToolError):  # asking is not approving
        await reg.call(A, "browser.act", commit)
    be.user_approves(ap["approval_id"])
    await reg.call(A, "browser.act", commit)
    assert be.committed == [(tid, "#place")]
    assert reg.audit.entries()[-1].level == "irreversible"


async def test_users_are_isolated():
    be, reg = make()
    tid = (await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x"}))["browser_task_id"]
    with pytest.raises(ToolError) as e:
        await reg.call(B, "browser.read_page", {"browser_task_id": tid})
    assert e.value.code == "forbidden"
    # user B approving does not unlock A's task
    ap = await reg.call(A, "browser.request_approval", {
        "browser_task_id": tid, "merchant": "S", "max_total_paise": 100, "items": [{"item_id": "i", "qty": 1}]})
    be.approvals[ap["approval_id"]]["user_id"] = "user-b"
    with pytest.raises(ToolError):
        await reg.call(A, "browser.act", {"browser_task_id": tid, "action": "click", "target": "#p",
                                          "intent": "commit"})


async def test_kill_switch_and_domain_allow_list_and_secret_fields():
    be, reg = make()
    tid = (await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x"}))["browser_task_id"]
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.act", {"browser_task_id": tid, "action": "goto",
                                          "target": "https://evil.test/", "intent": "navigate"})
    assert e.value.code == "forbidden"
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.act", {"browser_task_id": tid, "action": "fill",
                                          "target": "#otp", "value": "123456", "intent": "edit"})
    assert e.value.code == "forbidden"
    with pytest.raises(ToolError):
        await reg.call(A, "browser.open_task", {"site": "other.test", "goal": "x"})
    reg.kill()
    assert reg.catalogue("user-a") == []
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.get_summary", {"browser_task_id": tid})
    assert e.value.code == "killed"


async def test_invalid_args_and_no_values_in_audit_or_errors():
    be, reg = make()
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x", "password": "hunter2hunter2"})
    assert e.value.code == "invalid" and "hunter2" not in str(e.value)
    blob = json.dumps([e.args_preview + e.reason for e in reg.audit.entries()])
    assert "hunter2" not in blob


async def test_handler_crash_is_wrapped_without_detail():
    be, reg = make()
    tid = (await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x"}))["browser_task_id"]
    be.fail_next = True
    with pytest.raises(ToolError) as e:
        await reg.call(A, "browser.get_summary", {"browser_task_id": tid})
    assert e.value.code == "error"
    assert reg.audit.entries()[-1].result_status == "error"


async def test_login_returns_link_only():
    be, reg = make()
    tid = (await reg.call(A, "browser.open_task", {"site": "shop.test", "goal": "x"}))["browser_task_id"]
    r = await reg.call(A, "browser.request_user_login", {"browser_task_id": tid})
    assert set(r) == {"login_url", "expires_in_s"}
