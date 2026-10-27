"""Fixtures: family Drive switched on (fakes only), two users, confirmed documents.

No real document or personal data anywhere: names, e-mails and numbers are invented."""

from __future__ import annotations

import hashlib
import logging

import pytest

from friday.core.config import Settings
from friday.core.models import User
from friday.db.repositories import make_repositories
from friday.docunderstand.models import DocField, DocStatus, DocType, Document
from friday.familydrive.fake import FakeDriveHub
from friday.familydrive.service import FamilyDrive

PDF = b"%PDF-1.4\n% invented test file, not a real document\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0 invented test image bytes"


@pytest.fixture
def dsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"family_drive_enabled": True, "family_drive_sharing_enabled": True}
    )


@pytest.fixture
def repos(db, clock):
    return make_repositories(db, clock, "test-secret")


@pytest.fixture
def hub() -> FakeDriveHub:
    return FakeDriveHub()


@pytest.fixture
def svc(dsettings, repos, hub, clock) -> FamilyDrive:
    return FamilyDrive(dsettings, repos, hub.factory, clock=clock)


@pytest.fixture
async def alice(repos) -> User:
    return await repos.users.add(User(phone="+919800000201"))


@pytest.fixture
async def bob(repos) -> User:
    return await repos.users.add(User(phone="+919800000202"))


def make_doc(
    user_id: str,
    clock,
    *,
    doc_type: DocType = DocType.FLIGHT,
    data: bytes = PDF,
    status: DocStatus = DocStatus.CONFIRMED,
    fields: dict[str, str] | None = None,
) -> Document:
    values = fields or {
        "airline": "IndiGo",
        "from_iata": "DEL",
        "to_iata": "GOI",
        "dep_local": "2026-11-14T06:30",
        "pnr": "ABC123",
    }
    return Document(
        user_id=user_id,
        doc_type=doc_type,
        status=status,
        mime="application/pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        fields={k: DocField(value=v, confidence=0.95, confirmed=True) for k, v in values.items()},
        created_at=clock.now(),
        confirmed_at=clock.now(),
    )


@pytest.fixture
def mk(repos, clock):
    async def _mk(user_id: str, **kw) -> Document:  # noqa: ANN003
        doc = make_doc(user_id, clock, **kw)
        await repos.documents.save(doc)
        return doc

    return _mk


@pytest.fixture
def log_capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG)
    return caplog
