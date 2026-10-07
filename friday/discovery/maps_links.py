"""Parse pasted Google Maps links (no network). Short links are expanded by the
real geocoder; the parser handles the long forms:

  https://www.google.com/maps/place/Looks+Salon/@12.9719,77.6412,17z/...
  https://maps.google.com/?q=12.9719,77.6412
  https://www.google.com/maps/search/?api=1&query=12.97,77.64
  https://www.google.com/maps/search/?api=1&query=Looks+Salon+Indiranagar
  https://www.google.com/maps/dir/?api=1&destination=12.97,77.64
  geo:12.9719,77.6412
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote_plus, urlparse

from friday.core.models import GeoPoint

SHORT_LINK_HOSTS = ("maps.app.goo.gl", "goo.gl")

_AT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_BANG = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_LATLNG = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_PLACE = re.compile(r"/maps/place/([^/@]+)")


@dataclass(frozen=True)
class ParsedMapsLink:
    point: GeoPoint | None = None
    query: str | None = None  # a place name / address to geocode
    is_short: bool = False


def is_maps_link(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("geo:") or (
        t.startswith(("http://", "https://"))
        and any(h in t for h in ("google.", "goo.gl", "maps.app"))
    )


def _point(lat: str, lng: str) -> GeoPoint | None:
    la, ln = float(lat), float(lng)
    if -90 <= la <= 90 and -180 <= ln <= 180:
        return GeoPoint(lat=la, lng=ln)
    return None


def parse_maps_link(url: str) -> ParsedMapsLink | None:
    url = url.strip()
    if url.lower().startswith("geo:"):
        m = _LATLNG.match(url[4:].split("?")[0])
        return ParsedMapsLink(point=_point(*m.groups())) if m else None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if host in SHORT_LINK_HOSTS and (host != "goo.gl" or parsed.path.startswith("/maps")):
        return ParsedMapsLink(is_short=True)
    if "google." not in host:
        return None
    # precise pin markers beat the viewport centre
    if m := _BANG.search(url):
        return ParsedMapsLink(point=_point(*m.groups()), query=_place_name(parsed.path))
    qs = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "destination", "center"):
        for value in qs.get(key, []):
            if m := _LATLNG.match(value):
                return ParsedMapsLink(point=_point(*m.groups()))
            if key in ("q", "query", "destination") and value.strip():
                return ParsedMapsLink(query=unquote_plus(value).strip())
    if m := _AT.search(parsed.path):
        return ParsedMapsLink(point=_point(*m.groups()), query=_place_name(parsed.path))
    if name := _place_name(parsed.path):
        return ParsedMapsLink(query=name)
    return None


def _place_name(path: str) -> str | None:
    m = _PLACE.search(path)
    return unquote_plus(m.group(1)).strip() if m else None
