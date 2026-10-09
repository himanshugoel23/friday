"""The hook on the event bus, the admin endpoints and the migration."""

from __future__ import annotations

import httpx

from friday.api.admin import admin_token
from friday.api.app import create_app
from friday.quality.hook import install_quality_hook
from friday.voice.frontdoor import FrontDoorCallFinished
from tests.quality.conftest import make_call, make_user


async def test_hook_stores_a_consented_call_published_on_the_bus(app, store):
    assert not install_quality_hook(app.c)  # Runtime already installed it
    await make_user(app)
    summary, result = make_call()
    await app.c.bus.publish(FrontDoorCallFinished(summary=summary, result=result))
    assert await store.get("call-1") is not None


async def test_hook_stores_nothing_without_consent_and_never_raises(app, store):
    await make_user(app, consent=False)
    summary, result = make_call()
    await app.c.bus.publish(FrontDoorCallFinished(summary=summary, result=result))
    await app.c.bus.publish(FrontDoorCallFinished(summary=summary, result=None))
    assert await store.count() == 0


async def test_install_is_idempotent():
    from friday.core.container import Container
    from tests.e2e.harness import make_settings

    c = Container(make_settings())
    assert install_quality_hook(c) and not install_quality_hook(c)
    await c.aclose()


async def test_whole_call_through_the_real_front_door_is_stored_when_consented(tmp_path):
    """End to end: a returning (consented) caller phones in; the transcript lands in the store."""
    from friday.quality.harness import CALLER, FRIDAY_NUMBER, ScriptedLeg
    from friday.quality.scenarios import parse_scenario
    from friday.quality.store import TranscriptStore
    from tests.frontdoor.conftest import ring, start_friday

    f = await start_friday("pilot", (CALLER,))
    try:
        await f.onboard(CALLER, name="Rahul")
        sc = parse_scenario({"id": "x", "script": ["kya aap ek bot ho?", "nahi bas"]})
        await ring(f, CALLER, ScriptedLeg(sc.script), to=FRIDAY_NUMBER)
        calls = await TranscriptStore.from_container(f.c).recent()
        assert len(calls) == 1
        assert "AI assistant" in calls[0].transcript[0]["text"]
    finally:
        await f.close()


async def test_whole_call_from_an_unconsented_stranger_is_not_stored():
    from friday.quality.harness import CALLER, FRIDAY_NUMBER, ScriptedLeg
    from friday.quality.scenarios import parse_scenario
    from friday.quality.store import TranscriptStore
    from tests.frontdoor.conftest import ring, start_friday

    f = await start_friday("pilot", (CALLER,))
    try:
        sc = parse_scenario({"id": "x", "script": ["Asha", "English", "no"]})
        await ring(f, CALLER, ScriptedLeg(sc.script), to=FRIDAY_NUMBER)
        assert await TranscriptStore.from_container(f.c).count() == 0
    finally:
        await f.close()


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_admin_rating_and_listing(tmp_path):
    from friday.core.container import Container
    from friday.quality.store import TranscriptStore
    from tests.e2e.harness import make_settings

    s = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/q.db")
    c = Container(s)
    await c.db.create_all()
    app = create_app(c, background=False, fast_pin_hash=True)
    h = {"Authorization": f"Bearer {admin_token(s)}"}

    class _F:  # minimal stand-in for the e2e driver: make_user only needs ``.c``
        pass

    f = _F()
    f.c = c
    await make_user(f)
    await TranscriptStore.from_container(c).capture(*make_call())
    async with app.router.lifespan_context(app), _client(app) as cl:
        assert (await cl.post("/admin/quality/rating", json={"call_id": "call-1", "rating": 4})
                ).status_code == 401  # admin token required
        body = {"call_id": "call-1", "rating": 4}
        ok = await cl.post("/admin/quality/rating", json=body, headers=h)
        assert ok.status_code == 200
        down = {"call_id": "call-1", "rating": "down"}
        up = await cl.post("/admin/quality/rating", json=down, headers=h)
        assert up.status_code == 200
        assert (await cl.post("/admin/quality/rating", json={"call_id": "nope", "rating": 4},
                              headers=h)).status_code == 404
        assert (await cl.post("/admin/quality/rating", json={"call_id": "call-1", "rating": 9},
                              headers=h)).status_code == 422
        listing = (await cl.get("/admin/quality/calls", headers=h)).json()["calls"]
        assert listing[0]["call_id"] == "call-1" and listing[0]["rating"] == 1
        assert "transcript" not in listing[0]  # transcripts never leave through the API
    await c.aclose()


def test_migration_creates_the_table(tmp_path):
    from sqlalchemy import create_engine, inspect

    from friday.db import migrate

    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    cols = {c["name"] for c in inspect(create_engine(f"sqlite:///{tmp_path}/m.db")).get_columns("quality_calls")}
    assert {"call_id", "user_id", "expires_at", "transcript", "labels", "note", "rating"} <= cols
