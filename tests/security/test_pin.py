"""Red team: the Friday PIN - never stored raw, never logged/echoed/sent to the LLM,
brute force stopped by lockout."""

from __future__ import annotations

import logging

import pytest

from friday.api.security import PinCheck, PinHasher, PinService, extract_pin, pin_problem
from friday.core.models import InboundMessage, Intent, Interpretation, OnboardingStep, UserStatus
from tests.security.conftest import ALICE_PHONE, PIN, SECRET, make_active_user, say

WRONG = "7391"


async def _messages_text(repos, user_id: str) -> str:
    return "\n".join((m.text or "") for m in await repos.messages.list_for_user(user_id, limit=500))


async def test_pin_hash_is_peppered_argon2_not_raw(repos, clock) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    stored = await repos.users.get(user.id)
    assert stored.pin_hash and stored.pin_hash.startswith("$argon2id$")
    assert PIN not in stored.pin_hash
    # pepper: a hasher without the app secret cannot verify the PIN
    assert PinHasher(SECRET, fast=True).verify(stored.pin_hash, PIN)
    assert not PinHasher("another-secret", fast=True).verify(stored.pin_hash, PIN)


@pytest.mark.parametrize("pin", ["1234", "0000", "1111", "2580", "12345", "12a4", ""])
def test_weak_or_malformed_pins_rejected(pin: str) -> None:
    assert pin_problem(pin) is not None


async def test_lockout_after_max_attempts_and_correct_pin_still_locked(repos, clock) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    svc = PinService(PinHasher(SECRET, fast=True), repos.users, clock, 5, repos.audit)
    results = [await svc.verify(user, WRONG) for _ in range(5)]
    assert [r.status for r in results[:4]] == [PinCheck.WRONG] * 4
    assert results[4].status == PinCheck.LOCKED
    assert (await svc.verify(user, PIN)).status == PinCheck.LOCKED  # no oracle while locked
    # a fresh process (in-memory lock state lost) is still locked via the audit log
    svc2 = PinService(PinHasher(SECRET, fast=True), repos.users, clock, 5, repos.audit)
    fresh = await repos.users.get(user.id)
    assert (await svc2.verify(fresh, PIN)).status == PinCheck.LOCKED
    clock.advance(minutes=31)
    assert (await svc2.verify(fresh, PIN)).status == PinCheck.OK


async def test_pin_entry_is_redacted_never_echoed_never_sent_to_brain(
    repos, clock, pipeline, channel, fake_brain, fake_engine, caplog
) -> None:
    caplog.set_level(logging.INFO)
    user = await make_active_user(repos, clock, ALICE_PHONE)
    fake_brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    replies = await say(pipeline, channel, ALICE_PHONE, "delete everything")
    assert any("PIN" in r for r in replies)
    replies += await say(pipeline, channel, ALICE_PHONE, PIN)
    replies += await say(pipeline, channel, ALICE_PHONE, "CANCEL")
    assert all(PIN not in r for r in replies)
    assert PIN not in fake_brain.seen
    assert PIN not in await _messages_text(repos, user.id)
    ours = [r.getMessage() for r in caplog.records if r.name.startswith("friday")]
    assert all(PIN not in m for m in ours)
    assert all(ALICE_PHONE not in m for m in ours)


async def test_wrong_pins_lock_sensitive_actions_via_chat(
    repos, clock, pipeline, channel, fake_brain
) -> None:
    await make_active_user(repos, clock, ALICE_PHONE)
    fake_brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    await say(pipeline, channel, ALICE_PHONE, "delete everything")
    replies = []
    for _ in range(5):
        replies += await say(pipeline, channel, ALICE_PHONE, WRONG)
    assert any("locked" in r.lower() for r in replies)
    fake_brain.script.append(Interpretation(intent=Intent.DELETE_DATA, requires_pin=True))
    replies = await say(pipeline, channel, ALICE_PHONE, "delete everything")
    assert any("locked" in r.lower() for r in replies)
    user = await repos.users.get_by_phone(ALICE_PHONE)
    assert user.status == UserStatus.ACTIVE  # nothing was deleted


async def test_onboarding_pin_never_reaches_brain_or_log(
    repos, clock, pipeline, channel, fake_brain
) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE, pin=None)
    user.status = UserStatus.ONBOARDING
    user.onboarding_step = OnboardingStep.PIN
    await repos.users.save(user)
    replies = await say(pipeline, channel, ALICE_PHONE, PIN)
    replies += await say(pipeline, channel, ALICE_PHONE, PIN)
    assert all(PIN not in r for r in replies)
    assert PIN not in fake_brain.seen
    assert PIN not in await _messages_text(repos, user.id)
    assert (await repos.users.get(user.id)).pin_hash


def test_extract_pin_requires_exactly_one_group() -> None:
    assert extract_pin("4 8 2 6") == "4826"
    assert extract_pin("1234 5678") is None
    assert extract_pin("call me at 9876543210") is None


async def test_pin_inside_sentence_is_redacted(repos, clock, pipeline, fake_brain) -> None:
    user = await make_active_user(repos, clock, ALICE_PHONE)
    await pipeline.handle(
        InboundMessage(
            channel="simulator", from_phone=ALICE_PHONE, text=f"delete everything, my pin is {PIN}"
        )
    )
    assert all(PIN not in (s or "") for s in fake_brain.seen)
    assert PIN not in await _messages_text(repos, user.id)
