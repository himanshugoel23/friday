"""The ONLY Google scopes Friday may ever request (least privilege).

Never add Contacts, Gmail send/modify/compose or any other scope here: the test
``tests/google/test_scopes.py`` fails if this list grows. Gmail read-only is added ONLY when
``FRIDAY_GOOGLE_GMAIL_ENABLED`` is true. The ONE Drive scope is ``drive.file`` (only files and
folders Friday itself creates), added ONLY when ``FRIDAY_FAMILY_DRIVE_ENABLED`` is true (founder
decision 2026-10-27, docs/FAMILY_DRIVE.md). ``drive``, ``drive.readonly`` and the other Drive
scopes are never requested.
"""

from __future__ import annotations

OPENID = "openid"
EMAIL = "email"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"

BASE_SCOPES: tuple[str, ...] = (OPENID, EMAIL, CALENDAR_EVENTS)
ALLOWED_SCOPES: frozenset[str] = frozenset({*BASE_SCOPES, GMAIL_READONLY, DRIVE_FILE})
# Google may return the long form of the identity scopes in the token response.
_EQUIVALENT = {
    "https://www.googleapis.com/auth/userinfo.email": EMAIL,
}


def requested_scopes(gmail_enabled: bool, drive_enabled: bool = False) -> list[str]:
    out = list(BASE_SCOPES)
    if gmail_enabled:
        out.append(GMAIL_READONLY)
    if drive_enabled:
        out.append(DRIVE_FILE)
    return out


def normalise_granted(scope_string: str | None) -> list[str]:
    """Granted scopes from Google's space-separated string, restricted to the allow-list.
    Anything unexpected is dropped (never stored, never acted on)."""
    out: list[str] = []
    for raw in (scope_string or "").split():
        s = _EQUIVALENT.get(raw, raw)
        if s in ALLOWED_SCOPES and s not in out:
            out.append(s)
    return out
