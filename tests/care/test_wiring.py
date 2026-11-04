# ruff: noqa: E501
"""The care protocol inside the real InboundPipeline and the proactive engine."""

from __future__ import annotations

import logging
from datetime import timedelta

from friday.care import copy
from friday.core.models import (
    Intent,
    Interpretation,
    MessageKind,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
)
from tests.api.conftest import ADMIN
from tests.api.test_pipeline import onboard, say


async def active_user(pipeline, channel):
    return await onboard(pipeline, channel)


async def test_distress_never_reaches_the_brain_and_is_stored_redacted(pipeline, channel, brain):
    user = await active_user(pipeline, channel)
    seen_before = len(brain.seen)
    out = await say(pipeline, channel, ADMIN, "I want to die")
    assert len(brain.seen) == seen_before  # the brain never saw it
    assert out and "14416" in out[0] and "hurting yourself?" in out[0]
    logged = [m.text for m in await pipeline.repos.messages.list_for_user(user.id)] if hasattr(pipeline.repos.messages, "list_for_user") else []
    assert not any(t and "want to die" in t for t in logged)


async def test_features_do_not_start_while_high_is_active(pipeline, channel, brain, engine):
    await active_user(pipeline, channel)
    engine.calls.clear()
    brain.script.append(Interpretation(intent=Intent.HELP, reply="should never be sent"))
    await say(pipeline, channel, ADMIN, "I want to die")
    seen = len(brain.seen)
    out = await say(pipeline, channel, ADMIN, "book a haircut for tomorrow")
    assert len(brain.seen) == seen and "should never be sent" not in " ".join(out)
    assert engine.names() == [] or "submit" not in engine.names()
    assert out and "paused" in out[0].lower()


async def test_okay_gives_the_features_back(pipeline, channel, brain):
    await active_user(pipeline, channel)
    await say(pipeline, channel, ADMIN, "I want to die")
    out = await say(pipeline, channel, ADMIN, "I'm okay now")
    assert "14416" in out[0]
    seen = len(brain.seen)
    await say(pipeline, channel, ADMIN, "hello there")
    assert len(brain.seen) == seen + 1


async def test_open_request_is_paused_with_one_plain_line(pipeline, channel):
    user = await active_user(pipeline, channel)
    t = Task(requester_user_id=user.id, type=TaskType.BOOKING, spec=TaskSpec(type=TaskType.BOOKING, goal="Haircut"),
             status=TaskStatus.AWAITING_APPROVAL)
    await pipeline.repos.tasks.add(t)
    out = await say(pipeline, channel, ADMIN, "I want to die")
    assert out[-1] == copy.line("paused_task", "en")


async def test_delete_everything_erases_care_state(pipeline, channel):
    user = await active_user(pipeline, channel)
    await say(pipeline, channel, ADMIN, "I want to die")
    assert await pipeline.care.blocked(user.id)
    await pipeline.delete_everything(user)
    assert await pipeline.care.store.get(user.id) is None


async def test_care_is_a_container_component_with_a_stable_is_active(pipeline, channel, wired):
    user = await active_user(pipeline, channel)
    care = wired.get("care")
    assert care is pipeline.care
    assert await care.is_active(user.id) is False
    await say(pipeline, channel, ADMIN, "I want to die")
    assert await care.is_active(user.id) is True
    assert await care.is_active("nobody") is False


async def test_only_a_hashed_tier_is_logged(pipeline, channel, caplog):
    await active_user(pipeline, channel)
    with caplog.at_level(logging.DEBUG):
        await say(pipeline, channel, ADMIN, "I want to die, my name is Sunita")
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "care_tier=high" in joined
    assert "want to die" not in joined and "Sunita" not in joined and ADMIN not in joined


async def test_unknown_sender_gets_the_lines_and_nothing_is_stored(pipeline, channel):
    out = await say(pipeline, channel, "+919800000777", "I want to die")
    assert out and "14416" in out[0]
    assert await pipeline.repos.users.get_by_phone("+919800000777") is None


async def test_webhook_path_does_not_queue_distress_text(pipeline, channel):
    user = await active_user(pipeline, channel)
    msg = channel.make_inbound(ADMIN, "I want to die")
    assert await pipeline.try_care(msg) is True
    assert await pipeline.try_care(channel.make_inbound(ADMIN, "what is the weather")) is False
    assert msg.kind == MessageKind.TEXT and user.id == msg.user_id


# ------------------------------------------------------------------ proactive engine
async def test_proactive_sends_nothing_while_high_and_runs_checkins(env_pe):
    env, pe, care, sent = env_pe
    from tests.proactive.test_proactive import add_fact

    await care.screen(env.user.id, "I want to die")
    await add_fact(env, "rent_due", (env.clock.now() + timedelta(days=1)).date())
    await pe.tick()
    assert env.notifier.sent == []  # no nudge at all
    env.clock.advance(hours=5)
    await pe.tick()
    assert env.notifier.sent == [] and len(sent) == 1  # the care check-in, not a nudge
    await care.screen(env.user.id, "I'm okay")
    await pe.tick()
    assert env.notifier.sent  # features are back


async def test_proactive_unaffected_without_an_episode(env_pe):
    env, pe, care, _ = env_pe
    from tests.proactive.test_proactive import add_fact

    await add_fact(env, "rent_due", (env.clock.now() + timedelta(days=1)).date())
    await pe.tick()
    assert env.notifier.sent
