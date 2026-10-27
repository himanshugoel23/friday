"""Pure derivations: buffers, time zones, assumptions, watch schedule, change detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from friday.core.clock import IST
from friday.docunderstand.models import DocType
from friday.trips.builder import leg_from_fields
from friday.trips.config import TripConfig
from friday.trips.derive import detect_changes, leave_by, next_check_at, plan_leg
from friday.trips.models import TaskKind, Trip
from tests.trips.conftest import FLIGHT_OUT, HOTEL, HOTEL_NOPHONE, INTL_OUT

CFG = TripConfig()


def trip(minutes=None):
    return Trip(
        user_id="u",
        title="t",
        start_date="2026-11-14",
        end_date="2026-11-17",
        travel_minutes=minutes,
    )


def leg_of(values, dt=DocType.FLIGHT, **kw):
    d = leg_from_fields(dt, values, **kw)
    assert d is not None
    return d.leg


@pytest.mark.parametrize(
    "values,travel,expect_minutes",
    [
        (FLIGHT_OUT, 45, 120 + 45),  # domestic: 2 h + travel
        (INTL_OUT, 45, 180 + 45),  # international: 3 h + travel
        (FLIGHT_OUT, None, 120 + 60),  # unknown travel: the stated default (60)
        (FLIGHT_OUT, 0, 120),
    ],
)
def test_leave_by_buffers(values, travel, expect_minutes):
    leg = leg_of(values)
    lb = leave_by(leg, trip(travel), CFG)
    assert leg.starts_at - lb.leave_at == timedelta(minutes=expect_minutes)
    assert lb.travel_assumed is (travel is None)


def test_leave_by_is_configurable():
    cfg = TripConfig(domestic_buffer_min=90, default_travel_min=30)
    lb = leave_by(leg_of(FLIGHT_OUT), trip(), cfg)
    assert lb.buffer_minutes == 90 and lb.travel_minutes == 30


def test_train_buffer():
    leg = leg_of(
        {"train_no": "12345", "from_station": "A", "dep_local": "2026-11-14T06:00"}, DocType.TRAIN
    )
    lb = leave_by(leg, trip(30), CFG)
    assert lb.buffer_kind == "train" and leg.starts_at - lb.leave_at == timedelta(minutes=75)


def test_local_departure_becomes_one_utc_instant_per_airport_zone():
    leg = leg_of(FLIGHT_OUT)
    assert leg.starts_at == datetime(2026, 11, 14, 6, 30, tzinfo=IST).astimezone(UTC)
    intl = leg_of(INTL_OUT)
    # departs 04:00 IST, lands 06:00 Dubai time = 07:30 IST: a 3 h 30 min flight
    assert intl.ends_at - intl.starts_at == timedelta(hours=3, minutes=30)
    assert intl.end_tz == "Asia/Dubai" and intl.tz == "Asia/Kolkata" and intl.international


def test_overnight_arrival_in_another_zone():
    leg = leg_of(
        {
            **FLIGHT_OUT,
            "to_iata": "JFK",
            "dep_local": "2026-11-14T23:00",
            "arr_local": "2026-11-14T23:30",
        }
    )
    # lands 23:30 New York time (UTC-5) = 04:30 UTC next day; left 17:30 UTC: 11 h
    assert leg.ends_at - leg.starts_at == timedelta(hours=11)


def test_unknown_airport_is_international_and_flagged():
    leg = leg_of({**FLIGHT_OUT, "to_iata": "QQQ"})
    assert leg.international and "intl_assumed" in leg.assumptions
    assert "tz_assumed" in leg.assumptions
    assert leave_by(leg, trip(0), CFG).buffer_minutes == 180  # the longer, safer buffer


def test_unreadable_arrival_is_dropped_not_guessed():
    leg = leg_of({**FLIGHT_OUT, "arr_local": "2026-11-14T05:00"})
    assert leg.ends_at is None and "arrival_unreadable" in leg.assumptions


def test_flight_plan_tasks_and_hotel_tasks():
    t = trip(30)
    leg = leg_of(FLIGHT_OUT)
    kinds = {p.kind: p for p in plan_leg(t, leg, CFG)}
    assert set(kinds) == {TaskKind.LEAVE_BY, TaskKind.CAB, TaskKind.FLIGHT_WATCH, TaskKind.LOUNGE}
    leave = datetime.fromisoformat(kinds[TaskKind.LEAVE_BY].params["leave_at"])
    assert kinds[TaskKind.LEAVE_BY].due_at == leave - timedelta(minutes=30)
    assert kinds[TaskKind.CAB].due_at == leave - timedelta(hours=12)
    assert kinds[TaskKind.FLIGHT_WATCH].due_at == leg.starts_at - timedelta(hours=24)
    stay = leg_of(HOTEL, DocType.HOTEL)
    sk = {p.kind: p for p in plan_leg(t, stay, CFG)}
    assert set(sk) == {TaskKind.CHECKIN, TaskKind.HOTEL_CALL, TaskKind.CHECKOUT}
    # the call is due the day before check-in at the configured local hour
    assert sk[TaskKind.HOTEL_CALL].due_at == datetime(2026, 11, 13, 10, 0, tzinfo=IST).astimezone(
        UTC
    )
    assert sk[TaskKind.HOTEL_CALL].params["phone_known"] is True


def test_hotel_without_times_or_phone_is_unknown_not_guessed():
    stay = leg_of({k: v for k, v in HOTEL_NOPHONE.items() if k != "check_in_time"}, DocType.HOTEL)
    assert stay.time_known is False and stay.phone is None


def test_hotel_takes_the_zone_it_is_given():
    stay = leg_of(HOTEL, DocType.HOTEL, stay_tz="Asia/Dubai")
    assert stay.starts_at == datetime(2026, 11, 14, 10, 0, tzinfo=UTC)  # 14:00 Dubai = 10:00 UTC


def test_watch_schedule_backs_off_then_goes_hourly():
    dep = datetime(2026, 11, 14, 1, 0, tzinfo=UTC)
    assert next_check_at(dep - timedelta(hours=48), dep, CFG) == dep - timedelta(hours=24)
    assert next_check_at(dep - timedelta(hours=20), dep, CFG) == dep - timedelta(hours=17)
    assert next_check_at(dep - timedelta(hours=8), dep, CFG) == dep - timedelta(hours=6)
    assert next_check_at(dep - timedelta(hours=3), dep, CFG) == dep - timedelta(hours=2)
    assert next_check_at(dep + timedelta(hours=2), dep, CFG) is None


def test_change_detection_ignores_small_shifts_and_reports_real_ones():
    leg = leg_of(FLIGHT_OUT)

    def det(**kw):
        base = {
            "status": "scheduled",
            "estimated_dep": leg.starts_at,
            "gate": None,
            "terminal": None,
            "cfg": CFG,
        }
        base.update(kw)
        return detect_changes(leg, 0, {}, None, **base)

    assert det() == []
    assert det(estimated_dep=leg.starts_at + timedelta(minutes=10)) == []
    assert det(estimated_dep=leg.starts_at + timedelta(minutes=45))[0].kind == "delay"
    assert det(status="cancelled")[0].kind == "cancelled"
    assert det(gate="B7")[0].kind == "gate"
