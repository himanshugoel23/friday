# ruff: noqa: E501
"""The private browser wired into the app: off by default, one flow handler, login commands,
routes, delete-everything, kill latch. Fake backend only; no real site."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.browser_routes import mount_browser
from friday.connectors.flow import get_browser_handler, register_browser_handler
from tests.chatbot.conftest import TESTER, build_chat


@pytest.fixture(autouse=True)
def _clean_handler():
    register_browser_handler(None)
    yield
    register_browser_handler(None)


def on(tmp_path, **over):
    return {"browser_enabled": True, "browser_enabled_users": ["*"], "browser_backend": "fake",
            "browser_vault_dir": str(tmp_path / "v"), "browser_credentials_dir": str(tmp_path / "c"),
            "browser_audit_file": str(tmp_path / "a.jsonl"), **over}


async def test_off_by_default_nothing_is_built_or_mounted():
    w = await build_chat()
    try:
        assert w.pipeline.browser is None and get_browser_handler() is None
        from friday.api.app import create_app

        client = TestClient(create_app(w.c, background=False))
        assert client.get("/ride/code/x").status_code == 404  # not mounted
    finally:
        await w.c.aclose()


async def test_on_builds_the_stack_registers_the_handler_and_mounts_routes(tmp_path):
    w = await build_chat(**on(tmp_path, browser_credentials_enabled=True,
                              browser_credentials_enabled_users=["*"]))
    try:
        stack = w.pipeline.browser
        assert stack is not None and stack.credentials is not None
        stack.start()
        try:
            assert get_browser_handler() is stack.flow
            assert stack.watcher._task is not None  # noqa: SLF001
        finally:
            await stack.stop()
        assert get_browser_handler() is None
        from friday.api.app import create_app

        client = TestClient(create_app(w.c, background=False))
        assert client.get("/ride/code/x").status_code == 200  # mounted (shows the button, not a code)
        assert client.get("/connectors/qr/nope.png").status_code == 404  # route exists, token unknown
        assert client.get("/connectors/otp/nope").status_code == 404
        assert client.get("/connectors/credentials/nope").status_code == 404
        assert client.get("/live/nope").status_code == 404
    finally:
        await w.c.aclose()


async def test_default_gate_hands_over_the_link_from_whatsapp(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        out = await w.say("Blinkit se doodh mangao")
        text = " ".join(m.text or "" for m in out)
        assert "https://blinkit.com" in text
        out = await w.say("Delhi se Jaipur bus")
        assert "redbus.in" in " ".join(m.text or "" for m in out)
    finally:
        await w.c.aclose()


async def test_user_not_named_is_not_touched(tmp_path):
    w = await build_chat(**on(tmp_path, browser_enabled_users=["someone-else"]))
    try:
        await w.onboard()
        out = await w.say("Blinkit se doodh mangao")
        assert "blinkit.com" not in " ".join(m.text or "" for m in out)
    finally:
        await w.c.aclose()


async def test_stale_browser_button_is_swallowed(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        out = await w.tap_id("bf:yes:nope")
        assert out == [] or all("Hinglish" not in (m.text or "") for m in out)
    finally:
        await w.c.aclose()


async def test_login_commands_list_and_forget_without_showing_passwords(tmp_path):
    w = await build_chat(**on(tmp_path, browser_credentials_enabled=True,
                              browser_credentials_enabled_users=["*"]))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        assert "nahi hain" in " ".join(m.text or "" for m in await w.say("my logins")).lower()
        out = await w.say("save blinkit login")
        link = next(m.text for m in out if "/connectors/credentials/" in (m.text or ""))
        assert "private page" in link
        stack.credentials.vault.save(user.id, "blinkit", "asha@example.test", "Hunter2-Test!", hosts=["blinkit.com"], consent=True)
        shown = " ".join(m.text or "" for m in await w.say("my logins"))
        assert "blinkit" in shown and "Hunter2" not in shown and "asha@example.test" not in shown
        ask = await w.say("forget my logins")  # asks first, deletes nothing yet
        assert "1 saved login" in ask[0].text and [b.id for b in ask[0].buttons] == ["lg:yes", "lg:no"]
        assert len(stack.credentials.saved(user.id)) == 1
        done = " ".join(m.text or "" for m in await w.say("yes"))
        assert "1 saved login" in done
        assert stack.credentials.saved(user.id) == []
    finally:
        await w.c.aclose()


async def test_login_commands_say_off_when_saved_logins_are_off(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        assert "chalu nahi hain" in " ".join(m.text or "" for m in await w.say("my logins"))
    finally:
        await w.c.aclose()


async def test_delete_everything_forgets_logins_and_saved_browser_sessions(tmp_path):
    w = await build_chat(**on(tmp_path, browser_credentials_enabled=True,
                              browser_credentials_enabled_users=["*"]))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.credentials.vault.save(user.id, "zepto", "u@example.test", "Pw-Test-12345", hosts=["www.zeptonow.com"], consent=True)
        stack.vault.save(user.id, "zepto", {"cookies": []})
        assert stack.vault.has(user.id, "zepto")
        await w.pipeline.delete_everything(user)
        assert stack.credentials.saved(user.id) == [] and not stack.vault.has(user.id, "zepto")
    finally:
        await w.c.aclose()


async def test_kill_latches_through_the_stack_and_the_provider_refuses(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        stack = w.pipeline.browser
        from friday.connectors.session.manager import SessionRefused

        await stack.manager.kill_all("operator")

        with pytest.raises(SessionRefused):
            await stack.flow._sessions.open(TESTER, "t1", "blinkit")  # noqa: SLF001
        assert stack.manager.revive()
    finally:
        await w.c.aclose()


async def test_provider_opens_a_session_limited_to_the_catalog_hosts(tmp_path):
    from friday.connectors.browser.port import NetworkBlocked

    w = await build_chat(**on(tmp_path, browser_enabled_users=[TESTER]))
    try:
        stack = w.pipeline.browser
        s = await stack.flow._sessions.open(TESTER, "t1", "blinkit")  # noqa: SLF001
        await s.goto("https://blinkit.com/")
        with pytest.raises(NetworkBlocked):
            await s.goto("https://evil.example.test/")
        await stack.flow._sessions.close("t1")  # noqa: SLF001
    finally:
        await w.c.aclose()


async def test_otp_qr_and_ride_code_pages_work_and_are_one_time(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        stack = w.pipeline.browser
        app = FastAPI()
        mount_browser(app, stack)
        client = TestClient(app)
        token = stack.otp_tokens.create("task-1")
        assert client.get(f"/connectors/otp/{token}").status_code == 200
        assert client.post(f"/connectors/otp/{token}", content=b"code=135790").status_code == 200
        assert stack.otp.take("task-1") == "135790"
        assert client.get(f"/connectors/otp/{token}").status_code == 404  # single use
        qr = stack.qr.put(b"\x89PNG-test")
        assert client.get(f"/connectors/qr/{qr}.png").content == b"\x89PNG-test"
        assert client.get("/connectors/qr/unknown.png").status_code == 404
        from friday.connectors.sites.ride import DEFAULT_REVEAL

        t = DEFAULT_REVEAL.put("task-9", "4821")
        assert "4821" not in client.get(f"/ride/code/{t}").text  # a preview must not burn or show it
        assert "4821" in client.post(f"/ride/code/{t}").text
        assert client.post(f"/ride/code/{t}").status_code == 404
        assert client.get("/live/nonsense").status_code == 404
    finally:
        await w.c.aclose()
