"""The ONLY Google scopes Friday may ever request (least privilege).

Never add Drive, Contacts, Gmail send/modify/compose or any other scope here: the test
``tests/google/test_scopes.py`` fails if this list grows. Gmail read-only is added ONLY when
``FRIDAY_GOOGLE_GMAIL_ENABLED`` is true.
"""

from __future__ import annotations

OPENID = "openid"
EMAIL = "email"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"

BASE_SCOPES: tuple[str, ...] = (OPENID, EMAIL, CALENDAR_EVENTS)
ALLOWED_SCOPES: frozenset[str] = frozenset({*BASE_SCOPES, GMAIL_READONLY})
# Google may return the long form of the identity scopes in the token response.
_EQUIVALENT = {
    "https://www.googleapis.com/auth/userinfo.email": EMAIL,
}


def requested_scopes(gmail_enabled: bool) -> list[str]:
    return [*BASE_SCOPES, GMAIL_READONLY] if gmail_enabled else list(BASE_SCOPES)


def normalise_granted(scope_string: str | None) -> list[str]:
    """Granted scopes from Google's space-separated string, restricted to the allow-list.
    Anything unexpected is dropped (never stored, never acted on)."""
    out: list[str] = []
    for raw in (scope_string or "").split():
        s = _EQUIVALENT.get(raw, raw)
        if s in ALLOWED_SCOPES and s not in out:
            out.append(s)
    return out
