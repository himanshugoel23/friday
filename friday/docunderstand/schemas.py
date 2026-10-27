"""The fields kept per document type, and the strict normaliser for each value.

A value that does not fit its kind is DROPPED (never guessed). Keys the model invents are ignored.
There is deliberately no field for a government-ID number, and the passport number exists only as
``number_masked``. Money is always paise (int), dates ISO, local times ``YYYY-MM-DDTHH:MM``.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from friday.docunderstand.models import DocType
from friday.docunderstand.safety import clean_text, mask_passport_number

# kind -> short description (the kinds are implemented in ``normalise_value``)
SPECS: dict[DocType, dict[str, str]] = {
    DocType.FLIGHT: {
        "passengers": "name",
        "airline": "str",
        "flight_no": "code",
        "from_iata": "iata",
        "to_iata": "iata",
        "dep_local": "dt",
        "arr_local": "dt",
        "terminal": "str",
        "pnr": "code",
        "seat": "str",
        "baggage": "str",
        "fare_paise": "paise",
        "cancellation_note": "text",
    },
    DocType.TRAIN: {
        "passengers": "name",
        "train_no": "code",
        "train_name": "str",
        "from_station": "str",
        "to_station": "str",
        "boarding_station": "str",
        "dep_local": "dt",
        "arr_local": "dt",
        "travel_class": "str",
        "coach_berth": "str",
        "pnr": "code",
    },
    DocType.HOTEL: {
        "property_name": "str",
        "address": "text",
        "phone": "phone",
        "check_in_date": "date",
        "check_in_time": "time",
        "check_out_date": "date",
        "check_out_time": "time",
        "guests": "count",
        "room_type": "str",
        "confirmation_no": "code",
        "amount_paise": "paise",
        "prepaid": "bool",
        "cancellation_deadline": "dt_or_date",
        "platform": "str",
    },
    DocType.PASSPORT: {
        "given_name": "name",
        "surname": "name",
        "nationality": "str",
        "dob": "date",
        "number_masked": "passport_masked",
        "issue_date": "date",
        "expiry_date": "date",
        "place_of_issue": "str",
    },
    DocType.BILL: {
        "biller": "str",
        "kind": "str",
        "amount_paise": "paise",
        "due_date": "date",
        "min_due_paise": "paise",
        "account_last4": "last4",
    },
    DocType.GENERIC: {"title": "str", "summary": "text"},
}
# what a reply shows, in order (the rest is kept but not listed)
SHOW: dict[DocType, tuple[str, ...]] = {
    DocType.FLIGHT: (
        "passengers",
        "airline",
        "flight_no",
        "from_iata",
        "to_iata",
        "dep_local",
        "arr_local",
        "pnr",
        "seat",
    ),
    DocType.TRAIN: (
        "passengers",
        "train_no",
        "train_name",
        "from_station",
        "to_station",
        "dep_local",
        "arr_local",
        "travel_class",
        "coach_berth",
        "pnr",
    ),
    DocType.HOTEL: (
        "property_name",
        "address",
        "check_in_date",
        "check_in_time",
        "check_out_date",
        "guests",
        "confirmation_no",
        "amount_paise",
        "prepaid",
    ),
    DocType.PASSPORT: (
        "given_name",
        "surname",
        "nationality",
        "dob",
        "number_masked",
        "issue_date",
        "expiry_date",
    ),
    DocType.BILL: ("biller", "kind", "amount_paise", "due_date", "min_due_paise", "account_last4"),
    DocType.GENERIC: ("title", "summary"),
}
# the minimum for "I read this": at least this many kept fields
MIN_FIELDS: dict[DocType, int] = {
    DocType.FLIGHT: 3,
    DocType.TRAIN: 3,
    DocType.HOTEL: 3,
    DocType.PASSPORT: 3,
    DocType.BILL: 2,
    DocType.GENERIC: 1,
}
MAX_LEN = {"name": 120, "str": 80, "text": 200, "code": 24, "phone": 20}

_IATA = re.compile(r"[A-Z]{3}")
_CODE = re.compile(r"[A-Z0-9][A-Z0-9 \-/]{1,23}")
_DT = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_PHONE = re.compile(r"[+\d][\d \-()]{5,19}")


def parse_date(v: object) -> date | None:
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_dt(v: object) -> datetime | None:
    s = str(v or "").strip()
    if m := _DT.fullmatch(s):
        try:
            return datetime(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    m2 = re.fullmatch(r"(.+?)[ T,]+(\d{1,2}):(\d{2})", s)
    if m2 and (d := parse_date(m2.group(1).strip(" ,"))):
        h, mi = int(m2.group(2)), int(m2.group(3))
        if h < 24 and mi < 60:
            return datetime(d.year, d.month, d.day, h, mi)
    return None


def parse_paise(v: object) -> int | None:
    """Model output is already paise (int). A user's typed fix may say rupees ('Rs 1,240')."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 <= v <= 10**10 else None
    s = str(v or "").strip()
    if re.fullmatch(r"\d{1,11}", s):
        return int(s)
    m = re.fullmatch(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)", s, re.IGNORECASE)
    if m:
        n = float(m.group(1).replace(",", ""))
        return round(n * 100) if n <= 10**8 else None
    return None


def normalise_value(kind: str, raw: object, *, from_user: bool = False) -> str | None:
    """The stored string for ``raw``, or None when it does not fit the kind."""
    if raw is None or raw == "" or isinstance(raw, (dict, set)):
        return None
    if kind in ("name", "str", "text"):
        if isinstance(raw, list):
            raw = "; ".join(clean_text(x, 60) for x in raw[:8] if x)
        s = clean_text(raw, MAX_LEN[kind])
        return s or None
    if kind == "iata":
        s = clean_text(raw, 12).upper()
        return s if _IATA.fullmatch(s) else None
    if kind == "code":
        s = clean_text(raw, 40).upper()
        return s if _CODE.fullmatch(s) else None
    if kind == "dt":
        d = parse_dt(raw)
        return d.strftime("%Y-%m-%dT%H:%M") if d else None
    if kind == "dt_or_date":
        if d := parse_dt(raw):
            return d.strftime("%Y-%m-%dT%H:%M")
        dd = parse_date(raw)
        return dd.isoformat() if dd else None
    if kind == "date":
        d2 = parse_date(raw)
        return d2.isoformat() if d2 else None
    if kind == "time":
        m = _TIME.fullmatch(str(raw).strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        return None
    if kind == "paise":
        n = parse_paise(raw) if from_user or isinstance(raw, (int, str)) else None
        return str(n) if n is not None else None
    if kind == "count":
        try:
            n = int(str(raw).strip())
        except ValueError:
            return None
        return str(n) if 1 <= n <= 99 else None
    if kind == "bool":
        s = str(raw).strip().lower()
        if s in ("true", "yes", "haan", "1", "prepaid", "paid"):
            return "true"
        if s in ("false", "no", "nahi", "0", "pay at hotel"):
            return "false"
        return None
    if kind == "phone":
        s = clean_text(raw, 40)
        return s if _PHONE.fullmatch(s) else None
    if kind == "last4":
        digits = re.sub(r"\D", "", str(raw))
        return digits[-4:] if len(digits) >= 4 else None
    if kind == "passport_masked":
        s = mask_passport_number(raw)
        return s or None
    return None


def normalise_fields(
    doc_type: DocType, raw: dict, confidences: dict[str, float], default_conf: float
) -> tuple[dict[str, tuple[str, float]], int]:
    """(name -> (stored value, confidence), number of dropped/unknown keys). A passport ``number``
    key is converted to ``number_masked`` before anything else sees it."""
    spec = SPECS[doc_type]
    raw = dict(raw or {})
    if doc_type == DocType.PASSPORT and "number" in raw:
        raw.setdefault("number_masked", raw.pop("number"))
        raw.pop("number", None)
    out: dict[str, tuple[str, float]] = {}
    dropped = 0
    for key, value in raw.items():
        kind = spec.get(key)
        if kind is None:
            dropped += 1
            continue
        v = normalise_value(kind, value)
        if v is None:
            dropped += 1
            continue
        c = confidences.get(key, default_conf)
        out[key] = (v, max(0.0, min(1.0, float(c))))
    return out, dropped
