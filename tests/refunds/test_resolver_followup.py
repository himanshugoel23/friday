# ruff: noqa: E501
"""Who-to-call resolver (a number is never invented) and the vendor follow-up proposal flow."""

from __future__ import annotations

import random
import re
import string
from types import SimpleNamespace

import pytest

from friday.core.models import TaskType
from friday.docunderstand.models import DocType
from friday.docunderstand.store import MemoryDocStore
from friday.refunds import copy
from friday.refunds.config import RefundConfig
from friday.refunds.models import RefundCase, RefundState
from friday.refunds.ports import (
    EngineRefundTaskPort,
    KnownNumber,
    LinesPending,
    name_match,
)
from friday.refunds.resolver import (
    DocumentNumberSource,
    StaticNumberSource,
    TaskNumberSource,
    resolve,
)
from friday.refunds.service import RefundService
from tests.refunds.conftest import EXAMPLE_NUMBER, at, known, open_case
from tests.trips.conftest import HOTEL, make_doc

S = RefundState


def case(vendor="Exampleair", **kw) -> RefundCase:
    return RefundCase(user_id="u1", vendor_name=vendor, state=S.OPENED, **kw)


# ------------------------------------------------------------------ name matching
def test_name_match_is_conservative():
    assert name_match("Exampleair", "Exampleair Pvt Ltd")
    assert name_match("Exampleair EX 101", "Exampleair")  # flight numbers are ignored
    assert name_match("hotel example palms", "Hotel Example Palms")
    assert not name_match("Air", "Exampleair")  # a short fragment matches nothing
    assert not name_match("Exampleair", "Examplemart")
    assert not name_match("", "Exampleair") and not name_match("Exampleair", "")


# ------------------------------------------------------------------ never an invented number
async def test_no_sources_means_no_numbers():
    r = await resolve("u1", case(), [])
    assert r.empty and r.contacts == []


async def test_user_typed_number_comes_first_then_document_task_record():
    src = StaticNumberSource()
    src.add("u1", "Exampleair", KnownNumber("+919800000555", "vendor_record", "Exampleair"))
    src.add("u1", "Exampleair", KnownNumber("+919800000444", "task", "Exampleair"))
    src.add("u1", "Exampleair", KnownNumber("+919800000333", "document", "Exampleair"))
    r = await resolve("u1", case(user_number="+919800000999"), [src])
    assert [(c.source, c.number) for c in r.contacts] == [
        ("user", "+919800000999"),
        ("document", "+919800000333"),
        ("task", "+919800000444"),
        ("vendor_record", "+919800000555"),
    ]
    assert len({c.contact_id for c in r.contacts}) == 4


async def test_unusable_numbers_are_dropped_not_repaired():
    src = StaticNumberSource()
    for bad in ("112", "+91 12345", "not a number", "", "0000"):
        src.add("u1", "Exampleair", KnownNumber(bad, "document", "Exampleair"))
    src.add("u1", "Exampleair", KnownNumber("+91 98000 00333", "document", "Exampleair"))
    src.add("u1", "Exampleair", KnownNumber("09800000333", "task", "Exampleair"))  # same number
    src.add("u1", "Exampleair", KnownNumber("+919800000222", "scraped_from_web", "Exampleair"))
    r = await resolve("u1", case(), [src])
    assert [c.number for c in r.contacts] == ["+919800000333"]


async def test_other_vendors_and_other_users_numbers_are_not_returned():
    src = StaticNumberSource()
    src.add("u1", "Examplemart", known("+919800000111"))
    src.add("u2", "Exampleair", known("+919800000222"))
    assert (await resolve("u1", case(), [src])).empty


async def test_every_returned_number_was_handed_in_by_a_source():
    """Property: with random vendors and random held numbers, the resolver's output is always a
    subset of what the sources supplied (canonicalised). It never makes one up."""
    rng = random.Random(7)
    for _ in range(60):
        vendor = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(4, 10))).title()
        src = StaticNumberSource()
        held = set()
        for _ in range(rng.randint(0, 4)):
            n = "+91" + "".join(rng.choices("6789", k=1) + rng.choices(string.digits, k=9))
            held.add(n)
            src.add("u1", vendor, KnownNumber(n, rng.choice(["document", "task", "evidence", "vendor_record"]), vendor))
        r = await resolve("u1", case(vendor), [src])
        assert {c.number for c in r.contacts} <= held
        assert (len(r.contacts) == 0) == (not held)


async def test_issuer_is_a_name_never_a_number():
    r = await resolve("u1", case(paid_with_bank="Fictional Bank"), [])
    assert r.contacts == [] and r.issuer_bank == "Fictional Bank"
    assert not hasattr(r, "issuer_number")


async def test_document_source_reads_only_the_users_confirmed_hotel_documents():
    docs = MemoryDocStore()
    await docs.save(make_doc("u1", DocType.HOTEL, HOTEL))
    await docs.save(make_doc("u2", DocType.HOTEL, {**HOTEL, "phone": "+91 99999 00000"}))
    await docs.save(make_doc("u1", DocType.HOTEL, {**HOTEL, "property_name": "Other Inn", "phone": "+91 97777 00000"}))
    await docs.save(make_doc("u1", DocType.HOTEL, {**HOTEL, "property_name": "Hidden Hotel", "phone": "+91 96666 00000"}, confirmed=False))
    src = DocumentNumberSource(docs)
    got = await src.numbers_for("u1", "Hotel Example Palms")
    assert [(k.number, k.source) for k in got] == [("+91 80000 11111", "document")]
    assert await src.numbers_for("u1", "Hidden Hotel") == []  # unconfirmed documents are not used
    assert await src.numbers_for("u3", "Hotel Example Palms") == []


async def test_task_source_reads_numbers_the_user_already_had_friday_dial():
    mine = SimpleNamespace(requester_user_id="u1", spec=SimpleNamespace(business_phone="+919800000444", business_name="Exampleair"))
    other = SimpleNamespace(requester_user_id="u2", spec=SimpleNamespace(business_phone="+919800000555", business_name="Exampleair"))
    nameless = SimpleNamespace(requester_user_id="u1", spec=SimpleNamespace(business_phone="+919800000666", business_name=None))

    class Lister:
        async def list_for_user(self, user_id):
            return [mine, other, nameless]

    got = await TaskNumberSource(Lister()).numbers_for("u1", "Exampleair")
    assert [k.number for k in got] == ["+919800000444"]


# ------------------------------------------------------------------ who to call (the reply)
async def test_who_to_call_lists_sources_and_never_makes_one_up(svc, alice, numbers):
    c = await open_case(svc, alice.id)
    r = await svc.who_to_call(alice.id, c.id)
    assert "koi number mere paas" in r.text and not re.search(r"\d{6,}", r.text)
    numbers.add(alice.id, "Exampleair", known())
    r = await svc.who_to_call(alice.id, c.id)
    assert EXAMPLE_NUMBER in r.text and "verified vendor record" in r.text


async def test_user_number_is_validated_and_used(svc, alice):
    c = await open_case(svc, alice.id)
    assert "sahi nahi" in (await svc.set_number(alice.id, c.id, "112")).text
    assert "sahi nahi" in (await svc.set_number(alice.id, c.id, "abc")).text
    assert "Number rakh liya" in (await svc.set_number(alice.id, c.id, "98000 00123")).text
    r = await svc.resolve_contacts(alice.id, c.id)
    assert [(x.source, x.number) for x in r.contacts] == [("user", "+919800000123")]


# ------------------------------------------------------------------ the follow-up proposal
async def _due_followup(svc, alice, clock, numbers=None):
    c = await open_case(svc, alice.id)
    clock.set(at(11, 10, 1))
    await svc.run_user(alice.id)  # requested_q
    clock.set(at(13, 10, 1))
    out = await svc.run_user(alice.id)  # followup
    return c, out


async def test_follow_up_is_proposed_not_run_and_needs_a_yes(svc, alice, clock, numbers, sender, taskport):
    numbers.add(alice.id, "Exampleair", known())
    c, out = await _due_followup(svc, alice, clock)
    assert out[0].stage == "followup" and out[0].action == "sent"
    text = sender.texts(alice.id)[-1]
    assert EXAMPLE_NUMBER in text and "tabhi" in text and "message" in text  # asks; offers a draft
    assert [b.id.split(":")[-1] for b in sender.sent[-1][1].buttons] == ["call", "nocall"]
    assert taskport.created == []  # nothing started without the user
    cur = await svc.store.get_case(alice.id, c.id)
    assert cur.proposal.status == "offered" and cur.chase_count == 0


async def test_approval_creates_an_unapproved_task_through_the_port(svc, alice, clock, numbers, taskport):
    numbers.add(alice.id, "Exampleair", known())
    c, _ = await _due_followup(svc, alice, clock)
    r = await svc.approve_followup(alice.id, c.id)
    assert "phir poochungi" in r.text
    ((uid, spec, approved),) = taskport.created
    assert uid == alice.id and approved is False  # the engine still asks before it dials
    assert spec.type == TaskType.STATUS_CHASE and spec.business_phone == EXAMPLE_NUMBER
    assert spec.business_name == "Exampleair" and spec.questions == copy.VENDOR_CALL_QUESTIONS["hinglish"]
    cur = await svc.store.get_case(alice.id, c.id)
    assert cur.chase_count == 1 and cur.proposal.status == "approved" and cur.proposal.task_id
    assert (await svc.approve_followup(alice.id, c.id)).text == copy.t("case.unknown")  # once only


async def test_decline_starts_nothing(svc, alice, clock, numbers, taskport):
    numbers.add(alice.id, "Exampleair", known())
    c, _ = await _due_followup(svc, alice, clock)
    assert "nahi karungi" in (await svc.decline_followup(alice.id, c.id)).text
    assert taskport.created == []
    assert (await svc.approve_followup(alice.id, c.id)).text == copy.t("case.unknown")


async def test_no_number_held_means_ask_the_user_and_offer_a_draft(svc, alice, clock, taskport, sender):
    c, _ = await _due_followup(svc, alice, clock)
    text = sender.texts(alice.id)[-1]
    assert "number mere paas" in text and "nahi dhoondhti" in text and "Namaste" in text
    assert not re.search(r"\d{6,}", text) and sender.sent[-1][1].buttons == []
    assert taskport.created == []
    assert (await svc.store.get_case(alice.id, c.id)).proposal.status == "needs_number"


async def test_the_number_is_rechecked_at_approval(svc, alice, clock, numbers, taskport):
    numbers.add(alice.id, "Exampleair", known())
    c, _ = await _due_followup(svc, alice, clock)
    numbers.rows.clear()  # the record was removed after the offer
    r = await svc.approve_followup(alice.id, c.id)
    assert "number mere paas" in r.text and taskport.created == []


async def test_chase_calls_switch_off_gives_a_draft_only(rsettings, store, clock, alice, numbers, sender, taskport):
    s = rsettings.model_copy(update={"refund_chase_calls": False})
    svc = RefundService(s, store, clock, sender=sender, tasks=taskport, sources=[numbers])
    numbers.add(alice.id, "Exampleair", known())
    c, _ = await _due_followup(svc, alice, clock)
    assert "chalu nahi" in sender.texts(alice.id)[-1] and sender.sent[-1][1].buttons == []
    assert (await svc.approve_followup(alice.id, c.id)).text == copy.t("case.unknown")
    assert taskport.created == []


async def test_at_most_two_follow_ups_per_case(svc, alice, clock, numbers, taskport):
    numbers.add(alice.id, "Exampleair", known())
    c = await open_case(svc, alice.id)
    for _ in range(3):
        cur = await svc.store.get_case(alice.id, c.id)
        from friday.refunds.models import Proposal

        cur.proposal = Proposal(kind="call", status="offered", contact_id=(await svc.resolve_contacts(alice.id, c.id)).contacts[0].contact_id)
        await svc.store.save_case(cur)
        await svc.approve_followup(alice.id, c.id)
    assert len(taskport.created) == 2
    cur = await svc.store.get_case(alice.id, c.id)
    cur.proposal = None
    msg = await svc._followup_message(cur)
    assert "2 follow-up ho chuke" in msg.text and msg.buttons[0].id.endswith(":close")


async def test_finished_follow_up_links_its_proof_and_marks_requested(svc, alice, clock, numbers, taskport):
    from friday.evidence.models import EvidenceItem, EvidenceKind, EvidenceLevel

    numbers.add(alice.id, "Exampleair", known())
    c, _ = await _due_followup(svc, alice, clock)
    await svc.approve_followup(alice.id, c.id)
    tid = (await svc.store.get_case(alice.id, c.id)).proposal.task_id
    item = EvidenceItem(user_id=alice.id, task_id=tid, kind=EvidenceKind.CALL_SUMMARY, level=EvidenceLevel.OBSERVED, summary="called")
    assert await svc.on_followup_finished("someone-else", tid, [item]) is None
    got = await svc.on_followup_finished(alice.id, tid, [item])
    assert got.state == S.REQUESTED
    assert [e.level for e in await svc.store.list_evidence(alice.id, c.id)] == [EvidenceLevel.OBSERVED]


# ------------------------------------------------------------------ the real port refuses while PENDING
async def test_engine_port_refuses_while_the_call_lines_are_pending():
    assert copy.CALL_LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    called = []

    class Engine:
        async def create_task(self, *a, **k):
            called.append(a)
            return SimpleNamespace(id="x")

    port = EngineRefundTaskPort(Engine())
    spec = RefundService.followup_spec(SimpleNamespace(lang="hinglish"), case(), (await resolve("u1", case(user_number=EXAMPLE_NUMBER), [])).contacts[0])
    with pytest.raises(LinesPending):
        await port.create_task("u1", spec, approved=False)
    assert called == []


def test_config_defaults():
    cfg = RefundConfig()
    assert (cfg.weekly_cap, cfg.max_chase_calls, cfg.chase_calls_enabled) == (3, 2, False)
