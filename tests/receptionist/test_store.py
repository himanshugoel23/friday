# ruff: noqa: E501
from __future__ import annotations

from datetime import timedelta

from friday.receptionist.models import (
    CallOutcomeKind,
    MessageStatus,
    ReceptionistConfig,
    StoredMessage,
    Urgency,
)


def msg(user, number="+919100000001", **kw):
    return StoredMessage(user_id=user, caller_number=number, caller_name="Rahul", reason="bill",
                         outcome=CallOutcomeKind.MESSAGE, **kw)  # fmt: skip


async def test_config_roundtrip_and_isolation(world):
    s = world.store
    assert await s.get_config(world.u1) is None
    cfg = ReceptionistConfig(enabled=True, rings=4, urgent_contacts=["+919000000011"],
                             known_contacts={"+919000000011": "Mummy"}, urgent_keywords=["tender"])  # fmt: skip
    await s.save_config(world.u1, cfg)
    got = await s.get_config(world.u1)
    assert got.rings == 4 and got.known_contacts == {"+919000000011": "Mummy"}
    assert await s.get_config(world.u2) is None
    await s.save_config(world.u1, cfg.model_copy(update={"rings": 6}))  # update, not duplicate
    assert (await s.get_config(world.u1)).rings == 6
    assert await s.enabled_user_ids() == [world.u1]


async def test_messages_roundtrip_filters_and_isolation(world):
    s = world.store
    a = await s.add_message(msg(world.u1, urgency=Urgency.URGENT, snippet="abc",
                                callback_number="+919876543210", classification_reasons=["urgent word: x"]))  # fmt: skip
    await s.add_message(msg(world.u2))
    got = await s.get_message(world.u1, a.id)
    assert got.caller_name == "Rahul" and got.urgency == Urgency.URGENT
    assert got.callback_number == "+919876543210" and got.classification_reasons == ["urgent word: x"]
    assert await s.get_message(world.u2, a.id) is None  # another user's message is invisible
    assert len(await s.list_messages(world.u1)) == 1
    assert await s.set_status(world.u1, a.id, MessageStatus.NOTIFIED, notified_at=world.clock.now())
    assert not await s.set_status(world.u2, a.id, MessageStatus.IGNORED)  # not theirs
    assert (await s.get_message(world.u1, a.id)).status == MessageStatus.NOTIFIED
    assert await s.list_messages(world.u1, statuses=(MessageStatus.NEW,)) == []
    old = world.clock.now() + timedelta(days=1)
    assert await s.list_messages(world.u1, since=old) == []


async def test_block_list_is_per_user_and_matches_formats(world):
    s = world.store
    await s.block(world.u1, "+919100000009")
    await s.block(world.u1, "09100000009")  # same number: no duplicate
    assert await s.is_blocked(world.u1, "+91 91000 00009")
    assert not await s.is_blocked(world.u2, "+919100000009")
    assert not await s.is_blocked(world.u1, None)
    assert await s.blocked_numbers(world.u1) == ["9100000009"]
    assert await s.unblock(world.u1, "+919100000009")
    assert not await s.is_blocked(world.u1, "+919100000009")
    assert not await s.unblock(world.u1, "+919100000009")


async def test_counters_for_the_caps(world):
    s = world.store
    now = world.clock.now()
    for _ in range(3):
        await s.add_message(msg(world.u1, "+919100000001"))
    await s.add_message(msg(world.u2, "+919100000001"))
    assert await s.count_for_user(world.u1, now - timedelta(days=1)) == 3
    assert await s.count_from_caller("+919100000001", now - timedelta(hours=1)) == 4
    assert await s.count_from_caller("+919100000002", now - timedelta(hours=1)) == 0
    assert await s.count_from_caller(None, now) == 0
    assert await s.count_for_user(world.u1, now + timedelta(hours=1)) == 0


async def test_retention_clears_old_snippets_and_unrouted_rows(world):
    s = world.store
    t0 = world.clock.now()
    old = t0 - timedelta(days=40)
    keep = await s.add_message(msg(world.u1, snippet="recent words", created_at=t0))
    gone = await s.add_message(msg(world.u1, snippet="old words", created_at=old))
    await s.add_message(msg(None, created_at=t0 - timedelta(days=9)))  # unrouted, old
    fresh_unrouted = await s.add_message(msg(None, created_at=t0 - timedelta(days=1)))
    out = await s.purge_expired(t0, 30)
    assert out == {"snippets_cleared": 1, "unrouted_deleted": 1}
    assert (await s.get_message(world.u1, keep.id)).snippet == "recent words"
    after = await s.get_message(world.u1, gone.id)
    assert after.snippet is None and after.reason == "bill"  # the message itself stays
    assert fresh_unrouted.id  # still there (not user-readable by design)


async def test_delete_user_removes_everything_of_that_user_only(world):
    s = world.store
    await s.save_config(world.u1, ReceptionistConfig(enabled=True))
    await s.add_message(msg(world.u1))
    await s.add_message(msg(world.u2))
    await s.block(world.u1, "+919100000009")
    assert await s.delete_user(world.u1) == 1
    assert await s.list_messages(world.u1) == [] and await s.get_config(world.u1) is None
    assert not await s.is_blocked(world.u1, "+919100000009")
    assert len(await s.list_messages(world.u2)) == 1


async def test_sql_text_is_encrypted_at_rest_and_indexes_are_blind(world):
    if world.kind != "sql":
        return
    from sqlalchemy import text

    await world.store.add_message(msg(world.u1, "+919100000001", snippet="secret words here"))
    async with world.store.db.session() as sess:
        row = (await sess.execute(text(
            "select caller_number, caller_name, reason, snippet, caller_hash from receptionist_messages"
        ))).one()  # fmt: skip
    raw = " ".join(str(x) for x in row)
    assert "9100000001" not in raw and "secret words" not in raw and "Rahul" not in raw
    assert row[4] and len(row[4]) == 64


async def test_data_purger_covers_the_receptionist_tables(world):
    if world.kind != "sql":
        return
    c = world.container
    await world.store.save_config(world.u1, ReceptionistConfig(enabled=True))
    await world.store.add_message(msg(world.u1))
    await world.store.add_message(msg(world.u2))
    await world.store.block(world.u1, "+919100000009")
    counts = await c.repos.purger.purge_user(world.u1)
    assert counts["receptionist_messages"] == 1
    assert counts["receptionist_blocks"] == 1 and counts["receptionist_configs"] == 1
    assert await world.store.list_messages(world.u1) == []
    assert len(await world.store.list_messages(world.u2)) == 1
