"""Deterministic checks across fields. A failing check never rejects a document: it marks the
fields involved ``needs_confirm`` and (for a few codes) adds a note line to the reply."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from friday.docunderstand.models import DocType
from friday.docunderstand.schemas import parse_date, parse_dt

INDIAN_AIRPORTS = frozenset(
    [
        "DEL",
        "BOM",
        "BLR",
        "MAA",
        "CCU",
        "HYD",
        "AMD",
        "PNQ",
        "GOI",
        "GOX",
        "COK",
        "JAI",
        "LKO",
        "ATQ",
        "IXC",
        "PAT",
        "BBI",
        "IXR",
        "GAU",
        "SXR",
        "IDR",
        "NAG",
        "VNS",
        "BDQ",
        "TRV",
        "IXB",
        "UDR",
        "RPR",
        "IXM",
        "CJB",
        "VTZ",
        "IXZ",
        "IMF",
        "AGR",
        "DED",
        "JDH",
        "IXJ",
        "SXV",
        "TIR",
        "HBX",
        "BHO",
        "IXE",
        "IXA",
        "DIB",
    ]
)


@dataclass(frozen=True)
class Issue:
    code: str  # arrival_before_departure, same_place, expiry_before_issue, ...
    fields: tuple[str, ...]
    note: bool = False  # True: also tell the user (a warning line)


def validate(doc_type: DocType, v: dict[str, str], today: date) -> list[Issue]:
    out: list[Issue] = []
    if doc_type in (DocType.FLIGHT, DocType.TRAIN):
        dep, arr = parse_dt(v.get("dep_local")), parse_dt(v.get("arr_local"))
        if dep and arr:
            domestic = doc_type == DocType.TRAIN or (
                v.get("from_iata") in INDIAN_AIRPORTS and v.get("to_iata") in INDIAN_AIRPORTS
            )
            limit = timedelta(0) if domestic else timedelta(hours=-24)
            if arr - dep <= limit:  # time zones can make an international arrival look earlier
                out.append(Issue("arrival_before_departure", ("dep_local", "arr_local")))
        if dep and not (today - timedelta(days=366) <= dep.date() <= today + timedelta(days=730)):
            out.append(Issue("date_out_of_range", ("dep_local",)))
        if (
            doc_type == DocType.FLIGHT
            and v.get("from_iata")
            and v.get("from_iata") == v.get("to_iata")
        ):
            out.append(Issue("same_place", ("from_iata", "to_iata")))
        if (
            doc_type == DocType.TRAIN
            and v.get("from_station")
            and (v.get("from_station", "").lower() == v.get("to_station", "").lower())
        ):
            out.append(Issue("same_place", ("from_station", "to_station")))
    elif doc_type == DocType.HOTEL:
        cin, cout = parse_date(v.get("check_in_date")), parse_date(v.get("check_out_date"))
        if cin and cout and cout <= cin:
            out.append(Issue("checkout_before_checkin", ("check_in_date", "check_out_date")))
        if cin and not (today - timedelta(days=366) <= cin <= today + timedelta(days=730)):
            out.append(Issue("date_out_of_range", ("check_in_date",)))
    elif doc_type == DocType.PASSPORT:
        issue, expiry = parse_date(v.get("issue_date")), parse_date(v.get("expiry_date"))
        dob = parse_date(v.get("dob"))
        if issue and expiry and expiry <= issue:
            out.append(Issue("expiry_before_issue", ("issue_date", "expiry_date")))
        if dob and dob >= today:
            out.append(Issue("dob_in_future", ("dob",)))
        if dob and issue and issue <= dob:
            out.append(Issue("issue_before_dob", ("dob", "issue_date")))
        if expiry and expiry < today + timedelta(days=183):
            out.append(Issue("expires_soon", ("expiry_date",), note=True))
    elif doc_type == DocType.BILL:
        if v.get("amount_paise") in ("0", None) and v.get("due_date") is None:
            out.append(Issue("no_amount_or_due", ("amount_paise", "due_date")))
        total, minimum = v.get("amount_paise"), v.get("min_due_paise")
        if total and minimum and int(minimum) > int(total):
            out.append(Issue("min_due_above_total", ("amount_paise", "min_due_paise")))
    return out
