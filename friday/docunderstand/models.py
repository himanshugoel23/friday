"""Plain models of the document feature (no bytes anywhere)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.models import new_id


class DocType(StrEnum):
    FLIGHT = "flight_ticket"
    TRAIN = "train_ticket"
    HOTEL = "hotel_confirmation"
    PASSPORT = "passport"
    BILL = "bill"
    GENERIC = "generic"


class DocStatus(StrEnum):
    PENDING = "pending_confirm"  # shown to the user, waiting for "sahi hai"
    AWAITING_FIX = "awaiting_fix"  # the user tapped "galat": waiting for "field: value"
    CONFIRMED = "confirmed"


OPEN_STATUSES = (DocStatus.PENDING, DocStatus.AWAITING_FIX)


class DocField(BaseModel):
    """One extracted value. ``value`` is always a short string (dates ISO, money in paise)."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(max_length=300)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_confirm: bool = False
    confirmed: bool = False
    source: str = "doc"  # "doc" (read from the file) or "user" (typed in a fix)
    masked: bool = False  # True when only a masked form is kept (passport number)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    doc_type: DocType
    status: DocStatus = DocStatus.PENDING
    mime: str = ""
    size_bytes: int = 0
    sha256: str | None = None  # hash of the file (duplicate detection), never the file
    language: str = "hinglish"
    confidence: float = 0.0
    injection_flag: bool = False  # the file contained instruction-like text (it was ignored)
    pointer_kind: str | None = None  # item E: "gdrive"; None until a file is filed in the Drive
    pointer_ref: str | None = None
    fields: dict[str, DocField] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None

    def values(self) -> dict[str, str]:
        return {k: f.value for k, f in self.fields.items()}
