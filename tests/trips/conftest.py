"""Fixtures: trips switched on, fakes only, invented documents. Each service test runs over the
in-memory store AND the SQL repository."""

from __future__ import annotations

import hashlib
from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.models import User
from friday.db.repositories import make_repositories
from friday.docunderstand.models import DocField, DocStatus, DocType, Document
from friday.docunderstand.store import MemoryDocStore
from friday.trips.fakes import FakeFlightStatus, FakeTripSender, FakeTripTaskPort
from friday.trips.service import TripService
from friday.trips.store import MemoryTripStore


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 10, 10, 0, tzinfo=IST))


@pytest.fixture
def tsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "trips_enabled": True,
            "trip_flight_watch_enabled": True,
            "trip_lounge_enabled": True,
        }
    )


@pytest.fixture
def repos(db, clock):
    return make_repositories(db, clock, "test-secret")


@pytest.fixture(params=["memory", "sql"])
def store(request, repos):
    return MemoryTripStore() if request.param == "memory" else repos.trips


@pytest.fixture
async def alice(repos) -> User:
    return await repos.users.add(User(phone="+919800000301"))


@pytest.fixture
async def bob(repos) -> User:
    return await repos.users.add(User(phone="+919800000302"))


@pytest.fixture
def docs() -> MemoryDocStore:
    return MemoryDocStore()


@pytest.fixture
def sender() -> FakeTripSender:
    return FakeTripSender()


@pytest.fixture
def taskport() -> FakeTripTaskPort:
    return FakeTripTaskPort()


@pytest.fixture
def status(clock) -> FakeFlightStatus:
    return FakeFlightStatus(clock)


@pytest.fixture
def svc(tsettings, store, clock, docs, sender, taskport, status) -> TripService:
    return TripService(
        tsettings, store, clock, docs=docs, sender=sender, tasks=taskport, status=status
    )


def make_doc(
    user_id: str, doc_type: DocType, values: dict[str, str], *, confirmed: bool = True
) -> Document:
    return Document(
        user_id=user_id,
        doc_type=doc_type,
        status=DocStatus.CONFIRMED if confirmed else DocStatus.PENDING,
        sha256=hashlib.sha256(repr(sorted(values.items())).encode()).hexdigest(),
        fields={k: DocField(value=v, confidence=0.95, confirmed=True) for k, v in values.items()},
    )


# invented fixtures: fake airline and hotel, no real booking, no real number
FLIGHT_OUT = {
    "airline": "Exampleair",
    "flight_no": "EX 101",
    "from_iata": "DEL",
    "to_iata": "GOI",
    "dep_local": "2026-11-14T06:30",
    "arr_local": "2026-11-14T09:00",
    "pnr": "ZZ1234",
}
FLIGHT_BACK = {
    "airline": "Exampleair",
    "flight_no": "EX 102",
    "from_iata": "GOI",
    "to_iata": "DEL",
    "dep_local": "2026-11-17T18:00",
    "arr_local": "2026-11-17T20:30",
    "pnr": "ZZ1234",
}
HOTEL = {
    "property_name": "Hotel Example Palms",
    "address": "1 Example Road",
    "phone": "+91 80000 11111",
    "check_in_date": "2026-11-14",
    "check_in_time": "14:00",
    "check_out_date": "2026-11-17",
    "check_out_time": "11:00",
    "confirmation_no": "HX9",
}
HOTEL_NOPHONE = {k: v for k, v in HOTEL.items() if k != "phone"}
INTL_OUT = {
    "airline": "Exampleair",
    "flight_no": "EX 7",
    "from_iata": "DEL",
    "to_iata": "DXB",
    "dep_local": "2026-11-20T04:00",
    "arr_local": "2026-11-20T06:00",
    "pnr": "ZZ77",
}
