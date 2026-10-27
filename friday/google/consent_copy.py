"""The words the user sees before Google's own consent screen. ONE place for all of it.

STATUS: PENDING FOUNDER APPROVAL (CLAUDE.md rule 3, hear/read before change). Nothing here may
change, and none of it may go to a real user, until the founder has read and approved it. The
tests only check the facts (read-only Gmail, disconnect any time), not the wording.
"""

from __future__ import annotations

from html import escape

PENDING_FOUNDER_APPROVAL = True

TITLE = "Connect your Google account to Friday"

CALENDAR_LINES = (
    "Your Google Calendar: Friday looks at your events so it never books or calls at a time "
    "you are busy, and adds the appointments you ask it to book.",
)
GMAIL_LINES = (
    "Your Gmail, read-only: Friday looks only for bills, tickets and appointment mails (for "
    "example a due date or a booking time) so it can remind you. It cannot send, delete or "
    "change any email, and it does not keep the text of your emails.",
)
DRIVE_LINES = (
    "Your Google Drive, only the files and folders Friday itself creates: Friday makes a "
    '"Friday" folder and keeps the documents you ask it to file (tickets, hotel bookings, '
    "passports) there, so they stay in YOUR Drive and not on Friday's servers. Friday cannot "
    "see your other Drive files. If you disconnect, Friday forgets where they are; the files "
    "stay yours.",
)
ALWAYS_LINES = (
    "Friday asks for your email address only to show which account is connected.",
    'You can disconnect any time: tell Friday "disconnect Google". Friday then deletes the '
    "connection from its servers and asks Google to cancel the access.",
    "Your Google data is used only for you. It is never used for ads, never shared with other "
    "users, and never used to train models.",
)
BUTTON = "Continue to Google"
FOOTNOTE = "You will see Google's own screen next, where you can allow or decline."

DONE_TITLE = "Google connected"
DONE_BODY = "Done. You can close this page and go back to WhatsApp."
DENIED_TITLE = "Google was not connected"
DENIED_BODY = "Nothing was saved. You can ask Friday to try again whenever you like."
EXPIRED_TITLE = "This link has expired"
EXPIRED_BODY = "Ask Friday for a new link."
CALENDAR_REQUIRED_BODY = (
    "Friday needs permission to see and add calendar events to work with your Google account. "
    "Nothing was saved. Ask Friday for a new link and keep the calendar box ticked."
)


def consent_lines(gmail_enabled: bool, drive_enabled: bool = False) -> list[str]:
    lines = list(CALENDAR_LINES)
    if gmail_enabled:
        lines += GMAIL_LINES
    if drive_enabled:
        lines += DRIVE_LINES
    return lines + list(ALWAYS_LINES)


def consent_body_html(google_url: str, *, gmail_enabled: bool, drive_enabled: bool = False) -> str:
    items = "".join(f"<li>{escape(x)}</li>" for x in consent_lines(gmail_enabled, drive_enabled))
    return (
        f"<h2>{escape(TITLE)}</h2><p>What Friday will do, and why:</p><ul>{items}</ul>"
        f'<p><a class="btn" href="{escape(google_url, quote=True)}" rel="noreferrer">'
        f"{escape(BUTTON)}</a></p><p><small>{escape(FOOTNOTE)}</small></p>"
    )
