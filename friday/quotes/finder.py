# ruff: noqa: E501
"""Vendor discovery for the quotes flow: Places search -> filter -> rank -> shortlist.

* Text search around the user's point (radius ~5 km), then a lean detail lookup only for
  results that came back without a phone number.
* Keeps: has a phone, operational (the directory drops closed places), rating >= minimum when
  a rating exists, inside the radius, not on the do-not-call list, not a duplicate (place id,
  phone, or same name at the same spot).
* Rank: ``rating * ln(1 + reviews) / (1 + distance_km / 5)``; a place known to be open at the
  requested time gets a boost, a place known to be closed is pushed down.
* Cost control: results are cached per ~1 km cell; a hard cap on directory calls per request
  (searches + detail lookups) stops the spend; the caller adds the per-user daily cap.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.core.models import BusinessCandidate, GeoPoint
from friday.discovery.geo import haversine_km, phone_key
from friday.quotes.models import Vendor

log = get_logger(__name__)

QUERIES = ("salon", "beauty parlour")


@dataclass
class FindResult:
    vendors: list[Vendor] = field(default_factory=list)
    calls_used: int = 0
    error: bool = False  # the directory failed (the user gets an honest message)
    capped: bool = False


def _supports(fn: Any, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def score(c: BusinessCandidate, when: datetime | None) -> float:
    rating = c.rating if c.rating is not None else 3.8
    base = rating * math.log(1 + max(c.review_count, 0))
    base /= 1 + (c.distance_km or 0.0) / 5.0
    open_then = _open_then(c, when)
    if open_then is True:
        base *= 1.15
    elif open_then is False:
        base *= 0.5
    return base


def _open_then(c: BusinessCandidate, when: datetime | None) -> bool | None:
    if when is not None and c.hours is not None:
        try:
            return c.hours.is_open(when)
        except Exception:  # noqa: BLE001
            return None
    return c.open_now if when is None else None


class VendorFinder:
    def __init__(
        self,
        directory: Any,
        *,
        cache: Any = None,
        pool: Any = None,
        radius_km: float = 5.0,
        min_rating: float = 3.8,
        max_calls: int = 8,
        cache_ttl_s: int = 6 * 3600,
    ) -> None:
        self.directory = directory
        self.cache = cache
        self.pool = pool
        self.radius_km = radius_km
        self.min_rating = min_rating
        self.max_calls = max_calls
        self.cache_ttl_s = cache_ttl_s

    # ------------------------------------------------------------------ cache
    @staticmethod
    def _cell(point: GeoPoint, query: str) -> str:
        return f"qplaces:{query}:{round(point.lat, 2)}:{round(point.lng, 2)}"

    async def _cached(self, key: str) -> list[BusinessCandidate] | None:
        if self.cache is None:
            return None
        raw = await self.cache.get(key)
        if not raw:
            return None
        return [BusinessCandidate.model_validate(x) for x in raw]

    async def _store(self, key: str, items: list[BusinessCandidate]) -> None:
        if self.cache is not None and items:
            await self.cache.set(
                key, [i.model_dump(mode="json") for i in items], ttl_s=self.cache_ttl_s
            )

    # ------------------------------------------------------------------ search
    async def find(
        self,
        point: GeoPoint,
        *,
        where_text: str,
        when: datetime | None = None,
        exclude: set[str] | None = None,
        limit: int = 12,
        max_calls: int | None = None,
    ) -> FindResult:
        res = FindResult()
        cap = self.max_calls if max_calls is None else max_calls
        pool_: dict[str, BusinessCandidate] = {}
        for query in QUERIES:
            if len(self._qualified(pool_.values(), point, exclude)) >= 6:
                break
            key = self._cell(point, query)
            items = await self._cached(key)
            if items is None:
                if res.calls_used >= cap:
                    res.capped = True
                    break
                try:
                    kw: dict[str, Any] = {"near": point, "limit": 15}
                    if _supports(self.directory.search, "radius_m"):
                        kw["radius_m"] = self.radius_km * 1000
                    items = await self.directory.search(query, where_text, **kw)
                except ProviderError as e:
                    log.warning("places search failed: %s", type(e).__name__)
                    res.error = True
                    break
                except Exception as e:  # noqa: BLE001 - never let discovery raise into the chat
                    log.warning("places search crashed: %s", type(e).__name__)
                    res.error = True
                    break
                res.calls_used += 1
                await self._store(key, items)
            for c in items:
                if c.distance_km is None and c.location is not None:
                    c = c.model_copy(update={"distance_km": round(haversine_km(point, c.location), 2)})
                pool_.setdefault(c.place_id, c)
        if res.error and not pool_:
            return res
        # lean detail lookup for the best candidates that came without a phone number
        cands = [c for c in pool_.values() if self._basic_ok(c, point, exclude)]
        cands.sort(key=lambda c: score(c, when), reverse=True)
        for i, c in enumerate(cands[: limit + 4]):
            if c.phone:
                continue
            if res.calls_used >= cap:
                res.capped = True
                break
            try:
                if _supports(self.directory.details, "lean"):
                    full = await self.directory.details(c.place_id, lean=True)
                else:
                    full = await self.directory.details(c.place_id)
            except Exception as e:  # noqa: BLE001
                log.info("places details failed: %s", type(e).__name__)
                res.calls_used += 1
                continue
            res.calls_used += 1
            if full is not None:
                full = full.model_copy(
                    update={"distance_km": c.distance_km if c.distance_km is not None else full.distance_km}
                )
                cands[i] = full
        final: list[BusinessCandidate] = []
        seen_phone: set[str] = set()
        seen_name: set[str] = set()
        for c in sorted(cands, key=lambda c: score(c, when), reverse=True):
            if not c.phone or not self._basic_ok(c, point, exclude):
                continue
            pk = phone_key(c.phone)
            nk = f"{c.name.lower().strip()}|{round(c.location.lat, 3) if c.location else 0}"
            if pk in seen_phone or nk in seen_name:
                continue
            if self.pool is not None and await self.pool.is_blocked(c.phone):
                continue  # DNC: never even shown
            seen_phone.add(pk)
            seen_name.add(nk)
            final.append(c)
            if len(final) >= limit:
                break
        res.vendors = [self._vendor(c, when) for c in final]
        return res

    def _basic_ok(
        self, c: BusinessCandidate, point: GeoPoint, exclude: set[str] | None
    ) -> bool:
        if exclude and c.place_id in exclude:
            return False
        if c.rating is not None and c.rating < self.min_rating:
            return False
        dist = c.distance_km
        if dist is None and c.location is not None:
            dist = haversine_km(point, c.location)
        return not (dist is not None and dist > self.radius_km)

    def _qualified(
        self, items: Any, point: GeoPoint, exclude: set[str] | None
    ) -> list[BusinessCandidate]:
        return [c for c in items if self._basic_ok(c, point, exclude)]

    @staticmethod
    def _vendor(c: BusinessCandidate, when: datetime | None) -> Vendor:
        return Vendor(
            place_id=c.place_id,
            name=c.name,
            phone=c.phone or "",
            rating=c.rating,
            review_count=c.review_count,
            distance_km=c.distance_km,
            address=c.address,
            category=c.category,
            open_now=_open_then(c, when),
        )

    def candidate_for(self, v: Vendor) -> BusinessCandidate:
        return BusinessCandidate(
            provider=getattr(self.directory, "name", "directory"),
            place_id=v.place_id,
            name=v.name,
            phone=v.phone,
            category=v.category or "salon",
            address=v.address,
            rating=v.rating,
            review_count=v.review_count,
            distance_km=v.distance_km,
        )
