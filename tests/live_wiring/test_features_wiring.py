# ruff: noqa: E501
"""Trips, refunds and family Drive are reachable from the live message path (api/features.py):
chat text and button taps, a confirmed document, a finished task, the scheduler loop.
Real pipeline + real task engine over fakes. No network, no calls."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from friday.api.features import LiveFeatures, _EnginePort
from friday.chatbot_media.wiring import build_docs
from friday.core.clock import IST
from friday.core.events import TaskStatusChanged
from friday.core.models import (
    Channel,
    InboundMessage,
    Intent,
    Interpretation,
    MessageKind,
    TaskStatus,
)
from friday.docunderstand.ports import FakeVision
from friday.refunds.ports import LinesPending
from tests.docunderstand import samples as S

FLIGHT_CMD = "add flight EX101 DEL BOM 2026-01-06 18:30 arr 2026-01-06 20:40"


async def tap_id(w, button_id: str):  # noqa: ANN001, ANN201
    before = len(w.channel.messages_to(w.phone))
    await w.runtime.handle(
        InboundMessage(channel=Channel.SIMULATOR, from_phone=w.phone, kind=MessageKind.BUTTON_REPLY,
                       button_id=button_id, text=button_id)
    )  # fmt: skip
    return w.channel.messages_to(w.phone)[before:]


def texts(msgs) -> str:  # noqa: ANN001
    return "\n".join(m.text or "" for m in msgs)


async def test_all_off_builds_nothing_and_commands_fall_through(media_world):
    w = await media_world()
    assert w.runtime.pipeline.features is None
    out = await w.say(FLIGHT_CMD)
    assert "Trip bana di" not in texts(out)


# ------------------------------------------------------------------ trips
async def test_trip_from_typed_flight_plan_button_and_scheduled_nudge(media_world):
    w = await media_world(trips_enabled=True)
    assert isinstance(w.runtime.pipeline.features, LiveFeatures)
    out = await w.say(FLIGHT_CMD)
    assert "Trip bana di" in texts(out)
    plan = await w.say("meri trip")
    assert "EX101" in texts(plan) or "DEL" in texts(plan)
    (trip,) = await w.c.repos.trips.list_trips(w.user.id)
    # the scheduler: leave-by heads-up goes out through the live notifier, once
    w.set_time(datetime(2026, 1, 6, 15, 10, tzinfo=IST))
    before = len(w.channel.messages_to(w.phone))
    await w.runtime.pipeline.features.tick()
    sent = w.channel.messages_to(w.phone)[before:]
    assert any("nikalna hai" in w.channel.render(m) for m in sent)  # the leave-by heads-up
    await w.runtime.pipeline.features.tick()
    assert len(w.channel.messages_to(w.phone)) == before + len(sent)  # de-duplicated
    assert texts(await tap_id(w, f"trip:{trip.id}:plan"))  # a trip button of this user works


async def test_trip_commands_ignore_other_chat(media_world):
    w = await media_world(trips_enabled=True)
    out = await w.say("kya haal hai")
    assert w.brain.seen[-1] == "kya haal hai"
    assert "Trip" not in texts(out)


async def test_confirmed_flight_document_builds_the_trip(media_world):
    w = await media_world(trips_enabled=True, docs_enabled=True)
    w.runtime.pipeline._docs_in = build_docs(w.c, w.runtime.pipeline, vision=FakeVision())  # noqa: SLF001
    media = w.channel.put_media(S.sample(S.FLIGHT), "image/jpeg", "file")
    await w.runtime.handle(
        InboundMessage(channel=Channel.SIMULATOR, from_phone=w.phone, kind=MessageKind.IMAGE,
                       media_url=media, media_mime="image/jpeg")
    )  # fmt: skip
    done = await w.tap("sahi hai")
    assert "Trip bana di" in texts(done)
    assert len(await w.c.repos.trips.list_trips(w.user.id)) == 1


async def test_finished_task_links_back_to_the_trip(media_world):
    from friday.trips.models import TaskKind, TaskState, TripTask

    w = await media_world(trips_enabled=True, refunds_enabled=True)
    feats = w.runtime.pipeline.features
    feats.subscribe()
    await w.say(FLIGHT_CMD)
    (trip,) = await w.c.repos.trips.list_trips(w.user.id)
    t = TripTask(user_id=w.user.id, trip_id=trip.id, kind=TaskKind.HOTEL_CALL, state=TaskState.RUNNING,
                 due_at=w.clock.now(), expires_at=w.clock.now(), task_id="eng-1", dedupe_key="k1")  # fmt: skip
    await w.c.repos.trips.save_task(t)
    await w.c.bus.publish(TaskStatusChanged(task_id="eng-1", user_id=w.user.id, old=TaskStatus.CALLING, new=TaskStatus.COMPLETED))
    assert (await w.c.repos.trips.get_task(w.user.id, t.id)).state == TaskState.DONE
    feats.unsubscribe()


# ------------------------------------------------------------------ refunds
async def test_refund_text_buttons_and_reminder_tick(media_world):
    w = await media_world(refunds_enabled=True)
    out = await w.say("Exampleair ka refund nahi aaya 4500")
    assert "Exampleair" in texts(out) and "4,500" in texts(out)
    (case,) = await w.c.repos.refunds.list_cases(w.user.id)
    assert case.vendor_name == "Exampleair"
    listing = await w.say("mera refund kahan hai")
    assert "Exampleair" in texts(listing)
    assert texts(await tap_id(w, f"refund:{case.id}:yes"))  # a button of this user's case works
    assert texts(await tap_id(w, "refund:not-a-case:yes"))  # answered, nothing created
    assert len(await w.c.repos.refunds.list_cases(w.user.id)) == 1
    got = await w.say("Exampleair refund aa gaya 4500")
    assert "Exampleair" in texts(got)
    await w.runtime.pipeline.features.tick()  # the scheduler entry does not raise


async def test_refund_followup_call_lines_stay_pending():
    class Engine:
        async def create_task(self, *a, **k):  # noqa: ANN002, ANN003
            raise AssertionError("must not be reached while the lines are PENDING")

    class P:
        def engine(self):  # noqa: ANN201
            return Engine()

    with pytest.raises(LinesPending):
        await _EnginePort(P(), lines_gate=True).create_task("u", object())


# ------------------------------------------------------------------ drive, status reply, loop
async def test_drive_commands_answer_without_any_network(media_world, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    w = await media_world(family_drive_enabled=True)
    out = await w.say("drive status")
    assert "Drive" in texts(out)
    out = await w.say("mera passport kahan hai")
    assert texts(out)


async def test_parity_status_reply_after_a_slow_turn(media_world, monkeypatch):
    from friday.chatbot.parity import turns

    monkeypatch.setitem(turns.run_with_status.__kwdefaults__, "after_s", 0.05)
    w = await media_world(parity_status=True)

    async def slow(ctx, msg):  # noqa: ANN001, ANN202
        await asyncio.sleep(0.3)
        return Interpretation(intent=Intent.HELP, reply="done thinking")

    monkeypatch.setattr(w.brain, "interpret", slow)
    out = await w.say("plan my weekend")
    assert len(out) == 2 and out[-1].text == "done thinking"  # status first, then the answer


async def test_runtime_starts_the_features_loop_and_it_ticks(media_world, monkeypatch):
    w = await media_world(trips_enabled=True, refunds_enabled=True)
    calls: list[int] = []

    async def tick() -> None:
        calls.append(1)

    monkeypatch.setattr(w.runtime.pipeline.features, "tick", tick)
    task = asyncio.create_task(w.runtime.features_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert calls
    w.c.settings.roles = ["task"]
    await w.runtime.start(background=True)
    try:
        assert "friday-features" in {t.get_name() for t in w.runtime._tasks}  # noqa: SLF001
    finally:
        await w.runtime.stop()
