"""Least privilege: the scope list can only ever be the approved one."""

from __future__ import annotations

from friday.google import scopes as sc

FORBIDDEN = (
    "drive", "contacts", "gmail.send", "gmail.compose", "gmail.modify", "gmail.insert",
    "gmail.labels", "gmail.settings", "mail.google.com", "calendar\"", "auth/calendar ",
    "admin", "cloud-platform", "photos", "youtube",
)  # fmt: skip


def test_allow_list_is_exactly_the_approved_scopes():
    assert {
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/gmail.readonly",
    } == sc.ALLOWED_SCOPES


def test_gmail_off_requests_calendar_and_identity_only():
    assert sc.requested_scopes(False) == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
    ]


def test_gmail_on_adds_only_read_only():
    got = sc.requested_scopes(True)
    assert got[-1] == "https://www.googleapis.com/auth/gmail.readonly"
    assert set(got) <= sc.ALLOWED_SCOPES and len(got) == 4


def test_no_forbidden_scope_anywhere():
    for scope in sc.ALLOWED_SCOPES:
        for bad in FORBIDDEN:
            assert bad not in scope


def test_unexpected_granted_scopes_are_dropped():
    granted = sc.normalise_granted(
        "openid https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/drive https://mail.google.com/ "
        "https://www.googleapis.com/auth/calendar.events"
    )
    assert granted == ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]
    assert sc.normalise_granted(None) == []
