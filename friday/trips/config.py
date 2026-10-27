"""Numbers of the trip timeline. Every default is a PROPOSAL the founder approves (HANDOFF)."""

from __future__ import annotations

from dataclasses import dataclass

from friday.core.config import Settings


@dataclass(frozen=True)
class TripConfig:
    # time to be at the airport / station before departure (docs/TRIP_CONCIERGE_DESIGN.md F)
    domestic_buffer_min: int = 120
    international_buffer_min: int = 180
    train_buffer_min: int = 45
    default_travel_min: int = 60  # used (and stated) when the user has not told the travel time
    leave_heads_up_min: int = 30  # the "nikalna hai" nudge goes out this long before leave-by
    # hotel
    hotel_call_hour: int = 10  # local hour, the day before check-in
    hotel_default_checkin_hour: int = 8  # info nudge hour when the check-in time is unknown
    checkout_heads_up_hours: int = 2
    # cab
    cab_propose_hours_before: int = 12
    # morning plan
    day_plan_hour: int = 8
    # flight / train watch
    watch_enabled: bool = False
    watch_start_hours: int = 24
    watch_every_hours: int = 3
    watch_last_hours: int = 6  # inside this window the poll is hourly
    watch_last_every_min: int = 60
    watch_stop_after_min: int = 60  # stop this long after the departure
    delay_threshold_min: int = 15  # a smaller shift is not worth a message
    stale_status_min: int = 180  # data older than this is labelled with its age
    watch_backoff_min: int = 30  # wait after a provider failure
    # lounge
    lounge_enabled: bool = False
    lounge_hours_before: int = 24
    # nudges
    daily_cap: int = 5
    critical_bypasses_quiet_hours: bool = True
    quiet_start: int = 22
    quiet_end: int = 8
    nudge_ignored_after_hours: int = 24
    retention_days: int = 30

    @classmethod
    def from_settings(cls, s: Settings) -> TripConfig:
        return cls(
            domestic_buffer_min=s.trip_domestic_buffer_minutes,
            international_buffer_min=s.trip_international_buffer_minutes,
            train_buffer_min=s.trip_train_buffer_minutes,
            default_travel_min=s.trip_default_travel_minutes,
            hotel_call_hour=s.trip_hotel_call_hour,
            cab_propose_hours_before=s.trip_cab_propose_hours_before,
            watch_enabled=s.trip_flight_watch_enabled,
            lounge_enabled=s.trip_lounge_enabled,
            daily_cap=s.trip_daily_cap,
            critical_bypasses_quiet_hours=s.trip_critical_bypasses_quiet_hours,
            quiet_start=s.quiet_hours_start,
            quiet_end=s.quiet_hours_end,
            retention_days=s.trips_retention_days,
        )
