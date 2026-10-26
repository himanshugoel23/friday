# ruff: noqa: E501
"""Memory layer: alias write-back, episodes, the list, forgetting, ranking, isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from friday.core.clock import FakeClock
from friday.core.models import Fact, FactKind, Person, Place, User, UserStatus
from friday.memory import MemoryService, rank_facts
from friday.memory.chat import handle as chat_handle
from friday.memory.service import format_list

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
async def world(settings):
    from friday.core.container import Container
    from friday.db import Database

    clock = FakeClock(NOW)
    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    a = await c.repos.users.add(User(phone="+919800000301", status=UserStatus.ACTIVE))
    b = await c.repos.users.add(User(phone="+919800000302", status=UserStatus.ACTIVE))
    await c.repos.places.upsert(Place(owner_user_id=a.id, label="Shreya Salon"))
    await c.repos.people.upsert(Person(owner_user_id=a.id, name="Ramesh Sharma", relation="father",
                                       aliases=["papa"]))
    yield c, a.id, b.id, MemoryService(c.repos, clock)
    await c.aclose()


async def test_alias_needs_two_sightings_then_goes_live_and_can_be_undone(world):
    c, a, _b, svc = world
    assert await svc.note_misheard(a, "Shriya salon", "Shreya Salon") == "recorded"
    assert not (await c.repos.places.list_for_owner(a))[0].aliases
    assert await svc.note_misheard(a, "Shriya salon", "Shreya Salon") == "promoted"
    assert (await c.repos.places.list_for_owner(a))[0].aliases == ["shriya salon"]
    assert not [f for f in await c.repos.facts.list_for_user(a) if f.key.startswith("alias_seen:")]
    assert await svc.forget_alias(a, "Shriya salon")
    assert (await c.repos.places.list_for_owner(a))[0].aliases == []


async def test_one_confirmation_is_enough(world):
    _c, a, _b, svc = world
    assert await svc.note_misheard(a, "Shreeya salon", "Shreya Salon", confirmed=True) == "promoted"


async def test_alias_guards(world):
    c, a, _b, svc = world
    assert await svc.note_misheard(a, "Unknown Place", "Unknown Place 2") == "ignored"  # not saved
    assert await svc.note_misheard(a, "zzzz", "Shreya Salon") == "ignored"  # does not sound alike
    # poison: "papa" already belongs to Ramesh, so it can never be moved onto another entry
    assert await svc.note_misheard(a, "papa", "Shreya Salon", confirmed=True) == "ignored"
    assert await svc.note_misheard(a, "papa", "Ramesh Sharma", confirmed=True) == "ignored"
    assert await svc.note_misheard(a, "otp 482913", "Shreya Salon") == "ignored"  # digits/secret
    for i in range(10):
        await svc.note_misheard(a, f"shreya salonn{'x' * i}", "Shreya Salon", confirmed=True)
    assert len((await c.repos.places.list_for_owner(a))[0].aliases) <= 6


async def test_aliases_are_per_user(world):
    c, a, b, svc = world
    await svc.note_misheard(a, "Shriya salon", "Shreya Salon", confirmed=True)
    assert await c.repos.places.list_for_owner(b) == []
    assert await svc.remember_list(b) == []


async def test_episode_recorded_listed_expires_and_hides_secrets(world):
    c, a, _b, svc = world
    assert await svc.record_episode(a, "t1", "Haircut quote, otp 482913 test", "done", "Shreya Salon")
    eps = await svc.episodes(a)
    assert len(eps) == 1 and "482913" not in eps[0].value and "Shreya Salon" in eps[0].value
    assert await svc.purge_expired(a, days=365) == 0
    c.clock.advance(days=400)
    assert await svc.purge_expired(a, days=365) == 1
    assert await svc.episodes(a) == []


async def test_a_finished_main_task_leaves_one_episode_and_child_calls_do_not(world):
    from friday.core.events import EventBus, TaskStatusChanged
    from friday.core.models import ContactTarget, Task, TaskSpec, TaskStatus, TaskType
    from friday.memory.attach import attach_episodes

    c, a, _b, svc = world
    target = ContactTarget(kind="business", name="Shreya Salon", phone="+919999900001")
    main = Task(requester_user_id=a, type=TaskType.BOOKING, status=TaskStatus.COMPLETED,
                spec=TaskSpec(type=TaskType.BOOKING, goal="Haircut tomorrow 6pm"), target=target)
    child = Task(requester_user_id=a, type=TaskType.BOOKING, status=TaskStatus.COMPLETED,
                 spec=TaskSpec(type=TaskType.BOOKING, goal="child call"), parent_task_id=main.id)
    tasks = {main.id: main, child.id: child}

    class Tasks:
        async def get(self, tid):
            return tasks.get(tid)

    class Repos:
        facts = c.repos.facts
        people, places, profiles = c.repos.people, c.repos.places, c.repos.profiles
        tasks = Tasks()

    bus = EventBus()
    attach_episodes(bus, Repos, c.clock)
    for t in (main, child):
        await bus.publish(TaskStatusChanged(task_id=t.id, user_id=a, old=TaskStatus.CREATED,
                                            new=TaskStatus.COMPLETED))
    (ep,) = await svc.episodes(a)
    assert "Haircut tomorrow 6pm" in ep.value and "Shreya Salon" in ep.value and "done" in ep.value


async def test_remember_list_shows_source_and_forget_removes_items(world):
    c, a, _b, svc = world
    await c.repos.facts.upsert(Fact(user_id=a.__str__(), kind=FactKind.PREFERENCE,
                                    key="usual_salon", value="Shreya Salon"))
    await svc.note_misheard(a, "Shriya salon", "Shreya Salon", confirmed=True)
    items = await svc.remember_list(a)
    kinds = {i.kind for i in items}
    assert {"person", "place", "fact", "alias"} <= kinds
    alias = next(i for i in items if i.kind == "alias" and "shriya" in i.text)
    assert alias.source == "inferred"
    assert await svc.forget(a, alias.id)
    fact = next(i for i in items if i.kind == "fact")
    assert await svc.forget(a, fact.id)
    assert not [i for i in await svc.remember_list(a)
                if i.kind == "fact" or (i.kind == "alias" and "shriya" in i.text)]
    text = format_list(items, "en")
    assert "you told me" in text and "delete everything" in text


async def test_cannot_forget_another_users_fact(world):
    c, a, b, svc = world
    f = await c.repos.facts.upsert(Fact(user_id=a, kind=FactKind.GENERAL, key="k", value="v"))
    assert not await svc.forget(b, f"fact:{f.id}")
    assert any(x.id == f.id for x in await c.repos.facts.list_for_user(a))


async def test_chat_commands(world):
    c, a, _b, svc = world
    await svc.note_misheard(a, "Shriya salon", "Shreya Salon", confirmed=True)
    out = await chat_handle(c.repos, c.clock, a, "What do u remember about me?", "en")
    assert out is None  # "u" is not matched: only the exact phrasings
    out = await chat_handle(c.repos, c.clock, a, "what do you remember about me", "en")
    assert "Shreya Salon" in out and "my guess" in out
    out = await chat_handle(c.repos, c.clock, a, "forget shriya salon", "en")
    assert out == "Okay, forgotten."
    assert await chat_handle(c.repos, c.clock, a, "forget dentist", "en") is None


def test_ranking_prefers_matching_recent_and_drops_internal_candidates():
    old = Fact(user_id="u", kind=FactKind.GENERAL, key="old_note", value="something old",
               updated_at=NOW - timedelta(days=700))
    match = Fact(user_id="u", kind=FactKind.PREFERENCE, key="usual_salon", value="Shreya Salon",
                 updated_at=NOW - timedelta(days=30))
    cand = Fact(user_id="u", kind=FactKind.PATTERN, key="alias_seen:shriya", value="Shreya|1")
    due = Fact(user_id="u", kind=FactKind.DATE, key="rent_due", value="5th", due_on=NOW.date())
    ranked = rank_facts([old, cand, due, match], "salon mein haircut", NOW, k=3)
    keys = [f.key for f, _s, _w in ranked]
    assert keys[0] == "usual_salon" and "alias_seen:shriya" not in keys and keys[1] == "rent_due"
    assert all(w for _f, _s, w in ranked)


def test_format_list_handles_items_without_a_date_and_mixed_sources():
    from friday.memory.service import MemoryItem

    items = [MemoryItem("profile:me", "profile", "Rahul, Pune", "said"),
             MemoryItem("fact:1", "episode", "Haircut | done", "done", NOW)]
    out = format_list(items, "hinglish")
    assert "Rahul, Pune (aapne bataya)" in out and "kaam hua" in out
    assert "yaad nahi" in format_list([], "hinglish")
