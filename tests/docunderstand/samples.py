"""INVENTED documents for tests. Nothing here is a real person, number or booking.

A "file" is magic bytes + the canned JSON the FakeVision returns for it. Passport "AB1234567" and
every name are made up; Aadhaar-shaped strings are made-up digits.
"""

from __future__ import annotations

import json

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
PNG = b"\x89PNG\r\n\x1a\n"
PDF = b"%PDF-1.4\n"


def sample(payload: dict, mime: str = "image/jpeg", *, pages: int = 1) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode()
    if mime == "application/pdf":
        return PDF + body + b"\n" + b"<< /Type /Page >>\n" * pages
    return (PNG if mime == "image/png" else JPEG) + body


FLIGHT = {
    "doc_type": "flight_ticket",
    "text": "E-TICKET Flight 6E 123 PNR XK7Q2P Departure gate Delhi to Goa",
    "fields": {
        "passengers": ["ASHA TESTVERMA", "ROHAN TESTVERMA"],
        "airline": "IndiFly",
        "flight_no": "6E 123",
        "from_iata": "DEL",
        "to_iata": "GOI",
        "dep_local": "2026-11-14T06:15",
        "arr_local": "2026-11-14T08:50",
        "pnr": "XK7Q2P",
        "seat": "14A",
        "fare_paise": 842000,
    },
    "overall": 0.93,
}
TRAIN = {
    "doc_type": "train_ticket",
    "text": "IRCTC e-ticket Indian Railways train 12951 coach B2 berth 31 sleeper",
    "fields": {
        "passengers": "MEERA TESTSHARMA",
        "train_no": "12951",
        "train_name": "Test Rajdhani",
        "from_station": "Mumbai Central",
        "to_station": "New Delhi",
        "dep_local": "2026-11-20T17:00",
        "arr_local": "2026-11-21T08:30",
        "travel_class": "3A",
        "coach_berth": "B2/31",
        "pnr": "8412345670",
    },
    "overall": 0.9,
}
HOTEL = {
    "doc_type": "hotel_confirmation",
    "text": "Booking confirmation hotel reservation check-in check-out room guests",
    "fields": {
        "property_name": "Test Palms Resort",
        "address": "12 Sample Road, Candolim, Goa",
        "phone": "+91 832 000 0000",
        "check_in_date": "2026-11-14",
        "check_in_time": "14:00",
        "check_out_date": "2026-11-17",
        "check_out_time": "11:00",
        "guests": 2,
        "room_type": "Deluxe",
        "confirmation_no": "TP884210",
        "amount_paise": 1860000,
        "prepaid": True,
    },
    "overall": 0.91,
}
PASSPORT = {
    "doc_type": "passport",
    "text": "Passport Republic of India P<INDTESTVERMA<<ASHA<<<< AB1234567",
    "fields": {
        "given_name": "ASHA",
        "surname": "TESTVERMA",
        "nationality": "INDIAN",
        "dob": "1990-04-12",
        "number": "AB1234567",
        "issue_date": "2021-03-01",
        "expiry_date": "2031-02-28",
        "place_of_issue": "TESTCITY",
    },
    "overall": 0.92,
}
BILL = {
    "doc_type": "bill",
    "text": "Test Power Ltd electricity bill kWh\nAmount payable Rs 1,240\nDue date 25 Dec 2026",
    "fields": {"biller": "Test Power Ltd", "account_last4": "7788"},
    "overall": 0.9,
}
BILL_HINDI = {
    "doc_type": "bill",
    "text": "टेस्ट पावर बिजली बिल\nदेय राशि Rs 980\nDue date 25 Dec 2026",
    "fields": {"biller": "Test Power"},
    "overall": 0.88,
}
GENERIC = {
    "doc_type": "generic",
    "text": "Warranty card for a test mixer grinder",
    "fields": {"title": "Warranty card", "summary": "Test mixer grinder, 2 year warranty"},
    "overall": 0.85,
}
AADHAAR = {
    "doc_type": "aadhaar",
    "text": "Aadhaar Government of India 4821 7733 0192 TEST PERSON",
    "fields": {"title": "ID"},
    "overall": 0.95,
}
