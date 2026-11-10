# ruff: noqa: E501
"""C1 + the hard rules: request model, queue order, claim/assign, proof before done, SLAs, escalation, never pays, no secrets,
spend ceiling, only parent/child admin, distress rerouted. Tested with fakes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.concierge.models import Priority, Status
from friday.concierge.service import BadState, Denied, DeskSettings, ProofRequired
from tests.concierge.conftest import PARENT_NUMBER, make_rig


async def ask(rig, who="par1", **payload):
    payload.setdefault("summary", "Pay the electricity bill for this month")
    payload.setdefault("category", "bill")
    return await rig.service.intake(who, payload)


# ---------------------------------------------------------------- hard rules
@pytest.mark.parametrize("field", ["card_number", "cvv", "upi_pin", "otp", "password", "bank_account", "payment_amount", "net_banking_login", "aadhaar"])
async def test_no_payment_or_credential_field_is_accepted(rig, field):
    res = await ask(rig, **{field: "x"})
    assert not res.ok and res.code == "payment_or_credential_field_refused"
    assert await rig.store.requests_open() == []


async def test_unknown_fields_are_refused_too(rig):
    assert (await ask(rig, colour="red")).code == "unknown_field"


@pytest.mark.parametrize("text,code", [
    ("my otp is 482913 please pay", "otp_refused"),
    ("OTP: 123456", "otp_refused"),
    ("the password is hunter2 for the site", "credential_refused"),
    ("my upi pin 4821", "credential_refused"),
    ("cvv on the back", "credential_refused"),
    ("card 4111 1111 1111 1111 use it", "card_refused"),
    ("aadhaar 2345 6789 0123", "aadhaar_refused"),
])
async def test_otp_password_card_aadhaar_text_is_refused_and_not_stored(rig, text, code):
    res = await ask(rig, summary=text)
    assert not res.ok and res.code == code and res.request_id is None
    assert await rig.store.requests_open() == []
    assert text not in repr([e.__dict__ for e in await rig.audit.entries()])


async def test_a_plain_number_that_is_not_a_card_is_fine(rig):
    assert (await ask(rig, summary="Bill number 1234567890123 at the counter")).ok


async def test_only_parent_or_child_admin_may_ask(rig):
    assert (await ask(rig, who="sec1")).code == "not_allowed"  # second contact
    assert (await ask(rig, who="nobody")).code == "not_allowed"
    assert (await ask(rig, who="par1")).ok and (await ask(rig, who="kid1")).ok


@pytest.mark.parametrize("text", ["bachao mujhe", "I have chest pain, call someone", "papa gir gaye hain", "someone is threatening me", "I want to die"])
async def test_distress_text_goes_to_the_ai_emergency_path_not_the_queue(rig, text):
    res = await ask(rig, summary=text)
    assert res.code == "rerouted_emergency" and res.incident_id and not res.ok and res.request_id is None
    assert rig.emergency.calls[-1][:2] == ("par1", "par1")
    assert await rig.store.requests_open() == []


async def test_spend_above_the_ceiling_needs_the_childs_yes(rig):
    over = rig.cfg.spend_ceiling_paise + 1
    res = await ask(rig, who="par1", estimated_paise=over, child_approved=True)  # a parent cannot approve their own spend
    assert res.code == "waiting_child_yes"
    req = await rig.store.request_get(res.request_id)
    assert req.status == Status.WAITING_USER and not req.child_approved
    with pytest.raises(BadState):  # not claimable until the child says yes
        await rig.service.claim(rig.staff("c1"), res.request_id)
    assert not await rig.service.child_yes("par1", res.request_id)  # parent cannot
    assert not await rig.service.child_yes("oth1", res.request_id)  # another family's child cannot
    assert await rig.service.child_yes("kid1", res.request_id)
    await rig.service.claim(rig.staff("c1"), res.request_id)
    assert (await rig.store.request_get(res.request_id)).status == Status.CLAIMED


async def test_child_can_ask_over_the_ceiling_with_their_own_yes(rig):
    res = await ask(rig, who="kid1", estimated_paise=rig.cfg.spend_ceiling_paise + 1, child_approved=True)
    assert res.code == "created"


async def test_pay_link_is_generated_for_the_user_and_respects_the_ceiling(rig):
    res = await ask(rig)
    await rig.service.claim(rig.staff("c1"), res.request_id)
    link = await rig.service.pay_link(rig.staff("c1"), res.request_id, "bses@upi", "Electricity board", 123456)
    assert link.startswith("upi://pay?") and "am=1234.56" in link and "pa=bses%40upi" in link
    with pytest.raises(BadState):
        await rig.service.pay_link(rig.staff("c1"), res.request_id, "bses@upi", "Board", rig.cfg.spend_ceiling_paise + 100)
    with pytest.raises(BadState):
        await rig.service.pay_link(rig.staff("c1"), res.request_id, "not a vpa", "Board", 100)


async def test_the_model_has_no_payment_field():
    from dataclasses import fields

    from friday.concierge.models import ConciergeRequest

    names = {f.name for f in fields(ConciergeRequest)}
    assert not {n for n in names if any(h in n for h in ("card", "cvv", "pin", "otp", "password", "account", "paid", "bank"))}


# ---------------------------------------------------------------- queue, claim, assign
async def test_queue_orders_safety_then_health_then_convenience_then_due(rig):
    a = await ask(rig, category="grocery")
    rig.clock.advance(minutes=1)
    b = await ask(rig, category="medicine", summary="Get the BP tablets")
    rig.clock.advance(minutes=1)
    c = await ask(rig, category="locksmith", summary="Lock is broken")
    rig.clock.advance(minutes=1)
    d = await ask(rig, category="cab")
    rows = await rig.service.queue(rig.staff("lead1"))
    assert [r.id for r in rows] == [c.request_id, b.request_id, a.request_id, d.request_id]
    assert [r.priority for r in rows][:2] == [Priority.SAFETY, Priority.HEALTH]


async def test_claim_is_exclusive_and_release_returns_it(rig):
    r = (await ask(rig)).request_id
    await rig.service.claim(rig.staff("c1"), r)
    with pytest.raises(BadState):
        await rig.service.claim(rig.staff("c2"), r)
    with pytest.raises(Denied):
        await rig.service.note(rig.staff("c2"), r, "hello")  # not theirs
    with pytest.raises(Denied):
        await rig.service.view(rig.staff("c2"), r)  # minimum data: another person's request is not shown
    await rig.service.release(rig.staff("c1"), r)
    await rig.service.claim(rig.staff("c2"), r)
    assert (await rig.store.request_get(r)).claimed_by == "c2"


async def test_lead_assigns_but_a_concierge_cannot(rig):
    r = (await ask(rig)).request_id
    with pytest.raises(Denied):
        await rig.service.assign(rig.staff("c1"), r, "c2")
    await rig.service.assign(rig.staff("lead1"), r, "c2")
    assert (await rig.store.request_get(r)).claimed_by == "c2"
    with pytest.raises(BadState):
        await rig.service.assign(rig.staff("lead1"), r, "rev1")  # a reviewer cannot take work


async def test_done_needs_proof_then_works_and_the_user_confirms(rig):
    r = (await ask(rig)).request_id
    s = rig.staff("c1")
    await rig.service.claim(s, r)
    with pytest.raises(ProofRequired):
        await rig.service.done(s, r)
    assert (await rig.store.request_get(r)).status == Status.CLAIMED
    with pytest.raises(BadState):
        await rig.service.proof(s, r, "screenshot", "x")  # unknown kind
    await rig.service.proof(s, r, "receipt", "obj/receipt-1")
    await rig.service.done(s, r)
    req = await rig.store.request_get(r)
    assert req.status == Status.DONE and req.done_at and not req.user_confirmed
    assert not await rig.service.user_confirm("sec1", r) and await rig.service.user_confirm("par1", r)
    with pytest.raises(BadState):
        await rig.service.release(s, r)  # DONE is final


async def test_notes_and_proofs_refuse_codes_and_passwords(rig):
    r = (await ask(rig)).request_id
    s = rig.staff("c1")
    await rig.service.claim(s, r)
    with pytest.raises(BadState):
        await rig.service.note(s, r, "the otp is 556677")
    with pytest.raises(BadState):
        await rig.service.proof(s, r, "call_note", "password is abc")
    await rig.service.note(s, r, "Called the shop, they open at 10")
    assert [t for _s, t in (await rig.service.view(s, r)).notes] == ["Called the shop, they open at 10"]


async def test_escalate_raises_priority_and_only_a_lead_takes_it(rig):
    r = (await ask(rig, category="grocery")).request_id
    await rig.service.claim(rig.staff("c1"), r)
    await rig.service.escalate(rig.staff("c1"), r, "cannot_reach")
    req = await rig.store.request_get(r)
    assert req.status == Status.ESCALATED and req.priority == Priority.HEALTH and req.claimed_by is None and req.escalations == 1
    with pytest.raises(Denied):
        await rig.service.claim(rig.staff("c2"), r)
    await rig.service.claim(rig.staff("lead1"), r)
    with pytest.raises(BadState):
        await rig.service.escalate(rig.staff("lead1"), r, "because")  # fixed reasons only


async def test_sla_states_come_from_settings():
    rig = make_rig(DeskSettings(ack_s=60, finish_s={Priority.SAFETY: 120, Priority.HEALTH: 300, Priority.CONVENIENCE: 600}))
    r = (await ask(rig)).request_id
    assert [x.sla for x in await rig.service.queue(rig.staff("c1"))] == ["ok"]
    rig.clock.advance(seconds=61)
    assert [x.sla for x in await rig.service.queue(rig.staff("c1"))] == ["ack_overdue"]
    await rig.service.claim(rig.staff("c1"), r)
    assert [x.sla for x in await rig.service.queue(rig.staff("c1"))] == ["ok"]
    rig.clock.advance(seconds=600)
    assert [x.sla for x in await rig.service.queue(rig.staff("c1"))] == ["finish_overdue"]
    req = await rig.store.request_get(r)
    assert req.finish_due_at - req.created_at == timedelta(seconds=600)


async def test_view_has_the_minimum_and_a_masked_number(rig):
    r = (await ask(rig)).request_id
    v = await rig.service.view(rig.staff("c1"), r)
    shown = repr(v)
    assert v.parent_phone_masked == "+91 ••••• ••555" and PARENT_NUMBER not in shown and "9800000555" not in shown
    assert "par1" not in shown and "fam1" not in shown  # no member or family ids
