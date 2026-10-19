"""The whole flow again with the database repositories instead of the in-memory stores."""

from __future__ import annotations

from friday.calls.models import CallOutcome, CallStatus, OutcomeStatus
from friday.calls.numbers import NumberHasher
from friday.core.models import User, UserStatus
from friday.db.repositories.consumer_calls import (
    CallDncRepo,
    ConsumerCallsRepo,
    ConsumerContactsRepo,
)
from friday.db.repositories.users import UserRepo
from tests.calls.conftest import MUMMY, PLUMBER, build_world


async def _world(db):
    from friday.core.clock import FakeClock

    user = await UserRepo(db, FakeClock()).add(
        User(phone="+919800000021", status=UserStatus.ACTIVE)
    )
    return build_world(
        store=ConsumerCallsRepo(db), contact_store=ConsumerContactsRepo(db),
        dnc_store=CallDncRepo(db), hasher=NumberHasher(), user=user,
    )  # fmt: skip


def _approve(reply) -> str:
    return next(b.id for b in reply.buttons if b.title == "Approve")


async def test_flow_with_database_stores(db):
    w = await _world(db)
    await w.contacts.add(w.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True)
    w.engine.on("Mummy", CallOutcome(request_id="x", status=OutcomeStatus.NO_ANSWER))
    reply = await w.intake.handle(
        w.user, "mummy ko phone karke bata do ki main late hoon", message_id="wamid.9",
        user_display_name="Rahul",
    )  # fmt: skip
    res = await w.orch.handle_button(w.user.id, _approve(reply))
    assert res.status == CallStatus.SCHEDULED
    await w.orch.run_due()
    req = await w.store.get_request(reply.request_id)
    assert req.status == CallStatus.SCHEDULED and req.attempts == 1
    # idempotent on re-delivery, also across the database
    again = await w.intake.handle(
        w.user, "mummy ko phone karke bata do ki main late hoon", message_id="wamid.9"
    )
    assert again.text == ""
    assert len(await w.store.list_for_user(w.user.id)) == 1
    # counters survive in the database
    assert await w.store.calls_between(w.user.id, w.at(0), w.at(23, 59)) == 1
    assert await w.store.number_calls_since(w.hasher.hash(MUMMY), w.at(0)) == 1


async def test_opt_out_is_global_in_the_database(db):
    w = await _world(db)
    await w.contacts.add(w.user.id, "Plumber", PLUMBER, relationship="plumber", confirmed=True)
    w.engine.on("Plumber", CallOutcome(request_id="x", status=OutcomeStatus.OPTED_OUT))
    reply = await w.intake.handle(
        w.user, "plumber ko call karo kal aane ke liye Rs 500", message_id="p1"
    )
    await w.orch.handle_button(w.user.id, _approve(reply))
    await w.orch.run_due()
    assert await w.dnc.is_blocked(PLUMBER)
    assert await w.dnc_store.count() == 1
    assert (await w.store.get_request(reply.request_id)).status == CallStatus.CANCELLED


async def test_group_with_database_stores(db):
    w = await _world(db)
    for n, num in (("Raj", "+919000000005"), ("Amit", "+919000000006")):
        await w.contacts.add(w.user.id, n, num, relationship="friend", confirmed=True)
    reply = await w.intake.handle(
        w.user, "sabko party ke liye call karo: Raj, Amit", message_id="g1"
    )
    await w.orch.handle_button(w.user.id, _approve(reply))
    await w.orch.run_due()
    parent = await w.store.get_request(reply.request_id)
    assert parent.status == CallStatus.COMPLETED
    assert len([t for t in w.notifier.texts() if "Group ka jawab" in t]) == 1
