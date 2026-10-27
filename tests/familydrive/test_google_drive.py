"""The real Drive v3 adapter, driven against the FAKE Google (ASGI transport: no sockets).

Covers the consent scope, the REST calls Friday makes (multipart streamed upload, appProperties
lookup, permissions), token handling and the full FamilyDrive flow over the adapter."""

from __future__ import annotations

import json

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.models import User
from friday.db import Database
from friday.db.repositories import make_repositories
from friday.familydrive.factory import build_family_drive
from friday.familydrive.google_drive import GoogleDrive
from friday.familydrive.ports import (
    DriveError,
    DriveNeedsReconnect,
    DriveNotLinked,
    DriveScopeMissing,
    DriveUnreachable,
)
from friday.google import scopes as sc
from friday.google.oauth import GoogleOAuth
from tests.familydrive.conftest import PDF, make_doc
from tests.google.fake_google import FakeGoogle, settings_overrides


def _settings(drive: bool) -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        family_drive_enabled=drive,
        family_drive_sharing_enabled=True,
        **settings_overrides(),
    )


@pytest.fixture
def fake() -> FakeGoogle:
    f = FakeGoogle()
    f.add_account("alice", "alice.example@gmail.com")
    f.add_account("bob", "bob.example@gmail.com")
    return f


@pytest.fixture
def clock() -> FakeClock:
    from datetime import datetime

    return FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))


@pytest.fixture
async def gdb():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_all()
    yield database
    await database.dispose()


@pytest.fixture
def repos(gdb, clock):
    return make_repositories(gdb, clock, "test-secret")


@pytest.fixture
async def alice(repos) -> User:
    return await repos.users.add(User(phone="+919800000301"))


@pytest.fixture
async def bob(repos) -> User:
    return await repos.users.add(User(phone="+919800000302"))


async def connect(repos, fake, clock, settings, user_id, account="alice") -> GoogleOAuth:
    oauth = GoogleOAuth(settings, repos.google, clock=clock, http=fake.client_factory())
    start = await oauth.start(user_id)
    url = await oauth.consent_url(start.link.rsplit("/", 1)[1])
    code, st = fake.user_clicks_allow(url, account)
    await oauth.handle_callback(st, code)
    return oauth


def adapter(oauth, user_id, settings, fake) -> GoogleDrive:
    return GoogleDrive(oauth, user_id, settings=settings, http=fake.client_factory())


# ----------------------------------------------------------------------------- consent / scope


def test_drive_scope_only_with_the_switch():
    assert sc.DRIVE_FILE == "https://www.googleapis.com/auth/drive.file"
    assert sc.DRIVE_FILE not in sc.requested_scopes(True)
    assert sc.requested_scopes(False, True)[-1] == sc.DRIVE_FILE


async def test_consent_asks_for_drive_file_when_on_and_not_otherwise(
    repos, fake, clock, alice, bob
):
    on, off = _settings(True), _settings(False)
    await connect(repos, fake, clock, on, alice.id)
    await connect(repos, fake, clock, off, bob.id, "bob")
    asked_on, asked_off = fake.authorize_params[0]["scope"], fake.authorize_params[1]["scope"]
    assert sc.DRIVE_FILE in asked_on.split() and sc.DRIVE_FILE not in asked_off.split()
    assert "https://www.googleapis.com/auth/drive " not in asked_on + " "  # never the full scope
    st = await GoogleOAuth(on, repos.google, clock=clock).status(alice.id)
    assert st.drive is True
    assert (await GoogleOAuth(off, repos.google, clock=clock).status(bob.id)).drive is False


async def test_consent_page_carries_the_pending_drive_paragraph():
    from friday.google import consent_copy as cc

    assert cc.PENDING_FOUNDER_APPROVAL
    assert any("Drive" in x for x in cc.consent_lines(False, True))
    assert not any("Drive" in x for x in cc.consent_lines(False, False))
    html = cc.consent_body_html("https://example.test/x", gmail_enabled=False, drive_enabled=True)
    assert "only the files and folders Friday itself creates" in html


async def test_a_user_who_unticked_drive_gets_scope_missing(repos, fake, clock, alice):
    s = _settings(True)
    fake.grant_override = ["openid", "email", sc.CALENDAR_EVENTS]  # the user unticked Drive
    oauth = await connect(repos, fake, clock, s, alice.id)
    with pytest.raises(DriveScopeMissing):
        await adapter(oauth, alice.id, s, fake).find_by_key("k1")
    assert not any(r["path"].startswith("/drive") for r in fake.requests)  # no call was made


async def test_no_connection_is_not_linked(repos, fake, clock, alice):
    s = _settings(True)
    oauth = GoogleOAuth(s, repos.google, clock=clock, http=fake.client_factory())
    with pytest.raises(DriveNotLinked):
        await adapter(oauth, alice.id, s, fake).get("abc")


# ----------------------------------------------------------------------------- REST behaviour


async def test_folder_lookup_upload_download_trash_share(repos, fake, clock, alice):
    s = _settings(True)
    oauth = await connect(repos, fake, clock, s, alice.id)
    d = adapter(oauth, alice.id, s, fake)
    root = await d.create_folder("Friday", None, key="rootkey")
    sub = await d.create_folder("Tickets", root.id, key="subkey")
    assert (await d.find_by_key("subkey")).id == sub.id
    assert (await d.find_by_key("subkey", parent_id=root.id)).id == sub.id
    assert await d.find_by_key("subkey", parent_id=sub.id) is None
    assert any("appProperties has" in q and "friday_key" in q for q in fake.drive_queries)
    f = await d.upload("2026-11-14 DEL-GOI IndiGo.pdf", PDF, "application/pdf", sub.id, key="fk1")
    assert f.size == len(PDF) and f.parent_id == sub.id and f.mime == "application/pdf"
    up = fake.uploads[0]  # streamed with an explicit length, multipart/related
    assert up["ctype"].startswith("multipart/related") and int(up["content_length"]) == up["size"]
    assert await d.download(f.id) == PDF
    pid = await d.share(root.id, "mom.example@gmail.com", "viewer")
    sub_ = fake.accounts["alice"]["sub"]
    assert fake.drive[sub_][root.id]["perms"][pid] == ("mom.example@gmail.com", "reader")
    await d.unshare(root.id, pid)
    assert fake.drive[sub_][root.id]["perms"] == {}
    await d.trash(f.id)
    assert (await d.get(f.id)).trashed
    assert await d.find_by_key("fk1") is None  # trashed files are not found
    assert await d.get("does-not-exist") is None
    await d.trash("does-not-exist")  # already gone: not an error


async def test_bad_ids_and_keys_never_reach_google(repos, fake, clock, alice):
    s = _settings(True)
    oauth = await connect(repos, fake, clock, s, alice.id)
    d = adapter(oauth, alice.id, s, fake)
    n = len(fake.requests)
    for coro in (
        d.find_by_key("k' or name contains 'x"),
        d.get("a/b"),
        d.get("x' in parents"),
        d.share("ok", "a@b.com", "owner"),
    ):
        with pytest.raises(DriveError):
            await coro
    assert len(fake.requests) == n


async def test_expired_access_token_is_refreshed_once(repos, fake, clock, alice):
    s = _settings(True)
    oauth = await connect(repos, fake, clock, s, alice.id)
    d = adapter(oauth, alice.id, s, fake)
    fake.expire_access_tokens()
    assert (await d.create_folder("Friday", None, key="k")).name == "Friday"
    assert sum(1 for r in fake.requests if r["path"] == "/token") == 2  # code exchange + refresh


async def test_revoked_grant_means_needs_reconnect(repos, fake, clock, alice):
    s = _settings(True)
    oauth = await connect(repos, fake, clock, s, alice.id)
    d = adapter(oauth, alice.id, s, fake)
    fake.expire_access_tokens()
    fake.fail_refresh = True
    with pytest.raises(DriveNeedsReconnect):
        await d.get("x")
    assert (await oauth.status(alice.id)).status == "needs_reconnect"


async def test_server_errors_are_unreachable_and_rejections_are_rejections(
    repos, fake, clock, alice
):
    s = _settings(True)
    oauth = await connect(repos, fake, clock, s, alice.id)
    d = adapter(oauth, alice.id, s, fake)
    root = await d.create_folder("Friday", None, key="k")
    fake.upload_status = 503
    with pytest.raises(DriveUnreachable):
        await d.upload("a.pdf", PDF, "application/pdf", root.id, key="u")
    fake.upload_status = 403
    with pytest.raises(DriveError) as e:
        await d.upload("a.pdf", PDF, "application/pdf", root.id, key="u")
    assert e.value.code == "http_403" and not isinstance(e.value, DriveUnreachable)
    with pytest.raises(DriveError):
        await d.upload("a.pdf", b"x" * (9 * 1024 * 1024), "application/pdf", root.id, key="u")


async def test_a_second_user_cannot_see_the_first_users_files(repos, fake, clock, alice, bob):
    s = _settings(True)
    oa = await connect(repos, fake, clock, s, alice.id)
    ob = await connect(repos, fake, clock, s, bob.id, "bob")
    da, db_ = adapter(oa, alice.id, s, fake), adapter(ob, bob.id, s, fake)
    root = await da.create_folder("Friday", None, key="k")
    assert await db_.get(root.id) is None and await db_.find_by_key("k") is None
    with pytest.raises(DriveError):
        await db_.create_folder("x", root.id, key="z")  # alice's folder is not bob's parent


# ----------------------------------------------------------------------------- whole flow


async def test_full_flow_over_the_real_adapter(repos, fake, clock, alice, log_capture):
    s = _settings(True)
    await connect(repos, fake, clock, s, alice.id)
    svc = build_family_drive(s, repos, clock=clock, http=fake.client_factory())
    info = await svc.link(alice.id)
    again = await svc.link(alice.id)
    assert info.root_link == again.root_link
    doc = make_doc(alice.id, clock)
    await repos.documents.save(doc)
    out = await svc.file_document(alice.id, doc.id, PDF, trip="Goa")
    assert out.path == "Friday/Trips/Goa/Tickets"
    sub_ = fake.accounts["alice"]["sub"]
    files = [o for o in fake.drive[sub_].values() if o["mime"] == "application/pdf"]
    assert len(files) == 1 and files[0]["data"] == PDF
    assert [h.document_id for h in await svc.where_is(alice.id, "ticket")] == [doc.id]
    req = await svc.request_share(alice.id, "mom.example@gmail.com")
    await svc.approve_share(alice.id, req.id)
    root = next(o for o in fake.drive[sub_].values() if o["name"] == "Friday")
    assert list(root["perms"].values()) == [("mom.example@gmail.com", "reader")]
    folders_before = sum(1 for o in fake.drive[sub_].values() if o["mime"].endswith("folder"))
    await svc.ensure_tree(alice.id, trip="Goa")
    await svc.ensure_tree(alice.id, trip="Goa")
    folders_after = sum(1 for o in fake.drive[sub_].values() if o["mime"].endswith("folder"))
    assert folders_after - folders_before == 3  # Hotel, Insurance, Bills; none duplicated
    res = await svc.disconnect(alice.id)
    assert res.pointers == 1 and files[0]["trashed"] is False  # the user's file is untouched
    assert (await svc.status(alice.id)).state == "not_linked"
    # no token, no file bytes and no personal value in any log line
    logs = " ".join(r.getMessage() for r in log_capture.records)
    assert not any(t in logs for t in fake.all_tokens_seen())
    assert "ABC123" not in logs and "IndiGo" not in logs and "mom.example" not in logs
    # the Drive requests never carried the file text in a URL or query
    assert all("INVENTED" not in json.dumps(r) for r in fake.requests)
