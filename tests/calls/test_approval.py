"""Approval message, buttons and the hash binding: edit invalidates, old buttons go stale."""

from __future__ import annotations

import pytest

from friday.calls.approval import (
    PREFIX,
    ApprovalService,
    StaleApproval,
    parse_button,
)
from friday.calls.fakes import FakeOpeningLineProvider
from friday.calls.models import CallBrief, CalleeKind, CallRequest, Limits
from friday.core.clock import FakeClock
from tests.calls.conftest import MUMMY, World


def _pair(world: World, **brief_kw):
    req = CallRequest(
        user_id=world.user.id, callee_kind=CalleeKind.PROVIDER, purpose="kal aane ke liye",
        callee_name="Plumber", callee_number=MUMMY,
    )  # fmt: skip
    brief = CallBrief(
        request_id=req.id, user_id=world.user.id, callee_kind=CalleeKind.PROVIDER,
        callee_name="Plumber", goal="kal aane ke liye", must_say=["kal aa sakte hain?"],
        ask_list=["kitna lagega"], must_not_say=["OTP"], user_display_name="Rahul",
        limits=Limits(max_price_inr=500), **brief_kw,
    )  # fmt: skip
    return req, brief


async def test_message_shows_the_plan_and_the_exact_opening_line(world: World):
    req, brief = _pair(world)
    fresh, prompt = await world.approval.prepare(req, brief)
    assert fresh.opening_line and fresh.opening_line in prompt.text
    for must in ("Plumber", "kal aane ke liye", "kitna lagega", "OTP", "Rs 500"):
        assert must in prompt.text
    assert [b.title for b in prompt.buttons] == ["Approve", "Edit", "Cancel"]
    assert all(b.id.startswith(PREFIX) and len(b.title) <= 20 for b in prompt.buttons)
    assert prompt.shown_hash == fresh.content_hash()


async def test_private_facts_and_numbers_never_appear_in_the_message(world: World):
    req, brief = _pair(
        world, private_facts=["meri salary 90000 hai"], shareable_facts=["late hoon"]
    )
    brief = brief.model_copy(update={"must_say": ["meri salary 90000 hai", f"call {MUMMY}"]})
    _fresh, prompt = await world.approval.prepare(req, brief)
    assert "salary" not in prompt.text and "[private]" in prompt.text
    assert "9000000001" not in prompt.text and "number ending 0001" in prompt.text


async def test_approve_stamps_the_hash_of_what_was_shown(world: World):
    req, brief = _pair(world)
    fresh, prompt = await world.approval.prepare(req, brief)
    assert not fresh.approved and not fresh.is_approved_as_is()
    press = parse_button(prompt.buttons[0].id)
    assert press.action == "approve" and press.request_id == req.id
    ok = world.approval.approve(fresh, press.hash8, world.clock.now())
    assert ok.approved and ok.approval_hash == fresh.content_hash() and ok.is_approved_as_is()
    assert ok.approved_at == world.clock.now()


async def test_editing_invalidates_the_approval(world: World):
    req, brief = _pair(world)
    fresh, prompt = await world.approval.prepare(req, brief)
    ok = world.approval.approve(fresh, prompt.shown_hash[:8])
    edited = world.approval.edit(ok, goal="parso aane ke liye")
    assert not edited.approved and edited.approval_hash is None and edited.approved_at is None
    assert edited.version == ok.version + 1
    assert not edited.is_approved_as_is()
    # forging the flags without the right hash does not help either
    forged = edited.model_copy(update={"approved": True, "approval_hash": ok.approval_hash})
    assert not forged.is_approved_as_is()


async def test_every_content_field_is_covered_by_the_hash(world: World):
    req, brief = _pair(world)
    ok = world.approval.approve(brief, brief.content_hash()[:8])
    changes = {
        "goal": "x", "must_say": ["y"], "must_not_say": ["z"], "ask_list": ["q"],
        "limits": Limits(max_price_inr=900), "tone": "angry", "relationship": "boss",
        "language": "en", "shareable_facts": ["f"], "private_facts": ["p"], "opening_line": "hi",
        "callee_number_hash": "abc", "callee_name": "Other", "user_display_name": "Sam",
    }  # fmt: skip
    for field, value in changes.items():
        changed = ok.model_copy(update={field: value})
        assert changed.content_hash() != ok.approval_hash, field
        assert not changed.is_approved_as_is(), field


async def test_a_button_from_an_old_message_cannot_approve_a_newer_plan(world: World):
    req, brief = _pair(world)
    fresh, old = await world.approval.prepare(req, brief)
    newer = world.approval.edit(fresh, goal="parso aane ke liye")
    with pytest.raises(StaleApproval):
        world.approval.approve(newer, old.shown_hash[:8])
    with pytest.raises(StaleApproval):
        world.approval.approve(newer, "")


async def test_edit_only_touches_editable_fields(world: World):
    _req, brief = _pair(world)
    with pytest.raises(ValueError):
        world.approval.edit(brief, callee_number_hash="x")
    with pytest.raises(ValueError):
        world.approval.edit(brief, approved=True)


async def test_group_children_are_approved_only_if_the_parent_is(world: World):
    req, brief = _pair(world)
    child_req, child_brief = _pair(world)
    with pytest.raises(StaleApproval):
        world.approval.derive_children(brief, [(child_req, child_brief)])
    ok = world.approval.approve(brief, brief.content_hash()[:8])
    (stamped,) = world.approval.derive_children(ok, [(child_req, child_brief)])
    assert stamped.is_approved_as_is()


async def test_button_parsing_rejects_garbage():
    for bad in ("", "x", f"{PREFIX}:a:b", f"{PREFIX}:r:delete:abcd1234", "a:t:yes"):
        assert parse_button(bad) is None


async def test_stale_notice_is_shown_when_a_plan_changed():
    svc = ApprovalService(FakeOpeningLineProvider(), FakeClock())
    req = CallRequest(user_id="u", callee_kind=CalleeKind.UNKNOWN, purpose="p", callee_name="X")
    brief = CallBrief(request_id=req.id, user_id="u", callee_kind=CalleeKind.UNKNOWN, goal="g")
    _b, prompt = await svc.prepare(req, brief, stale=True)
    assert "purana approval" in prompt.text
