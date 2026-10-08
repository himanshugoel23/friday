"""POST /admin/livecall + GET /admin/livecall/last: pilot profile only, offline (simulator)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from friday.api.admin import admin_token
from friday.api.app import create_app
from friday.core.config import Settings
from friday.core.container import Container

OWN = "+919812345678"


def _settings(tmp_path, **kw) -> Settings:
    base = dict(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
        media_dir=str(tmp_path / "m"),
    )
    base.update(kw)
    return Settings(**base)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _h(s: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token(s)}"}


async def test_not_mounted_outside_pilot(tmp_path):
    for profile in ("default", "beta"):
        app = create_app(Container(_settings(tmp_path, profile=profile)), background=False)
        paths = set(app.openapi()["paths"])
        assert "/admin/livecall" not in paths and "/admin/livecall/last" not in paths
        async with _client(app) as cl:
            r = await cl.post("/admin/livecall", json={"to": OWN})
            assert r.status_code in (404, 405)


async def test_requires_admin_token(tmp_path):
    s = _settings(tmp_path, profile="pilot")
    app = create_app(Container(s), background=False, fast_pin_hash=True)
    async with _client(app) as cl:
        assert (await cl.post("/admin/livecall", json={"to": OWN})).status_code == 401
        assert (await cl.get("/admin/livecall/last")).status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert (await cl.post("/admin/livecall", json={"to": OWN}, headers=bad)).status_code == 401


async def test_simulated_call_returns_summary_and_last(tmp_path):
    s = _settings(tmp_path, profile="pilot")
    app = create_app(Container(s), background=False, fast_pin_hash=True)
    async with app.router.lifespan_context(app), _client(app) as cl:
        r = await cl.get("/admin/livecall/last", headers=_h(s))
        assert r.json() == {"in_progress": False, "last": None}
        r = await cl.post("/admin/livecall", json={"to": OWN, "max_seconds": 60}, headers=_h(s))
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("outcome", "duration_s", "languages", "estimated_cost_inr", "transcript_path"):
            assert k in body
        assert OWN not in r.text
        last = (await cl.get("/admin/livecall/last", headers=_h(s))).json()
        assert last["in_progress"] is False and last["last"]["outcome"] == body["outcome"]
        assert list((tmp_path / "m" / "livecalls").glob("livecall-*.txt"))
        assert not (tmp_path / "m" / "livecalls" / "livecall.lock").exists()


async def test_limits_enforced(tmp_path):
    s = _settings(tmp_path, profile="pilot", pilot_max_spend_inr=5.0)
    app = create_app(Container(s), background=False, fast_pin_hash=True)
    async with _client(app) as cl:
        h = _h(s)
        assert (await cl.post("/admin/livecall", json={"to": OWN, "max_seconds": 999},
                              headers=h)).status_code == 422
        assert (await cl.post("/admin/livecall", json={"to": OWN, "max_seconds": 5},
                              headers=h)).status_code == 422
        r = await cl.post("/admin/livecall", json={"to": OWN, "max_seconds": 120}, headers=h)
        assert r.status_code == 422 and "spend cap" in r.text


async def test_live_refuses_number_not_on_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ADMIN_TOKEN", "t" * 40)
    s = _settings(tmp_path, profile="pilot", mode="live", llm_provider="fake",
                  public_base_url="https://1-2-3-4.sslip.io",
                  sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
                  sarvam_caller_ids=["+918065354620"], sarvam_api_key="k",
                  secret_key="s" * 32, pin_pepper="p", field_key="f", index_key="i",
                  pilot_allowed_numbers=[OWN])
    app = create_app(Container(s), background=False, fast_pin_hash=True)
    async with _client(app) as cl:
        h = {"Authorization": "Bearer " + "t" * 40}
        r = await cl.post("/admin/livecall", json={"to": "+919000000000"}, headers=h)
        assert r.status_code == 403 and "allowed list" in r.text
        r = await cl.post("/admin/livecall", json={"to": "garbage"}, headers=h)
        assert r.status_code == 422


async def test_one_call_at_a_time(tmp_path):
    s = _settings(tmp_path, profile="pilot")
    c = Container(s)
    app = create_app(c, background=False, fast_pin_hash=True)
    gate = asyncio.Event()
    orig = c.call_runner.run

    async def slow(*a, **kw):
        await gate.wait()
        return await orig(*a, **kw)

    c.call_runner.run = slow  # type: ignore[method-assign]
    async with app.router.lifespan_context(app), _client(app) as cl:
        h = _h(s)
        first = asyncio.create_task(cl.post("/admin/livecall", json={"to": OWN}, headers=h))
        for _ in range(50):
            if (await cl.get("/admin/livecall/last", headers=h)).json()["in_progress"]:
                break
            await asyncio.sleep(0.02)
        r = await cl.post("/admin/livecall", json={"to": OWN}, headers=h)
        assert r.status_code == 409
        gate.set()
        assert (await first).status_code == 200


@pytest.mark.parametrize("path", ["/admin/livecall", "/admin/livecall/last"])
async def test_admin_disabled_in_live_without_token(tmp_path, monkeypatch, path):
    monkeypatch.delenv("FRIDAY_ADMIN_TOKEN", raising=False)
    s = _settings(tmp_path, profile="pilot", mode="live")
    app = create_app(Container(s), background=False)
    async with _client(app) as cl:
        r = await (cl.get(path) if path.endswith("last") else cl.post(path, json={"to": OWN}))
        assert r.status_code == 404
