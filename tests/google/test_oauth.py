"""OAuth: consent link, state, PKCE, encryption at rest, refresh, disconnect, isolation."""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from sqlalchemy import text

from friday.google import scopes as sc
from friday.google.oauth import (
    GoogleError,
    InvalidState,
    NeedsReconnect,
    NotConfigured,
    NotConnected,
    ScopeMissing,
    mask_email,
)
from tests.google.conftest import connect_user
from tests.google.fake_google import CLIENT_ID, REDIRECT


async def test_happy_path_stores_connection(oauth, fake, alice, gcontainer):
    res = await connect_user(oauth, fake, alice.id)
    assert res.user_id == alice.id and res.email_masked == "a***@gmail.com"
    assert sc.CALENDAR_EVENTS in res.scopes and sc.GMAIL_READONLY in res.scopes
    conn = await gcontainer.repos.google.get(alice.id)
    assert conn is not None and conn.status == "connected"
    assert conn.refresh_token.startswith("1//") and conn.access_token.startswith("ya29.")
    assert conn.email == "alice.example@gmail.com"
    st = await oauth.status(alice.id)
    assert st.connected and st.gmail and st.email_masked == "a***@gmail.com"


async def test_consent_request_parameters(oauth, fake, alice):
    await connect_user(oauth, fake, alice.id)
    q = fake.authorize_params[0]
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["include_granted_scopes"] == "false"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT
    assert set(q["scope"].split()) <= sc.ALLOWED_SCOPES
    assert "client_secret" not in q and "test-client-secret-value" not in str(q)


async def test_gmail_switch_off_does_not_request_gmail(gsettings, gcontainer, fake, gclock, alice):
    from friday.google.oauth import GoogleOAuth

    off = gsettings.model_copy(update={"google_gmail_enabled": False})
    o = GoogleOAuth(off, gcontainer.repos.google, clock=gclock, http=fake.client_factory())
    res = await connect_user(o, fake, alice.id)
    assert sc.GMAIL_READONLY not in fake.authorize_params[0]["scope"]
    assert sc.GMAIL_READONLY not in res.scopes


async def test_link_points_to_friday_consent_page(oauth, alice):
    start = await oauth.start(alice.id)
    assert start.link.startswith("https://friday.example/google/consent/")
    assert start.expires_at == oauth.clock.now() + timedelta(minutes=10)


async def test_not_configured(gsettings, gcontainer, alice):
    from friday.google.oauth import GoogleOAuth

    bare = gsettings.model_copy(update={"google_oauth_client_id": None})
    with pytest.raises(NotConfigured):
        await GoogleOAuth(bare, gcontainer.repos.google).start(alice.id)


# ------------------------------------------------------------------ state
async def _pending(oauth, fake, user_id):
    start = await oauth.start(user_id)
    state = start.link.rsplit("/", 1)[1]
    code, st = fake.user_clicks_allow(await oauth.consent_url(state))
    return code, st


async def test_tampered_state_rejected(oauth, fake, alice):
    code, st = await _pending(oauth, fake, alice.id)
    body, sig = st.split(".")
    for bad in (f"{body}.{sig[:-2]}xx", f"{body}x.{sig}", "garbage", "", f"{sig}.{body}"):
        with pytest.raises(InvalidState):
            await oauth.handle_callback(bad, code)


async def test_state_bound_to_user(oauth, fake, alice, bob):
    """A state signed for Alice cannot be re-labelled as Bob's."""
    code, st = await _pending(oauth, fake, alice.id)
    body, sig = st.split(".")
    payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    forged = payload.replace(alice.id, bob.id, 1)
    forged_body = base64.urlsafe_b64encode(forged.encode()).decode().rstrip("=")
    with pytest.raises(InvalidState):
        await oauth.handle_callback(f"{forged_body}.{sig}", code)


async def test_expired_state_rejected(oauth, fake, alice, gclock):
    code, st = await _pending(oauth, fake, alice.id)
    gclock.advance(601)
    with pytest.raises(InvalidState):
        await oauth.handle_callback(st, code)
    assert await oauth.repo.get(alice.id) is None


async def test_consent_page_dead_after_expiry(oauth, alice, gclock):
    start = await oauth.start(alice.id)
    state = start.link.rsplit("/", 1)[1]
    assert await oauth.consent_url(state) is not None
    gclock.advance(601)
    assert await oauth.consent_url(state) is None


async def test_state_is_single_use(oauth, fake, alice):
    code, st = await _pending(oauth, fake, alice.id)
    await oauth.handle_callback(st, code)
    with pytest.raises(InvalidState):
        await oauth.handle_callback(st, code)
    assert await oauth.consent_url(st) is None  # consent page also dead


async def test_verifier_wiped_after_use(oauth, fake, alice, gcontainer):
    code, st = await _pending(oauth, fake, alice.id)
    await oauth.handle_callback(st, code)
    async with gcontainer.db.session() as s:
        sql = text("select code_verifier, used_at from google_oauth_states")
        rows = (await s.execute(sql)).all()
    assert rows and rows[0][0] is None and rows[0][1] is not None


async def test_pkce_is_checked_by_google(oauth, fake, alice):
    code, st = await _pending(oauth, fake, alice.id)
    fake.codes[code]["challenge"] = "A" * 43  # as if the verifier did not match
    with pytest.raises(GoogleError) as e:
        await oauth.handle_callback(st, code)
    assert e.value.code == "invalid_grant"
    assert await oauth.repo.get(alice.id) is None


async def test_calendar_not_granted_is_refused_and_revoked(oauth, fake, alice):
    fake.grant_override = ["openid", "email", sc.GMAIL_READONLY]  # user unticked calendar
    start = await oauth.start(alice.id)
    state = start.link.rsplit("/", 1)[1]
    code, st = fake.user_clicks_allow(await oauth.consent_url(state))
    with pytest.raises(ScopeMissing):
        await oauth.handle_callback(st, code)
    assert await oauth.repo.get(alice.id) is None
    assert fake.revoked  # what Google issued is handed back


async def test_missing_refresh_token_is_refused(oauth, fake, alice):
    fake.omit_refresh_token = True
    code, st = await _pending(oauth, fake, alice.id)
    with pytest.raises(ScopeMissing) as e:
        await oauth.handle_callback(st, code)
    assert e.value.code == "no_refresh_token" and await oauth.repo.get(alice.id) is None


async def test_unexpected_scopes_are_not_stored(oauth, fake, alice):
    fake.grant_override = [*sc.requested_scopes(True), "https://www.googleapis.com/auth/drive"]
    res = await connect_user(oauth, fake, alice.id)
    assert set(res.scopes) <= sc.ALLOWED_SCOPES


async def test_reconnect_replaces_row(oauth, fake, alice, gcontainer):
    await connect_user(oauth, fake, alice.id)
    first = await gcontainer.repos.google.get(alice.id)
    await connect_user(oauth, fake, alice.id)
    second = await gcontainer.repos.google.get(alice.id)
    assert second.refresh_token != first.refresh_token
    async with gcontainer.db.session() as s:
        assert (await s.execute(text("select count(*) from google_connections"))).scalar() == 1


# ------------------------------------------------------------------ encryption + logs
async def test_tokens_encrypted_at_rest(oauth, fake, alice, gcontainer):
    await connect_user(oauth, fake, alice.id)
    conn = await gcontainer.repos.google.get(alice.id)
    async with gcontainer.db.session() as s:
        row = (
            await s.execute(
                text(
                    "select refresh_token, access_token, email, google_sub_hmac "
                    "from google_connections"
                )
            )
        ).one()
    for raw in row:
        assert conn.refresh_token not in raw and conn.access_token not in raw
        assert "alice.example" not in raw and "sub-alice" not in raw
    assert all(v.startswith("v1:") for v in row[:3])  # AES-GCM envelope, not plaintext
    assert len(row[3]) == 64  # blind index of the Google account id


async def test_aad_binds_ciphertext_to_its_column(oauth, fake, alice, gcontainer):
    """A refresh-token ciphertext copied into the access_token column cannot be read."""
    from friday.core.crypto import DecryptionError

    await connect_user(oauth, fake, alice.id)
    async with gcontainer.db.session() as s:
        await s.execute(text("update google_connections set access_token = refresh_token"))
    with pytest.raises(DecryptionError):
        await gcontainer.repos.google.get(alice.id)


async def test_tokens_never_in_logs_or_repr(oauth, fake, alice, gcontainer, log_capture, gclock):
    await connect_user(oauth, fake, alice.id)
    gclock.advance(4000)
    await oauth.access_token(alice.id)  # refresh
    fake.fail_refresh = True
    gclock.advance(4000)
    with pytest.raises(NeedsReconnect):
        await oauth.access_token(alice.id)
    await oauth.disconnect(alice.id)
    secrets_seen = fake.all_tokens_seen() | set(fake.revoked) | {"test-client-secret-value"}
    for rec in log_capture.records:
        msg = rec.getMessage()
        for t in secrets_seen:
            assert t not in msg
    assert "ya29." not in log_capture.text and "1//" not in log_capture.text
    assert "alice.example" not in log_capture.text
    conn_repr = repr(
        await gcontainer.repos.google.get(alice.id) or "gone"
    )
    assert "1//" not in conn_repr and "ya29" not in conn_repr


async def test_dataclass_repr_hides_tokens():
    from friday.db.repositories.google import GoogleConnection

    c = GoogleConnection(
        "u", "h", None, [], "connected", refresh_token="SECRET-R", access_token="SECRET-A"
    )
    assert "SECRET" not in repr(c)


# ------------------------------------------------------------------ refresh
async def test_access_token_reused_until_margin(oauth, fake, alice, gclock):
    await connect_user(oauth, fake, alice.id)
    t1 = await oauth.access_token(alice.id)
    gclock.advance(3000)  # 599s left, margin is 120s
    assert await oauth.access_token(alice.id) == t1
    assert sum(1 for r in fake.requests if r["path"] == "/token") == 1


async def test_refresh_on_expiry_with_margin(oauth, fake, alice, gclock, gcontainer):
    await connect_user(oauth, fake, alice.id)
    t1 = await oauth.access_token(alice.id)
    gclock.advance(3599 - 100)  # inside the 120 s margin: refresh before it dies
    t2 = await oauth.access_token(alice.id)
    assert t2 != t1 and t2.startswith("ya29.")
    refresh_calls = [r for r in fake.requests if "grant_type=refresh_token" in r["body"]]
    assert len(refresh_calls) == 1
    conn = await gcontainer.repos.google.get(alice.id)
    assert conn.access_token == t2 and conn.status == "connected"
    assert conn.last_used_at is not None


async def test_refresh_failure_marks_needs_reconnect(oauth, fake, alice, gclock):
    await connect_user(oauth, fake, alice.id)
    gclock.advance(4000)
    fake.fail_refresh = True
    with pytest.raises(NeedsReconnect):
        await oauth.access_token(alice.id)
    st = await oauth.status(alice.id)
    assert st.status == "needs_reconnect" and not st.connected
    fake.fail_refresh = False
    with pytest.raises(NeedsReconnect):  # stays down until the user reconnects
        await oauth.access_token(alice.id)
    conn = await oauth.repo.get(alice.id)
    assert conn.access_token is None  # dead access token dropped
    await connect_user(oauth, fake, alice.id)  # reconnecting heals it
    assert (await oauth.status(alice.id)).connected


async def test_not_connected(oauth, alice):
    with pytest.raises(NotConnected):
        await oauth.access_token(alice.id)
    st = await oauth.status(alice.id)
    assert not st.connected and st.status == "not_connected" and st.email_masked is None


async def test_scope_not_granted_blocks_use(oauth, fake, alice):
    await connect_user(oauth, fake, alice.id)
    await oauth.access_token(alice.id, scope=sc.CALENDAR_EVENTS)
    # pretend an old connection without Gmail
    conn = await oauth.repo.get(alice.id)
    conn.scopes = list(sc.BASE_SCOPES)
    await oauth.repo.upsert(conn)
    with pytest.raises(ScopeMissing):
        await oauth.access_token(alice.id, scope=sc.GMAIL_READONLY)


# ------------------------------------------------------------------ disconnect
async def test_disconnect_revokes_and_deletes(oauth, fake, alice, gcontainer):
    await connect_user(oauth, fake, alice.id)
    conn = await oauth.repo.get(alice.id)
    res = await oauth.disconnect(alice.id)
    assert res.deleted and res.revoked
    assert fake.revoked == [conn.refresh_token]
    assert await oauth.repo.get(alice.id) is None
    async with gcontainer.db.session() as s:
        for table in ("google_connections", "google_oauth_states"):
            assert (await s.execute(text(f"select count(*) from {table}"))).scalar() == 0
    assert not (await oauth.status(alice.id)).connected


async def test_disconnect_deletes_rows_even_if_revoke_fails(oauth, fake, alice):
    await connect_user(oauth, fake, alice.id)
    fake.revoke_status = 500
    res = await oauth.disconnect(alice.id)
    assert res.deleted and not res.revoked
    assert await oauth.repo.get(alice.id) is None


async def test_disconnect_when_google_unreachable(
    oauth, fake, alice, gsettings, gcontainer, gclock
):
    import httpx

    from friday.google.oauth import GoogleOAuth

    await connect_user(oauth, fake, alice.id)

    def down() -> httpx.AsyncClient:
        def boom(request):
            raise httpx.ConnectError("down")

        return httpx.AsyncClient(transport=httpx.MockTransport(boom))

    o = GoogleOAuth(gsettings, gcontainer.repos.google, clock=gclock, http=down)
    res = await o.disconnect(alice.id)
    assert res.deleted and not res.revoked


async def test_disconnect_twice_is_harmless(oauth, fake, alice):
    await connect_user(oauth, fake, alice.id)
    await oauth.disconnect(alice.id)
    res = await oauth.disconnect(alice.id)
    assert not res.deleted and not res.revoked


async def test_disconnect_also_kills_pending_links(oauth, fake, alice):
    start = await oauth.start(alice.id)
    state = start.link.rsplit("/", 1)[1]
    await oauth.disconnect(alice.id)
    assert await oauth.consent_url(state) is None


# ------------------------------------------------------------------ isolation
async def test_users_are_isolated(oauth, fake, alice, bob, gcontainer):
    await connect_user(oauth, fake, alice.id, "alice")
    await connect_user(oauth, fake, bob.id, "bob")
    a, b = await oauth.repo.get(alice.id), await oauth.repo.get(bob.id)
    assert a.google_sub_hmac != b.google_sub_hmac and a.refresh_token != b.refresh_token
    assert (await oauth.status(bob.id)).email_masked == "b***@gmail.com"
    await oauth.disconnect(alice.id)
    assert await oauth.repo.get(bob.id) is not None  # Bob untouched
    assert await oauth.repo.get("someone-else") is None


async def test_erasure_deletes_google_rows(oauth, fake, alice, gcontainer):
    await connect_user(oauth, fake, alice.id)
    await oauth.start(alice.id)
    await gcontainer.repos.purger.purge_user(alice.id)
    async with gcontainer.db.session() as s:
        for table in ("google_connections", "google_oauth_states"):
            assert (await s.execute(text(f"select count(*) from {table}"))).scalar() == 0


def test_mask_email():
    assert mask_email("rahul@example.com") == "r***@example.com"
    assert mask_email(None) is None and mask_email("nonsense") is None


def test_schema_and_rls_files_cover_google_tables():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "deploy" / "supabase"
    schema, rls = (root / "schema.sql").read_text(), (root / "rls.sql").read_text()
    for table in ("google_connections", "google_oauth_states"):
        assert f"CREATE TABLE {table}" in schema
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in rls
