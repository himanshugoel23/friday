from __future__ import annotations

import os

import pytest

from friday.connectors.browser.backend import FakeBackend
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.session import (
    AuditLog,
    BrowserSettings,
    InMemoryVaultStore,
    LiveViewService,
    SessionManager,
    StorageVault,
)
from friday.core.crypto import FieldCipher, LocalKeyProvider

POLICY = NetworkPolicy.for_hosts({"fake.test", "*.fake.test"})


def make_cipher() -> FieldCipher:
    return FieldCipher(LocalKeyProvider({"k1": os.urandom(32)}, index_key=os.urandom(32)))


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def settings() -> BrowserSettings:
    return BrowserSettings(enabled=True, enabled_users="*", max_per_user=1, max_global=2,
                           backend="fake")


@pytest.fixture
def vault(clock) -> StorageVault:
    return StorageVault(InMemoryVaultStore(), make_cipher(), clock=clock)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def mgr(backend, vault, settings) -> SessionManager:
    return SessionManager(backend, vault, settings, audit=AuditLog())


@pytest.fixture
def live(mgr, clock) -> LiveViewService:
    return LiveViewService(mgr, clock=clock)
