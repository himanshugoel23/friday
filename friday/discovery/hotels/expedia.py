"""Expedia Rapid API (v3) - Phase 1 stub: auth signature + search/details wired;
book/cancel/modify are not enabled (``ProviderError("not enabled")``).

Auth: ``Authorization: EAN APIKey=<key>,Signature=<sha512(key+secret+ts)>,timestamp=<ts>``
Docs: https://developers.expediagroup.com/docs/products/rapid
Search flow: region by coordinates (``/regions?area=radius,lat,lng&include=property_ids``)
-> ``/properties/availability`` for those property ids. Content via ``/properties/content``.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from friday.core.clock import Clock, SystemClock
from friday.core.interfaces import ProviderError
from friday.core.models import (
    GeoPoint,
    GuestDetails,
    HotelBooking,
    HotelBookingMode,
    HotelOffer,
    HotelProperty,
    StayRequest,
    normalize_phone,
)

PROVIDER = "expedia_rapid"
MAX_PROPERTIES = 50


def rapid_signature(api_key: str, secret: str, timestamp: int) -> str:
    return hashlib.sha512(f"{api_key}{secret}{timestamp}".encode()).hexdigest()


def rapid_auth_header(api_key: str, secret: str, timestamp: int) -> str:
    sig = rapid_signature(api_key, secret, timestamp)
    return f"EAN APIKey={api_key},Signature={sig},timestamp={timestamp}"


class ExpediaRapid:
    name = PROVIDER

    def __init__(
        self,
        api_key: str,
        shared_secret: str,
        *,
        base_url: str = "https://test.ean.com/v3",
        client: httpx.AsyncClient | None = None,
        clock: Clock | None = None,
        customer_ip: str = "127.0.0.1",
    ) -> None:
        self._key = api_key
        self._secret = shared_secret
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self.clock = clock or SystemClock()
        self.customer_ip = customer_ip

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        ts = int(self.clock.now().timestamp())
        return {
            "Authorization": rapid_auth_header(self._key, self._secret, ts),
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Customer-Ip": self.customer_ip,
            "User-Agent": "Friday/0.1",
        }

    async def _get(self, path: str, params: Any) -> Any:
        try:
            resp = await self._client.get(
                self.base_url + path, params=params, headers=self._headers()
            )
        except httpx.HTTPError as e:
            raise ProviderError(
                PROVIDER, f"network error: {type(e).__name__}", retryable=True
            ) from e
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise ProviderError(
                PROVIDER, f"HTTP {resp.status_code}", retryable=resp.status_code in (429, 503)
            )
        return resp.json()

    # ------------------------------------------------------------------ protocol
    async def search(self, stay: StayRequest, *, limit: int = 20) -> list[HotelOffer]:
        if stay.near is None:
            raise ProviderError(PROVIDER, "destination must be geocoded (stay.near) before search")
        regions = await self._get(
            "/regions",
            [
                ("language", "en-US"),
                ("include", "property_ids"),
                ("area", f"10,{stay.near.lat},{stay.near.lng}"),
            ],
        )
        ids: list[str] = []
        for region in regions or []:
            for pid in region.get("property_ids", []):
                if pid not in ids:
                    ids.append(pid)
        if not ids:
            return []
        ids = ids[:MAX_PROPERTIES]
        occupancy = str(stay.adults) + (
            "-" + ",".join(["8"] * stay.children) if stay.children else ""
        )
        params: list[tuple[str, str]] = [
            ("checkin", stay.check_in.isoformat()),
            ("checkout", stay.check_out.isoformat()),
            ("currency", "INR"),
            ("language", "en-US"),
            ("country_code", "IN"),
            ("rate_plan_count", "1"),
            ("sales_channel", "website"),
            ("sales_environment", "hotel_only"),
            *[("occupancy", occupancy) for _ in range(stay.rooms)],
            *[("property_id", pid) for pid in ids],
        ]
        avail = await self._get("/properties/availability", params) or []
        offers: list[HotelOffer] = []
        for prop in avail:
            details = await self.property_details(prop["property_id"])
            if details is None:
                continue
            offers.extend(self._offers(prop, details, stay, occupancy))
        offers.sort(key=lambda o: o.rate_per_night_inr or 10**9)
        if stay.max_rate_per_night_inr:
            offers = [
                o
                for o in offers
                if (o.rate_per_night_inr or 0) <= stay.max_rate_per_night_inr * 1.5
            ]
        return offers[:limit]

    async def property_details(self, property_id: str) -> HotelProperty | None:
        data = await self._get(
            "/properties/content", [("language", "en-US"), ("property_id", property_id)]
        )
        if not data or property_id not in data:
            return None
        p = data[property_id]
        coords = (p.get("location") or {}).get("coordinates") or {}
        addr = p.get("address") or {}
        ratings = p.get("ratings") or {}
        guest = ratings.get("guest") or {}
        phone = None
        if p.get("phone"):
            try:
                phone = normalize_phone(p["phone"])
            except ValueError:
                phone = None
        overall = guest.get("overall")
        return HotelProperty(
            provider=PROVIDER,
            property_id=property_id,
            name=p.get("name", property_id),
            phone=phone,
            address=", ".join(x for x in (addr.get("line_1"), addr.get("city")) if x) or None,
            location=GeoPoint(lat=coords["latitude"], lng=coords["longitude"])
            if "latitude" in coords
            else None,
            star_rating=_float((ratings.get("property") or {}).get("rating")),
            # Rapid guest ratings are out of 5
            guest_rating=_float(overall),
            review_count=int(guest.get("count") or 0),
            amenities=[a.get("name", "") for a in (p.get("amenities") or {}).values()][:15],
        )

    async def book(
        self, offer: HotelOffer, stay: StayRequest, guest: GuestDetails, *, mode: HotelBookingMode
    ) -> HotelBooking:
        raise ProviderError(PROVIDER, "not enabled")

    async def cancel(self, booking: HotelBooking) -> HotelBooking:
        raise ProviderError(PROVIDER, "not enabled")

    async def modify(self, booking: HotelBooking, stay: StayRequest) -> HotelBooking:
        raise ProviderError(PROVIDER, "not enabled")

    # ------------------------------------------------------------------ parsing
    def _offers(
        self, prop: dict[str, Any], details: HotelProperty, stay: StayRequest, occupancy: str
    ) -> list[HotelOffer]:
        out: list[HotelOffer] = []
        for room in prop.get("rooms", []):
            for rate in room.get("rates", [])[:1]:
                pricing = (rate.get("occupancy_pricing") or {}).get(occupancy) or next(
                    iter((rate.get("occupancy_pricing") or {}).values()), {}
                )
                total = _float(
                    (
                        ((pricing.get("totals") or {}).get("inclusive") or {}).get(
                            "request_currency"
                        )
                        or {}
                    ).get("value")
                )
                total_inr = int(round(total)) if total is not None else None
                nightly = (
                    int(round(total_inr / max(1, stay.nights * stay.rooms))) if total_inr else None
                )
                out.append(
                    HotelOffer(
                        property=details,
                        room_type=room.get("room_name", "room"),
                        rate_per_night_inr=nightly,
                        total_inr=total_inr,
                        pay_at_hotel=rate.get("merchant_of_record") == "property",
                        refundable=rate.get("refundable"),
                        inclusions=[
                            a.get("name", "") for a in (rate.get("amenities") or {}).values()
                        ],
                        booking_link=((prop.get("links") or {}).get("additional_rates") or {}).get(
                            "href"
                        ),
                        offer_token=rate.get("id"),
                    )
                )
        return out


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_expedia_rapid(c) -> ExpediaRapid:  # c: Container
    s = c.settings
    if not s.expedia_rapid_api_key or not s.expedia_rapid_shared_secret:
        raise ProviderError(PROVIDER, "EXPEDIA_RAPID_API_KEY / SHARED_SECRET not set")
    return ExpediaRapid(
        s.expedia_rapid_api_key,
        s.expedia_rapid_shared_secret.get_secret_value(),
        base_url=s.expedia_rapid_base_url,
        clock=c.clock,
    )
