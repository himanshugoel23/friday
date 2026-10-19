"""Google Calendar for one connected user (scope ``calendar.events`` only).

Times are aware datetimes; naive input is read as ``Asia/Kolkata`` (the default zone) and all
results come back in that zone. Event creation is idempotent: the event id is derived from the
caller's idempotency key, so a retry after a timeout returns the same event instead of a second
one (Google answers 409 for a repeated id). Deleted events keep their id reserved at Google; a
retry with the same key then re-confirms the event.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from friday.core.config import Settings
from friday.google import scopes as sc
from friday.google.oauth import GoogleError, GoogleOAuth, default_http

DEFAULT_TZ = ZoneInfo("Asia/Kolkata")
_MAX_PAGES = 10


class CalendarError(GoogleError):
    code = "calendar_error"


class InvalidTimeRange(ValueError):
    pass


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool = False
    busy: bool = True
    location: str | None = None


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def event_id_for(user_id: str, idempotency_key: str) -> str:
    """Deterministic Google event id (base32hex alphabet: 0-9a-v) for an idempotency key."""
    digest = hashlib.sha256(f"{user_id}\x00{idempotency_key}".encode()).hexdigest()
    return "fri" + digest[:40]


class CalendarClient:
    def __init__(
        self,
        oauth: GoogleOAuth,
        user_id: str,
        *,
        settings: Settings,
        tz: ZoneInfo = DEFAULT_TZ,
        http: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.oauth, self.user_id, self.tz = oauth, user_id, tz
        self.base = settings.google_calendar_base_url.rstrip("/")
        self._http = http or default_http

    # ------------------------------------------------------------------ time helpers
    def aware(self, dt: datetime) -> datetime:
        return dt.replace(tzinfo=self.tz) if dt.tzinfo is None else dt.astimezone(self.tz)

    def _range(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        s, e = self.aware(start), self.aware(end)
        if e <= s:
            raise InvalidTimeRange("end must be after start")
        return s, e

    def _parse(self, item: dict[str, Any]) -> CalendarEvent | None:
        if item.get("status") == "cancelled":
            return None
        st, en = item.get("start") or {}, item.get("end") or {}
        all_day = "date" in st and "dateTime" not in st
        try:
            if all_day:
                s = datetime.combine(date.fromisoformat(st["date"]), time.min, self.tz)
                e = datetime.combine(date.fromisoformat(en["date"]), time.min, self.tz)
            else:
                s = datetime.fromisoformat(st["dateTime"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(en["dateTime"].replace("Z", "+00:00"))
                s, e = self.aware(s), self.aware(e)
        except (KeyError, ValueError):
            return None
        return CalendarEvent(
            id=str(item.get("id", "")),
            summary=str(item.get("summary") or "(no title)"),
            start=s,
            end=e,
            all_day=all_day,
            busy=item.get("transparency", "opaque") != "transparent",
            location=item.get("location"),
        )

    # ------------------------------------------------------------------ HTTP
    async def _request(
        self, method: str, path: str, *, ok: tuple[int, ...] = (200,), **kw: Any
    ) -> httpx.Response:
        url = f"{self.base}{path}"
        token = await self.oauth.access_token(self.user_id, scope=sc.CALENDAR_EVENTS)
        for attempt in (1, 2):
            try:
                async with self._http() as client:
                    r = await client.request(
                        method, url, headers={"Authorization": f"Bearer {token}"}, **kw
                    )
            except httpx.HTTPError as e:
                raise CalendarError(
                    f"calendar unreachable ({type(e).__name__})", code="unreachable"
                ) from None
            if r.status_code == 401 and attempt == 1:
                token = await self.oauth.force_refresh(self.user_id)
                continue
            if r.status_code not in ok:
                raise CalendarError(
                    f"calendar returned {r.status_code}", code=f"http_{r.status_code}"
                )
            return r
        raise CalendarError("calendar rejected the token", code="http_401")  # pragma: no cover

    # ------------------------------------------------------------------ reads
    async def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEvent]:
        s, e = self._range(time_min, time_max)
        params: dict[str, Any] = {
            "timeMin": s.isoformat(),
            "timeMax": e.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        }
        out: list[CalendarEvent] = []
        for _ in range(_MAX_PAGES):
            r = await self._request("GET", "/calendars/primary/events", params=params)
            body = r.json()
            out += [ev for it in body.get("items", []) if (ev := self._parse(it))]
            token = body.get("nextPageToken")
            if not token:
                break
            params = {**params, "pageToken": token}
        return sorted(out, key=lambda ev: ev.start)

    async def clashes(
        self, proposed_start: datetime, proposed_end: datetime
    ) -> list[CalendarEvent]:
        """Busy events overlapping [start, end). Touching edges (one ends when the other
        starts) is not a clash; events marked "free" at Google are ignored."""
        s, e = self._range(proposed_start, proposed_end)
        events = await self.list_events(s, e)
        return [ev for ev in events if ev.busy and ev.start < e and ev.end > s]

    async def find_free_slots(
        self,
        window_start: datetime,
        window_end: datetime,
        duration: timedelta,
        *,
        limit: int = 5,
    ) -> list[Slot]:
        """Free gaps of at least ``duration`` inside the window, earliest first. Each slot is
        the whole gap (not cut to ``duration``); the caller picks a start inside it."""
        if duration <= timedelta(0):
            raise InvalidTimeRange("duration must be positive")
        w0, w1 = self._range(window_start, window_end)
        events = await self.list_events(w0, w1)
        busy = sorted((max(ev.start, w0), min(ev.end, w1)) for ev in events if ev.busy)
        slots: list[Slot] = []
        cursor = w0
        for b0, b1 in busy:
            if b0 - cursor >= duration:
                slots.append(Slot(cursor, b0))
            cursor = max(cursor, b1)
        if w1 - cursor >= duration:
            slots.append(Slot(cursor, w1))
        return slots[:limit]

    # ------------------------------------------------------------------ writes
    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        *,
        idempotency_key: str,
        location: str | None = None,
        description: str | None = None,
    ) -> CalendarEvent:
        s, e = self._range(start, end)
        eid = event_id_for(self.user_id, idempotency_key)
        zone = str(self.tz.key)
        body: dict[str, Any] = {
            "id": eid,
            "summary": summary[:300],
            "start": {"dateTime": s.isoformat(), "timeZone": zone},
            "end": {"dateTime": e.isoformat(), "timeZone": zone},
            "extendedProperties": {
                "private": {
                    "friday_key": hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
                }
            },
        }
        if location:
            body["location"] = location[:300]
        if description:
            body["description"] = description[:2000]
        r = await self._request("POST", "/calendars/primary/events", ok=(200, 201, 409), json=body)
        item = r.json()
        if r.status_code == 409:  # same key seen before: return that event, make no second one
            item = (await self._request("GET", f"/calendars/primary/events/{eid}")).json()
            if item.get("status") == "cancelled":  # deleted earlier: bring it back
                put = await self._request(
                    "PUT", f"/calendars/primary/events/{eid}", json={**body, "status": "confirmed"}
                )
                item = put.json()
        ev = self._parse(item)
        if ev is None:
            raise CalendarError("calendar returned an unreadable event", code="bad_event")
        return ev

    async def delete_event(self, event_id: str) -> bool:
        """True if deleted now; False if it was already gone (idempotent)."""
        r = await self._request(
            "DELETE", f"/calendars/primary/events/{event_id}", ok=(200, 204, 404, 410)
        )
        return r.status_code in (200, 204)
