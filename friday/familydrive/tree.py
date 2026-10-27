"""The folder tree, folder keys and file names. All of it is built by OUR code.

Layout (display names are in ``copy.FOLDER_NAMES``, PENDING approval; keys never change):

    Friday/                          key "root"
      Family/                        key "family"
        <person>/                    key "family/<slug>"
          Passports | Visas | IDs | Insurance | Bills | Other
      Trips/                         key "trips"
        <trip>/                      key "trips/<slug>"
          Tickets | Hotel | Insurance | Bills

Keys, not names, identify a folder: a rename in Drive, or a copy-wording change, never breaks a
pointer. Person and trip names are what the user typed (never document text) and are cleaned before
they become a folder name. File names come only from validated, confirmed fields via a strict
character allow-list; a long digit run (an ID or account number) never appears in a name.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime

from friday.docunderstand.models import DocType, Document
from friday.familydrive import copy

ROOT = "root"
FAMILY = "family"
TRIPS = "trips"
PERSON_SUBS = ("passports", "visas", "ids", "insurance", "bills", "other")
TRIP_SUBS = ("tickets", "hotel", "insurance", "bills")

_NAME_MAX = 60
_BAD = re.compile(r"[\x00-\x1f\x7f/\\<>:\"|?*]")
_TOKEN_OK = re.compile(r"[^\w .\-]", re.UNICODE)
_LONG_DIGITS = re.compile(r"\d{6,}")
_EXT = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def clean_folder_name(text: str | None, fallback: str) -> str:
    """A folder name from user-typed text: no path or control characters, short, never empty."""
    t = _BAD.sub(" ", unicodedata.normalize("NFKC", text or ""))
    t = _LONG_DIGITS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:_NAME_MAX].strip() or fallback


def slug(name: str) -> str:
    """Stable key part for a person or trip name: ascii slug + short hash (so Devanagari and
    near-duplicates stay distinct). Case and spacing do not change the key."""
    norm = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).casefold()).strip()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")[:24]
    return f"{ascii_part or 'x'}-{hashlib.sha256(norm.encode()).hexdigest()[:6]}"


def person_key(person: str) -> str:
    return f"{FAMILY}/{slug(person)}"


def trip_key(trip: str) -> str:
    return f"{TRIPS}/{slug(trip)}"


def drive_key(user_id: str, path_key: str) -> str:
    """The value stamped on the Drive object (its ``friday_key``): a hash, not readable."""
    return hashlib.sha256(f"{user_id}\x00{path_key}".encode()).hexdigest()[:32]


def file_key(user_id: str, document_id: str) -> str:
    return hashlib.sha256(f"{user_id}\x00doc\x00{document_id}".encode()).hexdigest()[:32]


def destination(doc_type: DocType, *, has_trip: bool) -> tuple[str, str]:
    """(scope, sub) for a document type: scope is "trip" or "person"."""
    if doc_type in (DocType.FLIGHT, DocType.TRAIN):
        return "trip", "tickets"
    if doc_type is DocType.HOTEL:
        return "trip", "hotel"
    if doc_type is DocType.PASSPORT:
        return "person", "passports"
    if doc_type is DocType.BILL:
        return ("trip", "bills") if has_trip else ("person", "bills")
    return "person", "other"


# ----------------------------------------------------------------------------- file names
def safe_token(value: str | None, maxlen: int = 24) -> str:
    t = unicodedata.normalize("NFKC", value or "")
    t = _TOKEN_OK.sub(" ", t)
    t = _LONG_DIGITS.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" .-")[:maxlen].strip()


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        return None


def file_name(doc: Document, mime: str) -> str:
    """e.g. ``2026-11-14 DEL-GOI IndiGo.pdf``. Built only from confirmed, validated fields."""
    v = doc.values()
    ext = _EXT.get(mime, "bin")
    d = doc.doc_type
    if d is DocType.FLIGHT:
        route = "-".join(
            x for x in (safe_token(v.get("from_iata"), 3), safe_token(v.get("to_iata"), 3)) if x
        )
        parts = [_iso_date(v.get("dep_local")), route, safe_token(v.get("airline"))]
    elif d is DocType.TRAIN:
        route = "-".join(
            x
            for x in (safe_token(v.get("from_station"), 12), safe_token(v.get("to_station"), 12))
            if x
        )
        parts = [_iso_date(v.get("dep_local")), route, copy.NAME_WORDS["train"]]
    elif d is DocType.HOTEL:
        parts = [
            _iso_date(v.get("check_in_date")),
            copy.NAME_WORDS["hotel"],
            safe_token(v.get("property_name")),
        ]
    elif d is DocType.PASSPORT:
        exp = _iso_date(v.get("expiry_date"))
        parts = [
            copy.NAME_WORDS["passport"],
            safe_token(v.get("given_name"), 20),
            f"{copy.NAME_WORDS['expires']} {exp}" if exp else None,
        ]
    elif d is DocType.BILL:
        parts = [_iso_date(v.get("due_date")), copy.NAME_WORDS["bill"], safe_token(v.get("biller"))]
    else:
        parts = [_iso_date(v.get("date")), copy.NAME_WORDS["document"], safe_token(v.get("title"))]
    stem = " ".join(p for p in parts if p).strip()
    if not stem or (d is DocType.GENERIC and not _iso_date(v.get("date"))):
        stem = f"{doc.created_at.date().isoformat()} {stem}".strip()
    return f"{stem[:90].strip()}.{ext}"
