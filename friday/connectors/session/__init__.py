"""Private-browser runtime: isolated per-task sessions, vault, live view/takeover, kill switch."""

from __future__ import annotations

from friday.connectors.session.audit import AuditLog
from friday.connectors.session.killswitch import PauseWatcher, pause_probe
from friday.connectors.session.liveview import LiveViewService
from friday.connectors.session.manager import (
    SessionClosed,
    SessionManager,
    SessionRefused,
    TakeoverError,
    TaskSession,
)
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.session.vault import (
    FileVaultStore,
    InMemoryVaultStore,
    StorageVault,
    cipher_from_settings,
)
from friday.connectors.session.web import LiveViewHttp

__all__ = [
    "AuditLog", "BrowserSettings", "FileVaultStore", "InMemoryVaultStore", "LiveViewHttp",
    "LiveViewService", "PauseWatcher", "SessionClosed", "SessionManager", "SessionRefused",
    "StorageVault", "TakeoverError", "TaskSession", "cipher_from_settings", "pause_probe",
]
