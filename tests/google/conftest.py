"""Fixtures: Settings pointed at FakeGoogle, a user, oauth service, calendar/gmail clients."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import User, UserStatus
from friday.db import Database
from friday.google.oauth import GoogleOAuth
from tests.google.fake_google import FakeGoogle, settings_overrides


@pytest.fixture
def gsettings() -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        google_gmail_enabled=True,
        **settings_overrides(),
    )


@pytest.fixture
def fake() -> FakeGoogle:
    f = FakeGoogle()
    f.add_account("alice", "alice.example@gmail.com")
    f.add_account("bob", "bob.example@gmail.com")
    return f


@pytest.fixture
def gclock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))


@pytest.fixture
async def gdb(gsettings: Settings) -> AsyncIterator[Database]:
    database = Database(gsettings.database_url)
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
async def gcontainer(
    gsettings: Settings, gclock: FakeClock, gdb: Database
) -> AsyncIterator[Container]:
    c = Container(gsettings, clock=gclock)
    c.override_db(gdb)
    try:
        yield c
    finally:
        await c.aclose()


async def _make_user(c: Container, phone: str) -> User:
    return await c.repos.users.add(User(phone=phone, status=UserStatus.ACTIVE))


@pytest.fixture
async def alice(gcontainer: Container) -> User:
    return await _make_user(gcontainer, "+919800000101")


@pytest.fixture
async def bob(gcontainer: Container) -> User:
    return await _make_user(gcontainer, "+919800000102")


@pytest.fixture
def oauth(gcontainer: Container, gsettings: Settings, fake: FakeGoogle, gclock: FakeClock):
    return GoogleOAuth(
        gsettings, gcontainer.repos.google, clock=gclock, http=fake.client_factory()
    )


async def connect_user(oauth: GoogleOAuth, fake: FakeGoogle, user_id: str, account: str = "alice"):
    """Run the whole consent flow against the fake; returns the callback result."""
    start = await oauth.start(user_id)
    state = start.link.rsplit("/", 1)[1]
    url = await oauth.consent_url(state)
    assert url is not None
    code, st = fake.user_clicks_allow(url, account)
    return await oauth.handle_callback(st, code)


@pytest.fixture
def log_capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG)
    return caplog
