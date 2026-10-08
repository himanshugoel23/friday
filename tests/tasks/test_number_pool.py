"""NP-2: caller-ID pool - sticky, local presence, pacing, warm-up, health, cooling,
retire + forwarding, pool-wide DNC."""

from datetime import datetime, timedelta

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.events import EventBus, NumberStatusChanged
from friday.core.interfaces import NumberPool
from friday.core.models import FridayNumber, NumberOutcome, NumberStatus
from friday.tasks.number_pool import Pool, locality

BLR = "+918069110001"
PUNE = "+912069110002"
SALON = "+918040000001"  # Bengaluru
CLINIC = "+912040000002"  # Pune


def make(numbers=(BLR, PUNE), **kw):
    clock = FakeClock(datetime(2026, 1, 5, 11, 0, tzinfo=IST))
    bus = EventBus()
    s = Settings(_env_file=None, friday_numbers=list(numbers), **kw)
    return Pool(s, clock=clock, bus=bus), clock, bus


def test_protocol_and_locality():
    pool, *_ = make()
    assert isinstance(pool, NumberPool)
    assert locality(SALON) == ("Bengaluru", "KA") and locality("+919812345678") == (None, None)
    with pytest.raises(ValueError):
        FridayNumber(phone="+911401234567", provider="x")  # 140-series never allowed


async def test_local_presence_and_sticky():
    pool, clock, _ = make()
    c1 = await pool.choose_for(CLINIC)
    assert c1.number.phone == PUNE and not c1.sticky and c1.not_before is None
    await pool.release(PUNE)
    clock.advance(minutes=5)
    c2 = await pool.choose_for(CLINIC)
    assert c2.number.phone == PUNE and c2.sticky and not c2.changed
    c3 = await pool.choose_for(SALON)
    assert c3.number.phone == BLR


async def test_pacing_no_bursts_and_release():
    pool, clock, _ = make(numbers=(BLR,), number_max_concurrent=1)
    first = await pool.choose_for(SALON)
    assert first.not_before is None
    second = await pool.choose_for("+918040000003")  # same number: concurrency + min gap
    assert second.number.phone == BLR and second.not_before is not None
    await pool.release(BLR)
    clock.advance(seconds=44)
    assert (await pool.choose_for("+918040000003")).not_before is not None  # min gap 45s
    clock.advance(seconds=2)
    assert (await pool.choose_for("+918040000003")).not_before is None


async def test_hourly_cap():
    pool, clock, _ = make(numbers=(BLR,), number_max_calls_per_hour=2, number_min_gap_s=0)
    for _ in range(2):
        assert (await pool.choose_for(SALON)).not_before is None
        await pool.release(BLR)
    nb = (await pool.choose_for(SALON)).not_before
    assert nb == clock.now() + timedelta(hours=1)


async def test_warmup_daily_cap():
    pool, clock, _ = make(numbers=(), number_warmup_daily_caps=[2, 5], number_min_gap_s=0)
    await pool.add_number(
        FridayNumber(phone=BLR, provider="sim", status=NumberStatus.WARMING, created_at=clock.now())
    )
    for _ in range(2):
        assert (await pool.choose_for(SALON)).not_before is None
        await pool.release(BLR)
    blocked = await pool.choose_for(SALON)
    assert blocked.not_before is not None and blocked.not_before > clock.now() + timedelta(hours=10)
    # next day: warm-up day 1 -> cap 5; after the ramp -> ACTIVE
    clock.advance(days=1)
    await pool.rescore()
    assert (await pool.list_numbers())[0].warmup_day == 1
    clock.advance(days=1)
    changed = await pool.rescore()
    assert changed and changed[0].status == NumberStatus.ACTIVE


async def test_dnc_on_one_number_blocks_whole_pool():
    pool, *_ = make()
    c = await pool.choose_for(SALON)
    await pool.record_outcome(c.number.phone, NumberOutcome.DNC_REQUEST, business_phone=SALON)
    assert await pool.is_blocked(SALON)
    assert await pool.choose_for(SALON) is None  # no rotation around a DNC
    await pool.record_outcome(PUNE, NumberOutcome.BLOCKED, business_phone=CLINIC)
    assert await pool.choose_for(CLINIC) is None


async def test_health_cooling_retire_and_forwarding():
    pool, clock, bus = make(
        numbers=(BLR, PUNE), number_cooldown_h=1, number_max_cooldowns_before_retire=1
    )
    events = []

    async def on(ev):
        events.append(ev)

    bus.subscribe(NumberStatusChanged, on)
    c = await pool.choose_for(SALON)
    assert c.number.phone == BLR
    for _ in range(12):
        await pool.record_outcome(BLR, NumberOutcome.NO_ANSWER, business_phone=SALON)
    assert (await pool.health(BLR)).score < 0.5
    changed = await pool.rescore()
    assert [n.status for n in changed] == [NumberStatus.COOLING]
    assert events[-1].new == "cooling"
    # sticky business waits for its cooling number (never moved, never dialled now)
    wait = await pool.choose_for(SALON)
    assert wait.number.phone == BLR and wait.not_before is not None
    # cooling numbers never dial for new businesses
    other = await pool.choose_for("+918040000099")
    assert other.number.phone == PUNE
    clock.advance(hours=2)
    await pool.rescore()
    assert {n.phone: n.status for n in await pool.list_numbers()}[BLR] == NumberStatus.ACTIVE
    for _ in range(12):
        await pool.record_outcome(BLR, NumberOutcome.SHORT_CALL)
    await pool.rescore()  # second cooldown > max 1 -> retired
    n = {n.phone: n for n in await pool.list_numbers()}[BLR]
    assert n.status == NumberStatus.RETIRED and n.forward_until is not None
    moved = await pool.choose_for(SALON)
    assert moved.number.phone == PUNE and moved.changed and not moved.sticky
    assert (await pool.owner_of(BLR)).phone == BLR  # still forwards call-backs
    clock.advance(days=31)
    assert await pool.owner_of(BLR) is None


async def test_short_call_and_ops_override():
    pool, *_ = make()
    await pool.record_outcome(BLR, NumberOutcome.ANSWERED, duration_s=3)
    assert (await pool.health(BLR)).short_calls == 1
    await pool.set_status(PUNE, NumberStatus.COOLING, reason="spam label")
    await pool.set_status(BLR, NumberStatus.RETIRED, reason="carrier")
    assert await pool.choose_for(SALON) is None  # nothing can dial
    await pool.set_status(PUNE, NumberStatus.ACTIVE, reason="cleared")
    assert (await pool.choose_for(SALON)).number.phone == PUNE
    with pytest.raises(KeyError):
        await pool.set_status("+918000000000", NumberStatus.ACTIVE, reason="x")


def test_factory(settings):
    from friday.core.container import Container

    assert isinstance(Container(settings).number_pool, NumberPool)
