"""Airport time zones and countries, so a local departure time becomes one real instant.

A small, public-fact table (IATA code -> IANA zone, ISO country). It is NOT a claim about any
airline. An airport that is not listed is ``None``: the caller falls back to a stated assumption
(conservative: international buffer, home zone) and says so in the message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST_ZONE = "Asia/Kolkata"

# code -> (IANA zone, ISO country)
AIRPORTS: dict[str, tuple[str, str]] = {
    "DEL": (IST_ZONE, "IN"),
    "BOM": (IST_ZONE, "IN"),
    "BLR": (IST_ZONE, "IN"),
    "HYD": (IST_ZONE, "IN"),
    "MAA": (IST_ZONE, "IN"),
    "CCU": (IST_ZONE, "IN"),
    "GOI": (IST_ZONE, "IN"),
    "GOX": (IST_ZONE, "IN"),
    "AMD": (IST_ZONE, "IN"),
    "PNQ": (IST_ZONE, "IN"),
    "COK": (IST_ZONE, "IN"),
    "JAI": (IST_ZONE, "IN"),
    "LKO": (IST_ZONE, "IN"),
    "IXC": (IST_ZONE, "IN"),
    "SXR": (IST_ZONE, "IN"),
    "ATQ": (IST_ZONE, "IN"),
    "GAU": (IST_ZONE, "IN"),
    "PAT": (IST_ZONE, "IN"),
    "IDR": (IST_ZONE, "IN"),
    "TRV": (IST_ZONE, "IN"),
    "VNS": (IST_ZONE, "IN"),
    "DXB": ("Asia/Dubai", "AE"),
    "AUH": ("Asia/Dubai", "AE"),
    "DOH": ("Asia/Qatar", "QA"),
    "SIN": ("Asia/Singapore", "SG"),
    "BKK": ("Asia/Bangkok", "TH"),
    "KUL": ("Asia/Kuala_Lumpur", "MY"),
    "HKG": ("Asia/Hong_Kong", "HK"),
    "NRT": ("Asia/Tokyo", "JP"),
    "ICN": ("Asia/Seoul", "KR"),
    "CMB": ("Asia/Colombo", "LK"),
    "KTM": ("Asia/Kathmandu", "NP"),
    "MLE": ("Indian/Maldives", "MV"),
    "LHR": ("Europe/London", "GB"),
    "CDG": ("Europe/Paris", "FR"),
    "FRA": ("Europe/Berlin", "DE"),
    "AMS": ("Europe/Amsterdam", "NL"),
    "JFK": ("America/New_York", "US"),
    "EWR": ("America/New_York", "US"),
    "SFO": ("America/Los_Angeles", "US"),
    "YYZ": ("America/Toronto", "CA"),
    "SYD": ("Australia/Sydney", "AU"),
    "MEL": ("Australia/Melbourne", "AU"),
}


def airport_zone(code: str | None) -> ZoneInfo | None:
    row = AIRPORTS.get((code or "").strip().upper())
    return ZoneInfo(row[0]) if row else None


def airport_country(code: str | None) -> str | None:
    row = AIRPORTS.get((code or "").strip().upper())
    return row[1] if row else None


def is_international(origin: str | None, dest: str | None) -> tuple[bool, bool]:
    """(international, assumed). An unknown airport counts as international (the longer, safer
    buffer) and ``assumed`` is True so the message says so."""
    a, b = airport_country(origin), airport_country(dest)
    if a is None or b is None:
        return True, True
    return not (a == "IN" and b == "IN"), False


def local_to_utc(naive_local: datetime, zone: ZoneInfo) -> datetime:
    """A wall-clock time at ``zone`` to an aware UTC instant."""
    return naive_local.replace(tzinfo=zone).astimezone(UTC)
