"""Least privilege: the scope list can only ever be the approved one."""

from __future__ import annotations

from friday.google import scopes as sc

FORBIDDEN = (
    "drive.readonly", "drive.metadata", "drive.appdata", "drive.photos", "auth/drive\"",
    "contacts", "gmail.send", "gmail.compose", "gmail.modify", "gmail.insert",
    "gmail.labels", "gmail.settings", "mail.google.com", "calendar\"", "auth/calendar ",
    "admin", "cloud-platform", "photos", "youtube",
)  # fmt: skip


def test_allow_list_is_exactly_the_approved_scopes():
    assert {
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive.file",
    } == sc.ALLOWED_SCOPES


def test_the_only_drive_scope_is_drive_file():
    """Founder decision 2026-10-27: family documents live in the family's own Drive, with the
    narrowest scope (only files Friday creates). Full drive / readonly are never allowed."""
    drive_scopes = {s for s in sc.ALLOWED_SCOPES if "drive" in s}
    assert drive_scopes == {sc.DRIVE_FILE} == {"https://www.googleapis.com/auth/drive.file"}
    assert "https://www.googleapis.com/auth/drive" not in sc.ALLOWED_SCOPES
    asked = sc.requested_scopes(True, True)
    assert not any(s.endswith(("/drive", "drive.readonly")) for s in asked)


def test_drive_file_is_requested_only_with_its_switch():
    assert sc.DRIVE_FILE not in sc.requested_scopes(False)
    assert sc.DRIVE_FILE not in sc.requested_scopes(True)
    assert sc.requested_scopes(False, True) == [*sc.BASE_SCOPES, sc.DRIVE_FILE]
    assert sc.requested_scopes(True, True)[-2:] == [sc.GMAIL_READONLY, sc.DRIVE_FILE]


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
        "https://www.googleapis.com/auth/drive.readonly "
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/drive.file"
    )
    assert granted == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/drive.file",
    ]
    assert sc.normalise_granted(None) == []
