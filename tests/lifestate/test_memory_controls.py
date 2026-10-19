"""'what do you remember', 'forget X', edit, export, delete everything."""

from __future__ import annotations

from datetime import datetime

import pytest

from friday.core.clock import IST, FakeClock, to_ist
from friday.lifestate.capture import capture_message
from friday.lifestate.memory import MemoryControls

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=IST)


@pytest.fixture
def mc(world):
    return MemoryControls(world.store, FakeClock(NOW))


async def seed(world):
    for msg in (
        "kal 2 baje interview hai",
        "parso shaam 6 baje dentist",
        "bijli ka bill 25 ko",
        "mummy ki dawai 8 baje roz",
    ):
        r = await capture_message(world.store, world.u1, msg, NOW)
        assert r.status == "captured", msg


async def test_remember_summary_lists_things_and_muted_topics(world, mc):
    assert "kuch yaad nahi" in (await mc.handle(world.u1, "tumhe kya yaad hai")).text
    await seed(world)
    await world.store.set_topic(world.u1, "after_event", muted=True)
    r = await mc.handle(world.u1, "tumhe mere baare mein kya kya yaad hai?")
    assert r.handled and r.action == "remember"
    for word in ("interview", "dentist", "mummy ki dawai", "Band kiye hue"):
        assert word in r.text
    r2 = await mc.handle(world.u2, "what do you remember")
    assert "dentist" not in r2.text


async def test_forget_one_by_name(world, mc):
    await seed(world)
    r = await mc.handle(world.u1, "bhool jao dentist")
    assert r.action == "forget" and "1 cheez" in r.text
    kinds = [e.title for e in await world.store.list_events(world.u1)]
    assert not any("dentist" in k for k in kinds)
    r = await mc.handle(world.u1, "mummy ki dawai hata do")
    assert "1 cheez" in r.text
    assert await world.store.list_commitments(world.u1) == []


async def test_forget_asks_when_several_match_and_deletes_nothing(world, mc):
    await capture_message(world.store, world.u1, "kal 2 baje meeting hai", NOW)
    await capture_message(world.store, world.u1, "parso 4 baje meeting hai", NOW)
    r = await mc.handle(world.u1, "forget meeting")
    assert "Kaun si" in r.text
    assert len(await world.store.list_events(world.u1)) == 2
    r = await mc.handle(world.u1, "bhool jao sab meeting")
    assert "2 cheezein" in r.text
    assert await world.store.list_events(world.u1) == []


async def test_forget_unknown_and_other_users_items(world, mc):
    await seed(world)
    assert "nahi mili" in (await mc.handle(world.u2, "bhool jao dentist")).text
    assert len(await world.store.list_events(world.u1)) == 3  # untouched


async def test_delete_everything_needs_the_exact_phrase(world, mc):
    await seed(world)
    r = await mc.handle(world.u1, "sab kuch delete karo")
    assert r.action == "delete_prompt" and "haan, sab mita do" in r.text
    assert len(await world.store.list_events(world.u1)) == 3  # nothing happened yet
    # a casual "haan" or a similar sentence does nothing
    assert (await mc.handle(world.u1, "haan")).handled is False
    assert len(await world.store.list_events(world.u1)) == 3
    r = await mc.handle(world.u1, "haan, sab mita do")
    assert r.action == "delete_all" and r.counts["life_events"] == 3
    assert await world.store.list_events(world.u1) == []
    assert await world.store.list_commitments(world.u1) == []


async def test_delete_everything_affects_only_the_caller(world, mc):
    await seed(world)
    await capture_message(world.store, world.u2, "kal 2 baje interview hai", NOW)
    await mc.handle(world.u1, "haan, sab mita do")
    assert len(await world.store.list_events(world.u2)) == 1


async def test_export_returns_everything(world, mc):
    await seed(world)
    r = await mc.handle(world.u1, "mera data export karo")
    assert (
        r.action == "export" and len(r.export["events"]) == 3 and len(r.export["commitments"]) == 1
    )


async def test_edit_moves_the_event(world, mc):
    await seed(world)
    r = await mc.handle(world.u1, "interview ko 4 baje kar do")
    assert r.action == "edit" and "4 baje" in r.text
    iv = next(e for e in await world.store.list_events(world.u1) if "nterview" in e.title)
    assert to_ist(iv.start).hour == 16 and to_ist(iv.start).day == 20
    assert (iv.end - iv.start).total_seconds() == 3600
    r = await mc.handle(world.u1, "dentist ko parso se guruvar kar do")
    assert r.action == "edit"
    assert "samajh nahi" in (await mc.handle(world.u1, "kuch nahi ko 4 baje kar do")).text


async def test_unrelated_messages_are_not_handled(world, mc):
    for text in ("hello", "kal 2 baje interview hai", "mujhe plumber chahiye", ""):
        assert (await mc.handle(world.u1, text)).handled is False
