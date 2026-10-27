# ruff: noqa: E501
"""Chat commands and buttons of the trip thread ("meri trip", "kab nikalna hai", button ids
``trip:<trip_id>:<action>[:<task_id>]``). Not wired into the live router yet (docs/TRIP_TIMELINE.md);
the service is complete without it. Returns ``None`` for anything that is not a trip command."""

from __future__ import annotations

import re

from friday.trips.copy import t
from friday.trips.service import TripReply, TripsDisabled, TripService

_PLAN = re.compile(
    r"\b(meri|mera|my)\s+trip\b|\btrip\s+(plan|dikhao|show)\b|\bdin\s*-?\s*ba\s*-?\s*din\b", re.I
)
_LEAVE = re.compile(
    r"\bkab\s+nikal(na|u|oon)?\b|\bnikalna\s+kab\b|\bwhen\s+(do\s+i|should\s+i)\s+leave\b|\bleave\s+by\b",
    re.I,
)
_MUTE = re.compile(r"^\s*trip\s+mute\s*$", re.I)
_UNMUTE = re.compile(r"^\s*trip\s+unmute\s*$", re.I)
_TRAVEL = re.compile(
    r"\b(?:airport|station)\s+tak\s+(\d{1,3})\s*(?:min|minute|mins)\b|\b(\d{1,3})\s*(?:min|minutes?)\s+to\s+the\s+(?:airport|station)\b",
    re.I,
)
_PICKUP = re.compile(r"^\s*pickup\s*[:\-]\s*(.{3,160})$", re.I)
_NUMBER = re.compile(r"\bhotel\s+(?:ka\s+)?number\s*[:\-]?\s*(\+?[0-9][0-9 \-]{6,17}[0-9])", re.I)


class TripCommands:
    def __init__(self, service: TripService) -> None:
        self.svc = service

    async def handle_text(self, user_id: str, text: str) -> TripReply | None:
        svc = self.svc
        if not svc.enabled_for(user_id):
            return None
        try:
            if _MUTE.match(text) or _UNMUTE.match(text):
                trip = await svc._trip_for(user_id, None)
                return (
                    await svc.set_muted(user_id, trip.id, bool(_MUTE.match(text)))
                    if trip
                    else TripReply(t("no_trip", svc.lang))
                )
            if _LEAVE.search(text):
                return await svc.leave_text(user_id)
            if _PLAN.search(text):
                return await svc.plan_text(user_id)
            m, p, n = _TRAVEL.search(text), _PICKUP.match(text), _NUMBER.search(text)
            if not (m or p or n):
                return None
            trip = await svc._trip_for(user_id, None)
            if trip is None:
                return TripReply(t("no_trip", svc.lang))
            if m:
                return await svc.set_travel_minutes(user_id, trip.id, int(m.group(1) or m.group(2)))
            if p:
                return await svc.set_pickup_address(user_id, trip.id, p.group(1))
            if n:
                return await svc.provide_hotel_number(user_id, trip.id, n.group(1))
        except TripsDisabled:
            return None
        return None

    async def handle_button(self, user_id: str, button_id: str) -> TripReply | None:
        parts = button_id.split(":")
        if len(parts) < 3 or parts[0] != "trip" or not self.svc.enabled_for(user_id):
            return None
        trip_id, action = parts[1], parts[2]
        if action == "plan":
            return await self.svc.plan_text(user_id, trip_id)
        task_id = parts[3] if len(parts) > 3 else ""
        task = await self.svc.store.get_task(user_id, task_id) if task_id else None
        if task is None or task.trip_id != trip_id:  # a button of another trip/user does nothing
            return TripReply(t("task.unknown", self.svc.lang))
        if action == "ok":
            return await self.svc.approve_task(user_id, task_id)
        if action == "no":
            return await self.svc.skip_task(user_id, task_id)
        return None
