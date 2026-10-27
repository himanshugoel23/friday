"""Confirmed documents (or the user's own words) -> a trip and its legs.

Only CONFIRMED documents are used; a field the document does not have is never invented (a hotel
phone, a check-in time). A duplicate document (same booking reference and date) updates the leg it
already made instead of making a second one. Time zones come from the airport table; an airport it
does not know is stated as an assumption, never silently guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from friday.core.clock import Clock
from friday.docunderstand.models import DocStatus, DocType, Document
from friday.trips.airports import IST_ZONE, airport_zone, is_international, local_to_utc
from friday.trips.copy import clean_name
from friday.trips.models import LegKind, Trip, TripLeg, TripStatus
from friday.trips.store import MemoryTripStore

GROUP_GAP_DAYS = 2  # a leg within this many days of a trip's dates belongs to that trip

_DT = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")
_PHONE = re.compile(r"^\+?[0-9][0-9 \-]{6,17}[0-9]$")


def parse_local_dt(value: str | None) -> datetime | None:
    m = _DT.match((value or "").strip())
    if not m:
        return None
    try:
        return datetime(*(int(x) for x in m.groups()))
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def parse_time(value: str | None) -> time | None:
    m = re.match(r"^(\d{1,2}):(\d{2})", (value or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return time(h, mi) if h < 24 and mi < 60 else None


def _code(value: str | None) -> str | None:
    v = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return v or None


def _clean_phone(value: str | None) -> str | None:
    v = (value or "").strip()
    return re.sub(r"[ \-]", "", v) if _PHONE.match(v) else None


@dataclass
class LegDraft:
    """A leg before it belongs to a trip, plus the dates it covers (for grouping)."""

    leg: TripLeg
    first_day: date
    last_day: date


def leg_from_fields(
    doc_type: DocType,
    v: dict[str, str],
    *,
    document_id: str | None = None,
    pointer_kind: str | None = None,
    stay_tz: str | None = None,
) -> LegDraft | None:
    """One leg from a document's field values (or a user's typed ones). None when the fields are
    not enough to place it in time (never guessed)."""
    base: dict[str, Any] = {
        "user_id": "",
        "trip_id": "",
        "document_id": document_id,
        "pointer_kind": pointer_kind,
    }
    if doc_type == DocType.FLIGHT:
        dep = parse_local_dt(v.get("dep_local"))
        if dep is None:
            return None
        o, d = _code(v.get("from_iata")), _code(v.get("to_iata"))
        oz, dz = airport_zone(o), airport_zone(d)
        assumptions: list[str] = []
        if oz is None or (d and dz is None):
            assumptions.append("tz_assumed")
        intl, intl_assumed = is_international(o, d)
        if intl_assumed:
            assumptions.append("intl_assumed")
        tz = oz.key if oz else IST_ZONE
        end_tz = dz.key if dz else IST_ZONE
        starts = local_to_utc(dep, ZoneInfo(tz))
        arr = parse_local_dt(v.get("arr_local"))
        ends = local_to_utc(arr, ZoneInfo(end_tz)) if arr else None
        if ends is not None and ends <= starts:
            ends = None
            assumptions.append("arrival_unreadable")
        number = _code(v.get("flight_no"))
        ref = _code(v.get("pnr"))
        label = clean_name(f"{v.get('airline', '')} {v.get('flight_no', '')}".strip(), 40) or None
        dep_day = dep.date()
        key = f"flight:{ref or number or f'{o}-{d}'}:{dep_day.isoformat()}"
        leg = TripLeg(
            kind=LegKind.FLIGHT,
            starts_at=starts,
            ends_at=ends,
            tz=tz,
            end_tz=end_tz,
            origin=o,
            dest=d,
            ref=ref,
            label=label,
            number=number,
            terminal=clean_name(v.get("terminal"), 10) or None,
            international=intl,
            assumptions=assumptions,
            dedupe_key=key,
            **base,
        )
        last = arr.date() if arr else dep_day
        return LegDraft(leg, dep_day, max(last, dep_day))
    if doc_type == DocType.TRAIN:
        dep = parse_local_dt(v.get("dep_local"))
        if dep is None:
            return None
        arr = parse_local_dt(v.get("arr_local"))
        starts = local_to_utc(dep, ZoneInfo(IST_ZONE))
        ends = local_to_utc(arr, ZoneInfo(IST_ZONE)) if arr else None
        assumptions = []
        if ends is not None and ends <= starts:
            ends = None
            assumptions.append("arrival_unreadable")
        number = _code(v.get("train_no"))
        ref = _code(v.get("pnr"))
        origin = clean_name(v.get("boarding_station") or v.get("from_station"), 40) or None
        dest = clean_name(v.get("to_station"), 40) or None
        label = clean_name(f"{v.get('train_no', '')} {v.get('train_name', '')}".strip(), 40) or None
        leg = TripLeg(
            kind=LegKind.TRAIN,
            starts_at=starts,
            ends_at=ends,
            tz=IST_ZONE,
            end_tz=IST_ZONE,
            origin=origin,
            dest=dest,
            ref=ref,
            label=label,
            number=number,
            international=False,
            assumptions=assumptions,
            dedupe_key=f"train:{ref or number}:{dep.date().isoformat()}",
            **base,
        )
        return LegDraft(leg, dep.date(), max(arr.date() if arr else dep.date(), dep.date()))
    if doc_type == DocType.HOTEL:
        cin = parse_date(v.get("check_in_date"))
        name = clean_name(v.get("property_name"), 60)
        if cin is None or not name:
            return None
        tz = stay_tz or IST_ZONE
        cin_t = parse_time(v.get("check_in_time"))
        starts = datetime.combine(cin, cin_t or time(0, 0), tzinfo=ZoneInfo(tz)).astimezone(UTC)
        cout = parse_date(v.get("check_out_date"))
        assumptions = []
        ends = None
        if cout is not None and cout >= cin:
            cout_t = parse_time(v.get("check_out_time"))
            if cout_t is None:
                assumptions.append("checkout_time_unknown")
            ends = datetime.combine(cout, cout_t or time(12, 0), tzinfo=ZoneInfo(tz)).astimezone(
                UTC
            )
        ref = _code(v.get("confirmation_no"))
        leg = TripLeg(
            kind=LegKind.STAY,
            starts_at=starts,
            ends_at=ends,
            tz=tz,
            end_tz=tz,
            dest=None,
            ref=ref,
            label=name,
            phone=_clean_phone(v.get("phone")),
            address=clean_name(v.get("address"), 120) or None,
            time_known=cin_t is not None,
            assumptions=assumptions,
            dedupe_key=f"stay:{ref or name.lower()}:{cin.isoformat()}",
            **base,
        )
        return LegDraft(leg, cin, max(cout or cin, cin))
    return None


def trip_title(draft: LegDraft) -> str:
    leg = draft.leg
    if leg.kind in (LegKind.FLIGHT, LegKind.TRAIN) and leg.dest:
        return clean_name(f"{leg.dest} trip", 40)
    if leg.kind == LegKind.STAY and leg.label:
        return clean_name(f"{leg.label} trip", 40)
    return "Trip"


@dataclass
class BuildResult:
    trips: list[Trip] = field(default_factory=list)  # every trip touched
    new_trip_ids: set[str] = field(default_factory=set)
    legs_added: int = 0
    legs_updated: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (document id, reason)


USABLE = (DocType.FLIGHT, DocType.TRAIN, DocType.HOTEL)


class TripBuilder:
    def __init__(self, store: MemoryTripStore | Any, clock: Clock) -> None:
        self.store, self.clock = store, clock

    # ------------------------------------------------------------------ documents
    async def from_documents(self, user_id: str, docs: list[Document]) -> BuildResult:
        res = BuildResult()
        usable: list[Document] = []
        # flights first: a hotel takes the zone of the airport its guest arrives at
        order = {DocType.FLIGHT: 0, DocType.TRAIN: 1, DocType.HOTEL: 2}
        for d in sorted((d for d in docs if d.doc_type in USABLE), key=lambda d: order[d.doc_type]):
            if d.user_id != user_id:
                res.skipped.append((d.id, "not_yours"))
                continue
            if d.status != DocStatus.CONFIRMED:
                res.skipped.append((d.id, "not_confirmed"))
                continue
            usable.append(d)
        for d in (d for d in docs if d.doc_type not in USABLE):
            res.skipped.append((d.id, "not_a_travel_document"))
        drafts: list[LegDraft] = []
        arrivals: list[tuple[date, str]] = []  # (arrival day, zone) of flights seen so far
        for d in usable:
            vals = d.values()
            stay_tz = None
            if d.doc_type == DocType.HOTEL:
                cin = parse_date(vals.get("check_in_date"))
                cands = [z for day, z in arrivals if cin and abs((day - cin).days) <= 1]
                stay_tz = cands[-1] if cands else None
            draft = leg_from_fields(
                d.doc_type, vals, document_id=d.id, pointer_kind=d.pointer_kind, stay_tz=stay_tz
            )
            if draft is None:
                res.skipped.append((d.id, "not_enough_fields"))
                continue
            if d.doc_type == DocType.FLIGHT and draft.leg.end_tz:
                arrivals.append((draft.last_day, draft.leg.end_tz))
            drafts.append(draft)
        # a stay spans the days between a trip's flights, so it is placed first and the flights
        # on either side join it
        for draft in sorted(drafts, key=lambda x: (x.leg.kind != LegKind.STAY, x.first_day)):
            await self._place(user_id, draft, res, created_from="doc")
        return res

    # ------------------------------------------------------------------ the user's own words
    async def from_user(
        self, user_id: str, doc_type: DocType, values: dict[str, str]
    ) -> BuildResult:
        res = BuildResult()
        draft = leg_from_fields(doc_type, values)
        if draft is None:
            res.skipped.append(("user", "not_enough_fields"))
            return res
        await self._place(user_id, draft, res, created_from="user")
        return res

    async def new_trip(
        self, user_id: str, title: str, start: date, end: date, *, created_from: str = "user"
    ) -> Trip:
        now = self.clock.now()
        trip = Trip(
            user_id=user_id,
            title=clean_name(title, 40) or "Trip",
            start_date=start,
            end_date=max(start, end),
            created_from=created_from,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_trip(trip)
        return trip

    # ------------------------------------------------------------------ placing a leg
    async def _place(
        self,
        user_id: str,
        draft: LegDraft,
        res: BuildResult,
        *,
        created_from: str,
        trip_id: str | None = None,
    ) -> None:
        leg = draft.leg
        leg.user_id = user_id
        existing = await self.store.find_leg(user_id, leg.dedupe_key)
        if existing is not None:  # the same booking again: update, never duplicate
            leg.id, leg.trip_id, leg.created_at = existing.id, existing.trip_id, existing.created_at
            trip = await self.store.get_trip(user_id, existing.trip_id)
            changed = leg.model_dump() != existing.model_dump()
            if changed:
                await self.store.save_leg(leg)
                res.legs_updated += 1
            if trip is not None and trip not in res.trips:
                res.trips.append(trip)
            return
        trip = None
        if trip_id:
            trip = await self.store.get_trip(user_id, trip_id)
        if trip is None:
            for t in await self.store.list_trips(user_id, (TripStatus.ACTIVE, TripStatus.DRAFT)):
                gap = timedelta(days=GROUP_GAP_DAYS)
                if t.start_date - gap <= draft.last_day and draft.first_day <= t.end_date + gap:
                    trip = t
                    break
        now = self.clock.now()
        if trip is None:
            trip = Trip(
                user_id=user_id,
                title=trip_title(draft),
                start_date=draft.first_day,
                end_date=draft.last_day,
                created_from=created_from,
                created_at=now,
                updated_at=now,
            )
            res.new_trip_ids.add(trip.id)
        else:
            trip.start_date = min(trip.start_date, draft.first_day)
            trip.end_date = max(trip.end_date, draft.last_day)
            trip.updated_at = now
        await self.store.save_trip(trip)
        leg.trip_id = trip.id
        await self.store.save_leg(leg)
        res.legs_added += 1
        res.trips = [t for t in res.trips if t.id != trip.id] + [trip]
