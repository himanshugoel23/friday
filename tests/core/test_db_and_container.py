from sqlalchemy import inspect, select

from friday.core.container import FACTORIES, ComponentNotAvailable, Container
from friday.core.models import TaskSpec, TaskType
from friday.db import Database
from friday.db.tables import ALL_TABLES, TaskRow, UserRow

EXPECTED = {
    "users",
    "profiles",
    "consents",
    "invites",
    "autonomy_settings",
    "people",
    "places",
    "businesses",
    "vendor_interactions",
    "account_identifiers",
    "facts",
    "messages",
    "tasks",
    "calls",
    "call_turns",
    "call_questions",
    "quotes",
    "hotel_bookings",
    "nudges",
    "nudge_feedback",
    "audit_log",
}


async def test_all_tables_created(db: Database):
    async with db.engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert names >= EXPECTED
    assert set(ALL_TABLES) >= EXPECTED


async def test_insert_and_read_back_with_utc(db: Database, clock):
    spec = TaskSpec(type=TaskType.BOOKING, goal="Haircut")
    async with db.session() as s:
        user = UserRow(phone="+919800000000", last_inbound_at=clock.now())
        s.add(user)
        await s.flush()
        s.add(
            TaskRow(
                requester_user_id=user.id,
                type="booking",
                spec=spec.model_dump(mode="json"),
                next_attempt_at=clock.now(),
            )
        )
    async with db.session() as s:
        row = (await s.execute(select(TaskRow))).scalar_one()
        assert TaskSpec.model_validate(row.spec) == spec
        assert row.next_attempt_at == clock.now()  # aware UTC round-trip
        u = (await s.execute(select(UserRow))).scalar_one()
        assert u.last_inbound_at.tzinfo is not None


async def test_container_resolves_paths_and_overrides(container: Container):
    assert container.factory_path("llm") == FACTORIES["llm"]["fake"]
    assert container.factory_path("telephony") == FACTORIES["telephony"]["simulator"]
    sentinel = object()
    container.override("brain", sentinel)
    assert container.brain is sentinel
    assert container.db is not None


def test_missing_component_raises_clear_error(settings):
    c = Container(settings)
    c_paths = {k: c.factory_path(k) for k in FACTORIES}
    assert all(":" in p for p in c_paths.values())
    if not c.is_available("task_engine"):
        try:
            c.get("task_engine")
        except ComponentNotAvailable as e:
            assert "friday.tasks.engine" in str(e)
        else:  # pragma: no cover
            raise AssertionError("expected ComponentNotAvailable")


def test_live_mode_refuses_to_start_without_keys(settings):
    live = settings.model_copy(update={"mode": "live"})
    c = Container(live)
    try:
        c.check_live_config()
    except RuntimeError as e:
        assert "ANTHROPIC_API_KEY" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_role_components_and_scale_wiring(settings):
    from friday.core.container import JOB_ROUTES, ROLE_COMPONENTS
    from friday.core.scale import MemoryJobQueue

    c = Container(settings.model_copy(update={"roles": ["voice"]}))
    comps = c.role_components()
    assert "call_runner" in comps and "proactive" not in comps
    assert set(JOB_ROUTES.values()) <= set(ROLE_COMPONENTS)
    assert isinstance(c.job_queue, MemoryJobQueue)
    assert c.get("outbox").queue is c.job_queue
    assert c.factory_path("number_pool").startswith("friday.tasks.number_pool")


def test_object_store_component_and_pool_settings(settings, monkeypatch, tmp_path):
    import friday.db.session as sess

    c = Container(settings.model_copy(update={"media_dir": str(tmp_path)}))
    assert c.factory_path("object_store") == FACTORIES["object_store"]["*"]
    assert c.is_available("object_store") and c.object_store is not None
    assert "object_store" in c.role_components(["voice"])
    assert "object_store" in c.role_components(["proactive"])

    seen: dict = {}

    class FakeDatabase:
        def __init__(self, url, **kw):
            seen.update(kw)

    monkeypatch.setattr(sess, "Database", FakeDatabase)
    pooled = Container(
        settings.model_copy(
            update={"db_pool_size": 3, "db_max_overflow": 4, "db_pool_timeout_s": 2.5}
        )
    )
    pooled.db  # noqa: B018
    assert seen["pool_size"] == 3 and seen["max_overflow"] == 4 and seen["pool_timeout_s"] == 2.5


def test_all_role_components_are_implemented(settings):
    c = Container(settings)
    assert c.missing_role_components(["api", "task", "voice", "proactive"]) == []
