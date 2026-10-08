"""No Expedia keys (hotels disabled): the hotel task uses the direct-call path only, the user is
told plainly that live rates are not available, and no API rate or booking is invented."""

from __future__ import annotations

from datetime import date

from friday.core.models import StayRequest, TaskSpec, TaskType
from friday.tasks.engine import HOTEL_NO_LIVE_RATES


async def test_hotel_task_without_provider_tells_user_and_calls_directly(env):
    env.container.override("hotels", None)  # what _opt() yields for a disabled component
    stay = StayRequest(
        destination="Udaipur", check_in=date(2026, 1, 20), check_out=date(2026, 1, 22)
    )
    t = await env.task(TaskSpec(type=TaskType.HOTEL_BOOKING, goal="Stay in Udaipur", stay=stay))
    assert HOTEL_NO_LIVE_RATES in env.texts()
    assert "live hotel rates" in HOTEL_NO_LIVE_RATES and "before booking" in HOTEL_NO_LIVE_RATES
    assert not t.result or not t.result.hotel_offers  # no API rates at all
    assert not env.repos.tasks.hotel_bookings  # nothing booked without the user's approval
