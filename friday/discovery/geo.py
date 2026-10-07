"""Small geo + phone helpers shared by the discovery providers. Pure functions."""

from __future__ import annotations

import math
import re

from friday.core.models import BusinessHours, GeoPoint, OpeningPeriod

_EARTH_KM = 6371.0088
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def phone_key(phone: str) -> str:
    """Comparable key for Indian numbers in any notation.

    '+91 1800 000 121' / '1800000121' -> '1800000121'; '+919876543210' / '09876543210'
    -> '9876543210'; short codes stay as-is ('121').
    """
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    return digits.lstrip("0") or digits


def is_indian_mobile(phone: str) -> bool:
    """Heuristic: 10-digit numbers starting 6-9 are mobiles, except the Bengaluru
    landline range (080-...), which shares the leading 8."""
    key = phone_key(phone)
    return len(key) == 10 and key[0] in "6789" and not key.startswith("80")


def is_toll_free(phone: str) -> bool:
    key = phone_key(phone)
    return key.startswith(("1800", "1860")) or len(key) <= 5


def hours_from_simworld(hours: dict[str, list[str]], source: str = "simulator") -> BusinessHours:
    """{"mon": ["10:00-13:00", "17:00-21:00"]} -> BusinessHours (IST)."""
    periods: list[OpeningPeriod] = []
    for day, spans in hours.items():
        key = day.strip().lower()[:3]
        if key not in _WEEKDAYS:
            continue
        for span in spans:
            start, _, end = span.partition("-")
            periods.append(
                OpeningPeriod(weekday=_WEEKDAYS.index(key), open=start.strip(), close=end.strip())
            )
    return BusinessHours(periods=periods, source=source)


_STOP = {"the", "and", "of", "a", "an", "in", "near", "at", "for", "&", "-", "pvt", "ltd"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP}


def names_match(a: str, b: str) -> bool:
    """Loose business-name match: most of the shorter name's tokens appear in the other."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & big) / len(small) >= 0.6
