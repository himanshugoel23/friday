from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import EventBus, TaskStatusChanged
from friday.core.models import Profile, TaskSpec, TaskStatus, TaskType, User
from friday.discovery.hotels.simulator import SimulatedHotels
from friday.discovery.official_numbers import OfficialNumbers
from friday.discovery.simulator import SimulatedDirectory, SimulatedGeocoder
from friday.discovery.verify import NumberVerifierImpl
from friday.simworld import load_world
from friday.tasks.engine import TaskEngine
from friday.tasks.policy import TaskPolicy
from tests.tasks.fakes import FakeBrain, RecordingNotifier, Repos, StubRunner

LOOKS = "+918040000001"
COOL = "+918040000003"
FROSTY = "+918040000004"
CHILL = "+918040000005"
RAJU = "+918040000012"
AIRTEL = "+911800000121"
SCAM = "+919000011111"


@dataclass
class Env:
    engine: TaskEngine
    repos: Repos
    brain: FakeBrain
    runner: StubRunner
    notifier: RecordingNotifier
    clock: FakeClock
    bus: EventBus
    container: Container
    user: User
    transitions: list[tuple] = field(default_factory=list)

    async def task(self, spec: TaskSpec, **kw):
        t = await self.engine.create_task(self.user.id, spec, **kw)
        await self.engine.drain()
        return await self.repos.tasks.get(t.id)

    async def get(self, task_id):
        return await self.repos.tasks.get(task_id)

    def texts(self):
        return self.notifier.texts(self.user.id)

    async def advance_and_tick(self, **delta):
        self.clock.advance(**delta)
        n = await self.engine.tick()
        await self.engine.drain()
        return n


ALL_TRANSITIONS: set[tuple] = set()  # observed across the whole session (see test_states)


@pytest.fixture
def env_settings() -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        google_places_api_key=None,
        twilio_from_number=None,
    )


@pytest.fixture
async def env(env_settings) -> Env:
    # Mon 05 Jan 2026, 11:00 IST: Looks Salon open, inside the call window, not lunch
    clock = FakeClock(datetime(2026, 1, 5, 11, 0, tzinfo=IST))
    bus = EventBus()
    c = Container(env_settings, clock=clock, bus=bus)
    repos = Repos()
    brain = FakeBrain()
    runner = StubRunner()
    notifier = RecordingNotifier()
    world = load_world()
    official = OfficialNumbers.from_file(sim=world)
    directory = SimulatedDirectory(world, clock=clock)
    scam = {b.phone for b in world.businesses if b.scam}
    c.override("repos", repos)
    c.override("brain", brain)
    c.override("call_runner", runner)
    c.override("notifier", notifier)
    c.override("directory", directory)
    c.override("geocoder", SimulatedGeocoder(world))
    c.override("hotels", SimulatedHotels(world, clock=clock))
    c.override("official_numbers", official)
    c.override(
        "number_verifier",
        NumberVerifierImpl(
            scam_numbers=scam,
            official=official,
            directory=directory,
            businesses=repos.businesses,
            clock=clock,
        ),
    )
    engine = TaskEngine(c, policy=TaskPolicy(caller_ids=["+918069110001", "+918069110002"]))
    c.override("task_engine", engine)
    user = User(phone="+919811111111")
    await repos.users.add(user)
    await repos.profiles.add(Profile(user_id=user.id, name="Rahul"))
    e = Env(engine, repos, brain, runner, notifier, clock, bus, c, user)

    async def on_change(ev: TaskStatusChanged):
        e.transitions.append((ev.old, ev.new))
        if ev.old is not None:
            ALL_TRANSITIONS.add((ev.old, ev.new))

    bus.subscribe(TaskStatusChanged, on_change)
    yield e
    await engine.aclose()


def booking(phone=LOOKS, name="Looks Unisex Salon", **kw) -> TaskSpec:
    return TaskSpec(
        type=TaskType.BOOKING,
        goal="Haircut for Rahul tomorrow evening",
        business_name=name,
        business_phone=phone,
        **kw,
    )


__all__ = ["TaskStatus", "booking"]
