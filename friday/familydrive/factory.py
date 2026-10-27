"""Build a ``FamilyDrive`` over the real Google Drive adapter and the existing OAuth token store.

Nothing calls this in a request path yet (no WhatsApp intent is wired; the switch is OFF). Tests use
``FakeDriveHub().factory`` instead.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from friday.core.clock import Clock
from friday.core.config import Settings
from friday.db.repositories import Repositories
from friday.familydrive.google_drive import GoogleDrive
from friday.familydrive.ports import DrivePort
from friday.familydrive.service import FamilyDrive
from friday.google.oauth import GoogleOAuth


def build_family_drive(
    settings: Settings,
    repos: Repositories,
    *,
    clock: Clock | None = None,
    http: Callable[[], httpx.AsyncClient] | None = None,
) -> FamilyDrive:
    oauth = GoogleOAuth(settings, repos.google, clock=clock, http=http)

    def drive_for(user_id: str) -> DrivePort:
        return GoogleDrive(oauth, user_id, settings=settings, http=http)

    kw = {"clock": clock} if clock is not None else {}
    return FamilyDrive(settings, repos, drive_for, **kw)  # type: ignore[arg-type]
