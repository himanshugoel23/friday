"""Router: status codes, auth, consent page, callback, disconnect; no secrets in responses."""

from __future__ import annotations

import httpx
import pytest

from friday.api.admin import admin_token
from friday.api.app import create_app
from friday.google import consent_copy


@pytest.fixture
async def api(gcontainer, fake):
    app = create_app(gcontainer, background=False, fast_pin_hash=True)
    app.state.google_http_factory = fake.client_factory()
    token = admin_token(gcontainer.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://friday.example"
    ) as c:
        c.headers["authorization"] = f"Bearer {token}"
        yield c


def _state(link: str) -> str:
    return link.rsplit("/", 1)[1]


async def _consent_url(api, link: str) -> str:
    page = await api.get(link.replace("https://friday.example", ""))
    assert page.status_code == 200
    href = page.text.split('href="', 1)[1].split('"', 1)[0]
    return href.replace("&amp;", "&")


async def test_full_flow_over_http(api, fake, alice):
    r = await api.post("/google/connect", json={"user_id": alice.id})
    assert r.status_code == 200
    link = r.json()["link"]
    assert link.startswith("https://friday.example/google/consent/")

    url = await _consent_url(api, link)
    code, state = fake.user_clicks_allow(url)
    cb = await api.get("/google/callback", params={"code": code, "state": state})
    assert cb.status_code == 200 and "Google connected" in cb.text

    st = await api.get("/google/status", params={"user_id": alice.id})
    assert st.status_code == 200
    body = st.json()
    assert body["connected"] is True and body["status"] == "connected"
    assert body["email_masked"] == "a***@gmail.com" and body["gmail"] is True
    assert "https://www.googleapis.com/auth/calendar.events" in body["scopes"]
    assert body["drive"] is False  # FRIDAY_FAMILY_DRIVE_ENABLED is off: drive.file never asked
    assert set(body) == {"connected", "status", "scopes", "email_masked", "gmail", "drive"}

    # replaying the same callback fails
    again = await api.get("/google/callback", params={"code": code, "state": state})
    assert again.status_code == 400

    d = await api.post("/google/disconnect", json={"user_id": alice.id})
    assert d.status_code == 200 and d.json() == {"disconnected": True, "revoked": True}
    st2 = await api.get("/google/status", params={"user_id": alice.id})
    assert st2.json()["connected"] is False and st2.json()["status"] == "not_connected"
    d2 = await api.post("/google/disconnect", json={"user_id": alice.id})
    assert d2.status_code == 200 and d2.json()["disconnected"] is False


async def test_no_token_or_secret_in_any_response(api, fake, alice):
    texts: list[str] = []
    r = await api.post("/google/connect", json={"user_id": alice.id})
    texts.append(r.text)
    page = await api.get(r.json()["link"].replace("https://friday.example", ""))
    texts.append(page.text)
    code, state = fake.user_clicks_allow(await _consent_url(api, r.json()["link"]))
    cb = await api.get("/google/callback", params={"code": code, "state": state})
    texts += [cb.text, (await api.get("/google/status", params={"user_id": alice.id})).text]
    texts.append((await api.post("/google/disconnect", json={"user_id": alice.id})).text)
    blob = "\n".join(texts)
    for t in fake.all_tokens_seen() | set(fake.revoked):
        assert t not in blob
    assert "test-client-secret-value" not in blob and code not in blob
    assert "alice.example@gmail.com" not in blob  # only the masked form is ever returned


async def test_internal_routes_need_the_bearer_token(api, alice):
    api.headers.pop("authorization")
    assert (await api.post("/google/connect", json={"user_id": alice.id})).status_code == 401
    assert (await api.post("/google/disconnect", json={"user_id": alice.id})).status_code == 401
    assert (await api.get("/google/status", params={"user_id": alice.id})).status_code == 401
    api.headers["authorization"] = "Bearer wrong"
    assert (await api.post("/google/connect", json={"user_id": alice.id})).status_code == 401


async def test_connect_validation(api):
    assert (await api.post("/google/connect", json={"user_id": "nobody"})).status_code == 404
    assert (await api.post("/google/connect", json={})).status_code == 422


async def test_connect_503_when_not_configured(gcontainer, fake, alice):
    gcontainer.settings.google_oauth_client_id = None
    app = create_app(gcontainer, background=False, fast_pin_hash=True)
    token = admin_token(gcontainer.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://friday.example"
    ) as c:
        r = await c.post(
            "/google/connect", json={"user_id": alice.id},
            headers={"authorization": f"Bearer {token}"},
        )  # fmt: skip
        assert r.status_code == 503
        assert (await c.get("/google/consent/whatever")).status_code == 503


async def test_consent_page_copy_and_headers(api, alice):
    r = await api.post("/google/connect", json={"user_id": alice.id})
    page = await api.get(r.json()["link"].replace("https://friday.example", ""))
    assert page.status_code == 200
    low = page.text.lower()
    assert "read-only" in low and "disconnect any time" in low
    assert "never used for ads" in low
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in page.headers["x-robots-tag"]
    assert "default-src 'none'" in page.headers["content-security-policy"]


async def test_consent_copy_has_no_gmail_text_when_switched_off(gcontainer, fake, alice):
    gcontainer.settings.google_gmail_enabled = False
    app = create_app(gcontainer, background=False, fast_pin_hash=True)
    app.state.google_http_factory = fake.client_factory()
    token = admin_token(gcontainer.settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://friday.example"
    ) as c:
        h = {"authorization": f"Bearer {token}"}
        r = await c.post("/google/connect", json={"user_id": alice.id}, headers=h)
        link = r.json()["link"]
        page = await c.get(link.replace("https://friday.example", ""))
        assert "gmail" not in page.text.lower()
        assert "calendar" in page.text.lower() and "disconnect any time" in page.text.lower()


def test_copy_is_marked_pending_founder_approval():
    assert consent_copy.PENDING_FOUNDER_APPROVAL is True
    assert "PENDING FOUNDER APPROVAL" in consent_copy.__doc__
    assert "read-only" in " ".join(consent_copy.GMAIL_LINES).lower()
    assert "disconnect any time" in " ".join(consent_copy.ALWAYS_LINES).lower()


async def test_consent_page_unknown_expired_or_forged(api, alice, gclock):
    assert (await api.get("/google/consent/garbage")).status_code == 404
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    gclock.advance(601)
    assert (await api.get(link.replace("https://friday.example", ""))).status_code == 404


async def test_callback_rejections(api, fake, alice, bob):
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    code, state = fake.user_clicks_allow(await _consent_url(api, link))
    for params in (
        {"code": code, "state": "forged"},
        {"code": code},
        {"state": state},
        {},
    ):
        r = await api.get("/google/callback", params=params)
        assert r.status_code == 400, params
    st = await api.get("/google/status", params={"user_id": alice.id})
    assert st.json()["connected"] is False


async def test_user_declines_burns_the_link(api, fake, alice):
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    code, state = fake.user_clicks_allow(await _consent_url(api, link))
    r = await api.get("/google/callback", params={"error": "access_denied", "state": state})
    assert r.status_code == 400 and "Nothing was saved" in r.text
    r2 = await api.get("/google/callback", params={"code": code, "state": state})
    assert r2.status_code == 400  # the attempt is dead
    st = await api.get("/google/status", params={"user_id": alice.id})
    assert st.json()["connected"] is False


async def test_calendar_untick_gives_clear_page(api, fake, alice):
    fake.grant_override = ["openid", "email"]
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    code, state = fake.user_clicks_allow(await _consent_url(api, link))
    r = await api.get("/google/callback", params={"code": code, "state": state})
    assert r.status_code == 400 and "calendar" in r.text.lower()
    assert fake.revoked  # nothing kept at Google either


async def test_google_failure_is_502_without_details(api, fake, alice):
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    code, state = fake.user_clicks_allow(await _consent_url(api, link))
    fake.codes[code]["challenge"] = "B" * 43
    r = await api.get("/google/callback", params={"code": code, "state": state})
    assert r.status_code == 502 and "invalid_grant" not in r.text


async def test_disconnect_when_revoke_fails_still_deletes(api, fake, alice):
    link = (await api.post("/google/connect", json={"user_id": alice.id})).json()["link"]
    code, state = fake.user_clicks_allow(await _consent_url(api, link))
    await api.get("/google/callback", params={"code": code, "state": state})
    fake.revoke_status = 503
    d = await api.post("/google/disconnect", json={"user_id": alice.id})
    assert d.json() == {"disconnected": True, "revoked": False}
    st = await api.get("/google/status", params={"user_id": alice.id})
    assert st.json()["connected"] is False
