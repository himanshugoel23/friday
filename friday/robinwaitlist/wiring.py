# ruff: noqa: E501
"""Build the store for these settings (encrypted lines when the process field cipher exists)."""

from __future__ import annotations

from typing import Any

from friday.robinwaitlist.store import WaitlistStore


def store_for(settings: Any) -> WaitlistStore:
    cipher = None
    try:
        from friday.core.crypto import get_field_cipher

        cipher = get_field_cipher()
    except Exception:  # noqa: BLE001 - plain JSON lines (file mode 0600) when no cipher is available
        cipher = None
    return WaitlistStore(getattr(settings, "robin_waitlist_dir", "var/robin_waitlist"), cipher=cipher)
