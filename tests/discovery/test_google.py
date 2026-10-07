"""Recorded-payload tests for Google Places (New) + Geocoding. No network:
every request is served by httpx.MockTransport."""

import json

import httpx
import pytest

from friday.core.interfaces import BusinessDirectory, Geocoder, ProviderError
from friday.core.models import GeoPoint
from friday.discovery.google_geocoder import GoogleGeocoder
from friday.discovery.google_places import GooglePlacesDirectory, parse_opening_hours

SEARCH = {
    "places": [
        {
            "id": "ChIJcool",
            "displayName": {"text": "CoolCare AC Services", "languageCode": "en"},
            "formattedAddress": "12th Main, Indiranagar, Bengaluru",
            "location": {"latitude": 12.9784, "longitude": 77.6408},
            "rating": 4.7,
            "userRatingCount": 320,
            "googleMapsUri": "https://maps.google.com/?cid=1",
            "currentOpeningHours": {"openNow": True},
            "priceLevel": "PRICE_LEVEL_MODERATE",
            "primaryType": "hvac_contractor",
            "businessStatus": "OPERATIONAL",
            "internationalPhoneNumber": "+91 80 4000 0003",
        },
        {
            "id": "ChIJclosed",
            "displayName": {"text": "Old AC"},
            "businessStatus": "CLOSED_PERMANENTLY",
        },
    ]
}
DETAILS = {
    "id": "ChIJcool",
    "displayName": {"text": "CoolCare AC Services"},
    "nationalPhoneNumber": "080 4000 0003",
    "rating": 4.7,
    "userRatingCount": 320,
    "reviews": [
        {"rating": 5, "text": {"text": "Technician came on time, fair price"}},
        {"rating": 4, "originalText": {"text": "Good service"}},
    ],
    "regularOpeningHours": {
        "periods": [
            {
                "open": {"day": 1, "hour": 9, "minute": 30},
                "close": {"day": 1, "hour": 13, "minute": 0},
            },
            {
                "open": {"day": 1, "hour": 14, "minute": 0},
                "close": {"day": 1, "hour": 19, "minute": 0},
            },
            {
                "open": {"day": 0, "hour": 22, "minute": 0},
                "close": {"day": 1, "hour": 2, "minute": 0},
            },
        ]
    },
}
GEOCODE_OK = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "Kothrud, Pune, Maharashtra, India",
            "place_id": "ChIJkothrud",
            "geometry": {
                "location": {"lat": 18.5074, "lng": 73.8077},
                "location_type": "APPROXIMATE",
            },
            "address_components": [
                {"long_name": "Kothrud", "types": ["sublocality"]},
                {"long_name": "Pune", "types": ["locality", "political"]},
            ],
        }
    ],
}


def places_client(seen: list[httpx.Request], status: int = 200) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if status != 200:
            return httpx.Response(status)
        if req.url.path.endswith(":searchText"):
            return httpx.Response(200, json=SEARCH)
        if req.url.path.endswith("/places/missing"):
            return httpx.Response(404)
        return httpx.Response(200, json=DETAILS)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_places_search_request_and_parsing():
    seen: list[httpx.Request] = []
    d = GooglePlacesDirectory("KEY", client=places_client(seen))
    assert isinstance(d, BusinessDirectory)
    res = await d.search(
        "AC repair", "Indiranagar, Bengaluru", near=GeoPoint(lat=12.9719, lng=77.6412)
    )
    req = seen[0]
    body = json.loads(req.content)
    assert req.headers["X-Goog-Api-Key"] == "KEY" and "places.id" in req.headers["X-Goog-FieldMask"]
    assert body["textQuery"] == "AC repair in Indiranagar, Bengaluru" and body["regionCode"] == "IN"
    assert body["locationBias"]["circle"]["center"]["latitude"] == 12.9719
    assert len(res) == 1  # permanently closed dropped
    c = res[0]
    assert c.phone == "+918040000003" and c.price_level == 2 and c.open_now is True
    assert c.distance_km and c.distance_km < 1.5 and c.provider == "google_places"


async def test_places_details_reviews_hours_and_cache():
    seen: list[httpx.Request] = []
    d = GooglePlacesDirectory("KEY", client=places_client(seen))
    c = await d.details("ChIJcool")
    assert c.review_snippets == ["Technician came on time, fair price", "Good service"]
    assert c.phone == "+918040000003"
    hours = await d.business_hours("ChIJcool")
    mon = [p for p in hours.periods if p.weekday == 0]
    assert [(p.open, p.close) for p in mon] == [("09:30", "13:00"), ("14:00", "19:00")]
    assert any(p.weekday == 6 and p.open == "22:00" and p.close == "23:59" for p in hours.periods)
    assert len(seen) == 1  # second call served from cache
    assert await d.details("missing") is None


async def test_places_errors_normalised():
    d = GooglePlacesDirectory("KEY", client=places_client([], status=429))
    with pytest.raises(ProviderError) as e:
        await d.search("x", "y")
    assert e.value.retryable
    d2 = GooglePlacesDirectory("KEY", client=places_client([], status=403))
    with pytest.raises(ProviderError) as e2:
        await d2.search("x", "y")
    assert not e2.value.retryable


def test_opening_hours_24h_and_empty():
    assert parse_opening_hours(None) is None
    h = parse_opening_hours({"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]})
    assert len(h.periods) == 7


def geo_client(seen, payloads, redirects=None):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if redirects and req.url.host in redirects:
            return httpx.Response(302, headers={"location": redirects[req.url.host]})
        return httpx.Response(200, json=payloads.pop(0))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_geocode_and_reverse():
    seen: list[httpx.Request] = []
    g = GoogleGeocoder(
        "KEY", client=geo_client(seen, [GEOCODE_OK, GEOCODE_OK, {"status": "ZERO_RESULTS"}])
    )
    assert isinstance(g, Geocoder)
    r = await g.geocode("Kothrud Pune", near=GeoPoint(lat=18.5, lng=73.8))
    assert r.city == "Pune" and r.confidence == 0.4 and r.provider_place_id == "ChIJkothrud"
    assert seen[0].url.params["region"] == "in" and "bounds" in seen[0].url.params
    pin = GeoPoint(lat=18.51, lng=73.81)
    rev = await g.reverse(pin)
    assert rev.location == pin and seen[1].url.params["latlng"] == "18.51,73.81"
    assert await g.geocode("nowhere") is None
    assert await g.geocode("  ") is None


async def test_geocode_error_status():
    g = GoogleGeocoder("KEY", client=geo_client([], [{"status": "REQUEST_DENIED"}]))
    with pytest.raises(ProviderError):
        await g.geocode("x")


async def test_maps_short_link_expanded_then_reverse_geocoded():
    seen: list[httpx.Request] = []
    g = GoogleGeocoder(
        "KEY",
        client=geo_client(
            seen,
            [GEOCODE_OK],
            redirects={
                "maps.app.goo.gl": "https://www.google.com/maps/place/Kothrud/@18.5074,73.8077,15z"
            },
        ),
    )
    r = await g.resolve_maps_link("https://maps.app.goo.gl/AbC123")
    assert r.city == "Pune" and r.location.lat == 18.5074
    assert seen[0].url.host == "maps.app.goo.gl"


async def test_maps_link_with_query_geocodes():
    g = GoogleGeocoder("KEY", client=geo_client([], [GEOCODE_OK]))
    r = await g.resolve_maps_link("https://www.google.com/maps/search/?api=1&query=Kothrud+Pune")
    assert r.city == "Pune"
    assert await g.resolve_maps_link("https://example.com") is None
