# ruff: noqa: E501
"""Migration 0017, schema/RLS files, encryption at rest, retention, DataPurger, perks table, doctor."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from friday.core.clock import IST
from friday.core.config import Settings
from friday.db import migrate
from friday.db.retention import expire_trips
from friday.docunderstand.models import DocType
from friday.trips import copy
from friday.trips.perks import CardPerk, PerkKind, load_example_perks
from friday.trips.service import TripService
from tests.trips.conftest import FLIGHT_OUT, HOTEL, make_doc

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"trips", "trip_legs", "trip_tasks", "flight_watch", "trip_nudges", "card_perks"}


def test_migration_0017_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0017_trips"
    assert "0016_family_drive" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert set(insp.get_table_names()) >= TABLES
    cols = set()
    for t in TABLES:
        cols |= {c["name"] for c in insp.get_columns(t)}
    assert {"user_id", "title", "dedupe_hmac", "next_check_at", "visits_per_period"} <= cols
    assert not {
        c for c in cols if c in ("blob", "file", "token", "commission", "revenue", "referral")
    }
    migrate.downgrade(url)
    assert not TABLES & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_migration_matches_the_models(tmp_path):
    """Alembic and the SQLAlchemy models agree on every column of the new tables."""
    import friday.db.tables  # noqa: F401
    from friday.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    for t in TABLES:
        model_cols = {c.name for c in Base.metadata.tables[t].columns}
        assert {c["name"] for c in insp.get_columns(t)} == model_cols, t
        idx = {i["name"] for i in insp.get_indexes(t)}
        assert {i.name for i in Base.metadata.tables[t].indexes} <= idx, t
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in TABLES:
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0017_trips'" in schema


def test_switch_is_off_and_doctor_reports_it():
    from friday.ops import doctor

    s = Settings(_env_file=None)
    assert s.trips_enabled is False
    msgs = [c.message for c in doctor.check_switches(s).checks]
    assert "FRIDAY_TRIPS_ENABLED=off" in msgs
    on = doctor.check_switches(
        s.model_copy(update={"trips_enabled": True, "trip_flight_watch_enabled": True})
    )
    warn = [c for c in on.checks if c.status == doctor.WARN and "TRIP" in c.message]
    assert any("PENDING" in c.message for c in warn)
    assert any("no flight-status provider" in c.message for c in warn)


def test_all_wording_is_pending_and_the_repo_has_no_real_offers_or_personal_data():
    assert copy.PENDING_FOUNDER_APPROVAL and copy.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert all("hinglish" in v and "en" in v for v in copy.TEXTS.values())
    rows = load_example_perks()
    assert rows and all(r.verified_by == "EXAMPLE_NOT_REAL" for r in rows)
    csv = (ROOT / "friday" / "trips" / "data" / "example_perks.csv").read_text()
    assert "example.invalid" in csv and "http" in csv
    assert csv.count("https://") == csv.count("https://example.invalid/")  # no real bank link


async def _fill(svc, docs, uid):
    await docs.save(make_doc(uid, DocType.FLIGHT, FLIGHT_OUT))
    await docs.save(make_doc(uid, DocType.HOTEL, HOTEL))
    await svc.create_from_documents(uid)


async def test_personal_values_are_encrypted_at_rest(tsettings, repos, clock, docs, sender, alice):
    svc = TripService(tsettings, repos.trips, clock, docs=docs, sender=sender)
    await _fill(svc, docs, alice.id)
    trip = (await repos.trips.list_trips(alice.id))[0]
    await svc.set_pickup_address(alice.id, trip.id, "12 Example Lane Secretville")
    clock.set(datetime(2026, 11, 13, 10, 5, tzinfo=IST))
    await svc.run_user(alice.id)
    chunks: list[str] = []
    async with repos.db.session() as s:
        for t in ("trips", "trip_legs", "trip_tasks", "trip_nudges", "flight_watch"):
            for row in (await s.execute(text(f"select * from {t}"))).all():  # noqa: S608
                chunks += [str(c) for c in row]
    raw = " ".join(chunks)
    for secret in (
        "ZZ1234",
        "HX9",
        "Hotel Example Palms",
        "80000 11111",
        "8000011111",
        "Secretville",
        "1 Example Road",
        "Exampleair",
    ):
        assert secret not in raw, secret
    legs = await repos.trips.list_legs(alice.id, trip.id)
    assert {x.ref for x in legs} == {"ZZ1234", "HX9"}  # but it decrypts for the owner
    assert (await repos.trips.get_trip(alice.id, trip.id)).pickup_address.endswith("Secretville")


async def test_delete_everything_covers_the_trip_tables(
    tsettings, repos, clock, docs, sender, alice, bob
):
    svc = TripService(tsettings, repos.trips, clock, docs=docs, sender=sender)
    await _fill(svc, docs, alice.id)
    await _fill(svc, docs, bob.id)
    clock.set(datetime(2026, 11, 13, 10, 5, tzinfo=IST))
    await svc.run_user(alice.id)
    await svc.run_user(bob.id)
    counts = await repos.purger.purge_user(alice.id)
    assert counts["trips"] == 1 and counts["trip_legs"] == 2 and counts["trip_tasks"] >= 5
    assert counts["trip_nudges"] >= 1
    assert await repos.trips.list_trips(alice.id) == []
    assert len(await repos.trips.list_trips(bob.id)) == 1  # the other user is untouched
    assert await repos.trips.users_with_active_trips() == [bob.id]


async def test_retention_deletes_finished_trips_only(
    tsettings, repos, clock, docs, sender, alice, tmp_path
):
    svc = TripService(tsettings, repos.trips, clock, docs=docs, sender=sender)
    await _fill(svc, docs, alice.id)  # trip ends 17 Nov
    assert (await expire_trips(repos, datetime(2026, 12, 10, tzinfo=IST)))["trips"] == 0
    assert len(await repos.trips.list_trips(alice.id)) == 1
    assert (await expire_trips(repos, datetime(2026, 12, 20, tzinfo=IST)))["trips"] == 1
    assert await repos.trips.list_trips(alice.id) == []
    assert await repos.trips.list_legs(alice.id, "x") == []


async def test_perks_repo_serves_only_verified_rows(repos):
    good = CardPerk(
        bank="Fictional Bank",
        card_name="Fictional Voyager",
        perk=PerkKind.INTL_LOUNGE,
        source_url="https://bank.test/v",
        checked_on=date(2026, 11, 1),
        verified_by="A. Reviewer",
        status="served",
    )
    draft = good.model_copy(update={"perk": PerkKind.GUEST_ACCESS, "status": "draft"})
    bot = good.model_copy(update={"perk": PerkKind.DOMESTIC_LOUNGE, "verified_by": "claude"})
    for p in (good, draft, bot, *load_example_perks()):
        await repos.card_perks.upsert(p)
    assert await repos.card_perks.upsert(good) is False  # same card+perk: updated, not duplicated
    served = await repos.card_perks.served_perks(date(2026, 11, 10))
    assert [(p.card_key, p.perk) for p in served] == [
        ("fictional-bank/fictional-voyager", PerkKind.INTL_LOUNGE)
    ]
    assert len(await repos.card_perks.all()) == 3 + len(load_example_perks())
