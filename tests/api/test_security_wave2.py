"""SECURITY-23 (progressive lockout, step-up, freeze), -34 (bounded state), -16 (STOP
suppression), -30 (pepper separation), -33 via the pipeline."""

from __future__ import annotations

from datetime import timedelta

from friday.api.inbound import PIN_LOCKED, PIN_NEEDED
from friday.api.security import PinCheck, PinHasher, PinService
from friday.api.state import PendingAction, UserState
from friday.core.models import (
    ConsentKind,
    Delegation,
    Intent,
    Interpretation,
    MessageKind,
    Person,
    PersonConsent,
    TaskSpec,
    TaskType,
)
from friday.core.scale import MemoryCache
from tests.api.conftest import ADMIN
from tests.api.test_pipeline import PIN, onboard, say


async def test_progressive_lockout_30min_24h_then_support(wired, clock):
    repos = wired.repos
    from friday.core.models import User, UserStatus

    user = await repos.users.add(User(phone="+919800000444", status=UserStatus.ACTIVE))
    svc = PinService(PinHasher("pep", fast=True), repos.users, clock, 3, repos.pin_locks)
    await svc.set_pin(user, "4826")

    async def burn() -> PinCheck:
        res = None
        for _ in range(3):
            res = await svc.verify(user, "0000")
        return res.status

    assert await burn() == PinCheck.LOCKED
    assert (await svc.verify(user, "4826")).status == PinCheck.LOCKED
    clock.advance(minutes=31)  # round 2 after 30 min
    assert await burn() == PinCheck.LOCKED
    clock.advance(minutes=31)
    assert (await svc.verify(user, "4826")).status == PinCheck.LOCKED  # now 24 h
    clock.advance(hours=24)
    assert await burn() == PinCheck.LOCKED  # round 3 -> support only
    clock.advance(days=30)
    assert (await svc.verify(user, "4826")).status == PinCheck.LOCKED
    assert (await repos.pin_locks.get(user.id)).support_required
    await repos.pin_locks.clear(user.id)  # support-verified unlock
    assert (await svc.verify(user, "4826")).status == PinCheck.OK


async def test_sensitive_read_requires_pin_by_intent(pipeline, channel, brain):
    """The brain forgot requires_pin; the backend still gates QUERY_MEMORY."""
    user = await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.QUERY_MEMORY, reply="Dad takes insulin"))
    assert await say(pipeline, channel, ADMIN, "what are dad's notes?") == [PIN_NEEDED]
    replies = await say(pipeline, channel, ADMIN, PIN)
    assert replies == ["Dad takes insulin"]
    # step-up grace: a second read right after does not ask again
    brain.script.append(Interpretation(intent=Intent.QUERY_MEMORY, reply="again"))
    assert await say(pipeline, channel, ADMIN, "and mom's?") == ["again"]
    assert await pipeline.state.stepped_up(user.id)


async def test_large_delegation_and_phone_change_need_pin(pipeline, channel, brain):
    user = await onboard(pipeline, channel)
    big = TaskSpec(
        type=TaskType.BOOKING, goal="x", delegation=Delegation(granted=True, max_price_inr=50000)
    )
    brain.script.append(Interpretation(intent=Intent.NEW_TASK, task_spec=big, reply="ok"))
    assert await say(pipeline, channel, ADMIN, "book anything under 50000") == [PIN_NEEDED]
    dad = await pipeline.repos.people.upsert(
        Person(owner_user_id=user.id, name="Dad", phone="+919811110001")
    )
    from tests.api.test_pipeline import say as _say  # noqa: F401

    pipeline.clock.advance(minutes=11)  # grace + pending expire
    brain.script.append(
        Interpretation(
            intent=Intent.ADD_PERSON,
            person_upsert=dad.model_copy(update={"phone": "+919899999999"}),
            reply="updated",
        )
    )
    assert await say(pipeline, channel, ADMIN, "change dad's number") == [PIN_NEEDED]


async def test_sim_swap_signal_freezes_pin_actions(pipeline, channel, brain, wired):
    user = await onboard(pipeline, channel)
    from friday.core.models import InboundMessage

    await pipeline.handle(
        InboundMessage(
            channel="simulator",
            from_phone=ADMIN,
            kind=MessageKind.SYSTEM,
            text="user_changed_number",
        )
    )
    assert (await pipeline.repos.pin_locks.get(user.id)).active(pipeline.clock.now())
    assert wired.get("sms").sent  # SMS heads-up (WhatsApp may be the hijacked channel)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    assert await say(pipeline, channel, ADMIN, "delete everything") == [PIN_LOCKED]
    pipeline.clock.advance(hours=25)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    assert await say(pipeline, channel, ADMIN, "delete everything") == [PIN_NEEDED]


async def test_user_state_is_bounded_and_expires(clock):
    """SECURITY-34: pending state lives in a TTL cache, not an unbounded dict."""
    cache = MemoryCache(clock, max_entries=50)
    state = UserState(cache)
    for i in range(500):
        await state.set_pending(
            f"u{i}", PendingAction("pin", None, None, clock.now() + timedelta(minutes=10))
        )
    assert len(cache._data) <= 50  # type: ignore[attr-defined]
    await state.set_pending(
        "x", PendingAction("pin", None, None, clock.now() + timedelta(minutes=10))
    )
    assert await state.get_pending("x", clock.now()) is not None
    clock.advance(minutes=11)
    assert await state.get_pending("x", clock.now()) is None


async def test_circle_stop_suppresses_across_owners(pipeline, channel, wired):
    """SECURITY-16: STOP from a circle member suppresses the phone for every owner."""
    alice = await onboard(pipeline, channel)
    dad = await pipeline.repos.people.upsert(
        Person(
            owner_user_id=alice.id,
            name="Ramesh",
            phone="+919811110055",
            contact_consent=PersonConsent.OPTED_IN,
        )
    )
    await say(pipeline, channel, dad.phone, "STOP")
    assert await pipeline.repos.suppressions.is_suppressed(dad.phone)
    from friday.core.models import User, UserStatus

    bob = await pipeline.repos.users.add(User(phone="+919800000556", status=UserStatus.ACTIVE))
    bobs_dad = await pipeline.repos.people.upsert(
        Person(owner_user_id=bob.id, name="Dad B", phone=dad.phone)
    )
    assert bobs_dad.contact_consent == PersonConsent.OPTED_OUT
    r = await wired.notifier.request_person_opt_in(bobs_dad, requester_name="Bob", what="x")
    assert not r.ok


async def test_pin_pepper_is_separate_from_secret_key(wired, pipeline):
    """SECURITY-30: hash made with only the app secret as pepper still verifies (legacy)
    and is migrated to the dedicated pepper on next success."""
    from friday.core.models import User, UserStatus

    secret = wired.settings.secret_key.get_secret_value()
    legacy = PinHasher(secret, fast=True).hash(PIN)
    user = await pipeline.repos.users.add(
        User(phone="+919800000666", status=UserStatus.ACTIVE, pin_hash=legacy)
    )
    assert (await pipeline.pins.verify(user, PIN)).status == PinCheck.OK
    fresh = await pipeline.repos.users.get(user.id)
    assert fresh.pin_hash != legacy
    assert pipeline.pins.hasher.check(fresh.pin_hash, PIN) == "current"
    assert PinHasher(secret, fast=True).check(fresh.pin_hash, PIN) is None


async def test_consent_receipts_survive_delete_via_chat(pipeline, channel, brain, wired):
    user = await onboard(pipeline, channel)
    brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    await say(pipeline, channel, ADMIN, "delete everything")
    await say(pipeline, channel, ADMIN, PIN)
    await say(pipeline, channel, ADMIN, "DELETE")
    receipts = await pipeline.repos.consents.list_for_user(user.id)
    assert receipts and all(r.evidence_text is None for r in receipts)
    assert any(r.kind == ConsentKind.TERMS_PRIVACY for r in receipts)
