"""Tables for the Google connector (migration 0006_google_connector).

* ``google_connections``: at most one row per Friday user. Refresh and access tokens and the
  Google e-mail are encrypted at rest (AES-GCM, AAD ``table.column``); ``google_sub_hmac`` is a
  blind index of Google's stable account id. ``user_id`` is the erasure key and the ONLY way a row
  is ever read (repositories always filter by it; Row Level Security is on, with no policy for
  the public API roles, see deploy/supabase/README.md).
* ``google_oauth_states``: one row per consent attempt. ``id`` is the SHA-256 of the state nonce
  (the nonce itself is never stored), ``used_at`` makes it single use, ``code_verifier`` (PKCE)
  is encrypted and wiped once used.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


class GoogleConnectionRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "google_connections"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    google_sub_hmac: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(EncryptedText("google_connections.email"))
    scopes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    refresh_token: Mapped[str] = mapped_column(
        EncryptedText("google_connections.refresh_token"), nullable=False
    )
    access_token: Mapped[str | None] = mapped_column(
        EncryptedText("google_connections.access_token")
    )
    access_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class GoogleOAuthStateRow(Base):
    __tablename__ = "google_oauth_states"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(nonce) hex
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_verifier: Mapped[str | None] = mapped_column(
        EncryptedText("google_oauth_states.code_verifier")
    )
    scopes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


__all__ = ["GoogleConnectionRow", "GoogleOAuthStateRow"]
