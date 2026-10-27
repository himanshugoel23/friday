# ruff: noqa: E501
"""Proof on "done" inside the real task engine (fakes only). Switch OFF = old message."""

from __future__ import annotations

from friday.core.models import CallOutcome, CallTurn, Delegation, Speaker, Transcript
from friday.core.models import TaskStatus as S
from friday.evidence import copy
from friday.evidence.models import ProofStatus
from friday.evidence.store import MemoryEvidenceStore
from tests.tasks.conftest import LOOKS, booking
from tests.tasks.fakes import outcome, quote

DELEGATED = Delegation(granted=True, max_price_inr=500)


def said(text: str) -> Transcript:
    return Transcript(turns=[CallTurn(speaker=Speaker.CALLEE, text=text)])


def turn_on(env, **kw) -> MemoryEvidenceStore:
    store = MemoryEvidenceStore()
    env.repos.evidence = store
    env.engine.settings = env.engine.settings.model_copy(update={"proof_enabled": True, **kw})
    return store


def script_booking(env, heard: str, **collected):
    env.runner.script(
        LOOKS,
        outcome(
            CallOutcome.SUCCESS,
            transcript=said(heard),
            quotes=[quote("Looks", 400)],
            collected={
                "committed": "true",
                "summary": "Booked the haircut.",
                "time": "6pm",
                **collected,
            },
        ),
    )


async def test_switch_off_is_the_old_message_and_stores_nothing(env):
    store = MemoryEvidenceStore()
    env.repos.evidence = store
    assert env.engine.settings.proof_enabled is False  # default OFF
    script_booking(env, "Yes confirmed, number BK4821", reference="BK4821")
    t = await env.task(booking(delegation=DELEGATED))
    assert t.status == S.COMPLETED
    assert env.texts()[-1] == "Booked the haircut.\ntime: 6pm\nreference: BK4821"
    assert store.items == [] and store.claims == {}


async def test_proven_booking_carries_reference_and_call_proof(env):
    store = turn_on(env)
    script_booking(env, "Yes confirmed, your number is BK4821", reference="BK4821")
    t = await env.task(booking(delegation=DELEGATED))
    assert t.status == S.COMPLETED  # no new TaskStatus: still COMPLETED
    text = env.texts()[-1]
    assert text.startswith("Booked the haircut.") and "Reference: BK4821" in text
    assert "Looks Unisex Salon" in text
    claim = store.claims[t.id]
    assert claim.status == ProofStatus.PROVEN and claim.user_id == env.user.id
    assert {i.kind.value for i in store.items} >= {"call_summary", "booking_ref"}
    assert all(i.expires_at and (i.expires_at - i.captured_at).days == 90 for i in store.items)


async def test_booking_without_a_reference_does_not_say_done_in_strict_mode(env):
    store = turn_on(env)
    script_booking(env, "Yes, see you at six.")
    t = await env.task(booking(delegation=DELEGATED))
    text = env.texts()[-1]
    assert text.startswith(copy.t("partial.head")) and "Booked the haircut." not in text
    assert store.claims[t.id].status == ProofStatus.PARTIAL
    assert store.claims[t.id].missing == ["reference"]


async def test_soft_mode_keeps_the_message_and_names_what_is_missing(env):
    turn_on(env, proof_strict=False)
    script_booking(env, "Yes, see you at six.")
    await env.task(booking(delegation=DELEGATED))
    text = env.texts()[-1]
    assert text.startswith("Booked the haircut.") and copy.t("missing.reference") in text


async def test_store_failure_never_blocks_the_completion_message(env):
    class Broken(MemoryEvidenceStore):
        async def add_items(self, items):
            raise RuntimeError("db down")

    env.repos.evidence = Broken()
    env.engine.settings = env.engine.settings.model_copy(update={"proof_enabled": True})
    script_booking(env, "Yes confirmed BK4821", reference="BK4821")
    t = await env.task(booking(delegation=DELEGATED))
    assert t.status == S.COMPLETED and "Reference: BK4821" in env.texts()[-1]


async def test_proof_on_but_no_store_is_the_old_message(env):
    env.engine.settings = env.engine.settings.model_copy(update={"proof_enabled": True})
    script_booking(env, "Yes confirmed BK4821", reference="BK4821")
    await env.task(booking(delegation=DELEGATED))
    assert env.texts()[-1] == "Booked the haircut.\ntime: 6pm\nreference: BK4821"
