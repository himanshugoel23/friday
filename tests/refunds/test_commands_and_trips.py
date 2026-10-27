# ruff: noqa: E501
"""Chat commands (Hinglish and English) and the trip-cancellation hook. Fakes only."""

from __future__ import annotations

from datetime import date

import pytest

from friday.core.clock import IST
from friday.docunderstand.models import DocType
from friday.docunderstand.store import MemoryDocStore
from friday.refunds.commands import (
    RefundCommands,
    extract_amount,
    extract_vendor,
    parse_date,
    parse_paise,
)
from friday.refunds.models import Origin, RefundState
from friday.trips.fakes import FakeFlightStatus, FakeTripSender, Scripted
from friday.trips.service import TripService
from friday.trips.store import MemoryTripStore
from tests.refunds.conftest import at
from tests.trips.conftest import FLIGHT_OUT, make_doc

S = RefundState


# ------------------------------------------------------------------ parsing
def test_parsers():
    assert parse_paise("4,500") == 450000 and parse_paise("99.50") == 9950
    assert parse_paise("0") is None and parse_paise("x") is None
    assert extract_amount("Exampleair ka refund nahi aaya 4500") == 450000
    assert extract_amount("refund nahi aaya Rs. 1,200.50") == 120050
    assert extract_amount("refund nahi aaya 20 Nov") is None  # a day number is not an amount
    assert extract_amount("refund nahi aaya") is None
    assert extract_vendor("Exampleair ka refund nahi aaya") == "Exampleair"
    assert extract_vendor("mera Hotel Example Palms ka refund nahi aaya 4500") == "Hotel Example Palms"
    assert extract_vendor("my refund from Exampleair has not arrived") == "Exampleair"
    assert extract_vendor("mera refund nahi aaya") == ""
    assert parse_date("20", "Nov", date(2026, 11, 10)) == date(2026, 11, 20)
    assert parse_date("5", "Jan", date(2026, 11, 10)) == date(2027, 1, 5)  # next occurrence
    assert parse_date("31", "Feb", date(2026, 11, 10)) is None and parse_date("5", "Xyz", date(2026, 11, 10)) is None


@pytest.fixture
def cmd(svc):
    return RefundCommands(svc)


# ------------------------------------------------------------------ opening and listing
async def test_not_arrived_opens_a_case_with_the_amount(cmd, svc, alice):
    r = await cmd.handle_text(alice.id, "Exampleair ka refund nahi aaya 4500")
    assert "Exampleair" in r.text and "Rs 4,500" in r.text
    (c,) = await svc.store.list_cases(alice.id)
    assert (c.vendor_name, c.amount_expected_paise, c.state) == ("Exampleair", 450000, S.OPENED)


async def test_not_arrived_without_a_vendor_asks_who(cmd, svc, alice):
    r = await cmd.handle_text(alice.id, "mera refund nahi aaya")
    assert "Kis ka refund" in r.text and await svc.store.list_cases(alice.id) == []


async def test_not_arrived_without_a_vendor_reuses_the_only_open_case(cmd, svc, alice):
    await svc.open_by_user(alice.id, "Exampleair")
    r = await cmd.handle_text(alice.id, "mera refund nahi aaya")
    assert "pehle se track" in r.text and len(await svc.store.list_cases(alice.id)) == 1


@pytest.mark.parametrize(
    "text", ["mera refund kahan hai", "where is my refund", "refund status dikhao", "my refunds"]
)
async def test_where_is_my_refund_phrases(cmd, svc, alice, text):
    await svc.open_by_user(alice.id, "Exampleair")
    r = await cmd.handle_text(alice.id, text)
    assert "Exampleair" in r.text and "khule refund" in r.text


# ------------------------------------------------------------------ the user's updates
async def test_received_with_an_amount_closes_and_without_asks(cmd, svc, alice):
    await svc.open_by_user(alice.id, "Exampleair", amount_paise=450000)
    assert "Kitna aaya" in (await cmd.handle_text(alice.id, "Exampleair refund aa gaya")).text
    r = await cmd.handle_text(alice.id, "Exampleair refund aa gaya 4500")
    assert "aa gaya" in r.text
    (c,) = await svc.store.list_cases(alice.id)
    assert c.state == S.CLOSED and c.amount_received_paise == 450000


async def test_english_updates(cmd, svc, alice):
    await svc.open_by_user(alice.id, "Exampleair", amount_paise=450000)
    assert "Exampleair" in (await cmd.handle_text(alice.id, "Exampleair refund requested")).text
    r = await cmd.handle_text(alice.id, "Exampleair refund received 4000")
    assert "kam" in r.text
    (c,) = await svc.store.list_cases(alice.id)
    assert c.state == S.RECEIVED


async def test_promise_phrases(cmd, svc, alice, clock):
    await svc.open_by_user(alice.id, "Exampleair")
    r = await cmd.handle_text(alice.id, "Exampleair ne 20 Nov tak 4500 ka kaha")
    assert "20 Nov" in r.text and "Rs 4,500" in r.text
    r = await cmd.handle_text(alice.id, "Exampleair said 3000 by 25 Nov")
    assert "25 Nov" in r.text and "Rs 3,000" in r.text
    (c,) = await svc.store.list_cases(alice.id)
    assert (c.state, c.promised_date, c.promised_amount_paise) == (S.PROMISED, date(2026, 11, 25), 300000)


async def test_other_verbs(cmd, svc, alice):
    await svc.open_by_user(alice.id, "Exampleair")
    await svc.open_by_user(alice.id, "Examplemart")
    assert "kaun sa refund" in (await cmd.handle_text(alice.id, "refund maang liya")).text.lower()
    await cmd.handle_text(alice.id, "Exampleair refund maang liya")
    await cmd.handle_text(alice.id, "Examplemart refund rejected")
    await cmd.handle_text(alice.id, "Examplemart refund escalate")
    states = {c.vendor_name: c.state for c in await svc.store.list_cases(alice.id)}
    assert states == {"Exampleair": S.REQUESTED, "Examplemart": S.ESCALATED}
    await cmd.handle_text(alice.id, "Exampleair refund band karo")
    assert {c.vendor_name: c.state for c in await svc.store.list_cases(alice.id)}["Exampleair"] == S.CLOSED


async def test_number_command_and_who_to_call(cmd, svc, alice):
    await svc.open_by_user(alice.id, "Exampleair")
    assert "Number rakh liya" in (await cmd.handle_text(alice.id, "refund number +91 98000 00123")).text
    r = await cmd.handle_text(alice.id, "refund kisko call karun")
    assert "+919800000123" in r.text and "aapne diya" in r.text


async def test_mute_commands(cmd, svc, alice, sender, clock):
    await svc.open_by_user(alice.id, "Exampleair")
    await cmd.handle_text(alice.id, "refund mute")
    clock.set(at(12, 10))
    assert await svc.run_user(alice.id) == []
    await cmd.handle_text(alice.id, "refund unmute")
    assert len(await svc.run_user(alice.id)) == 1


async def test_things_that_are_not_refund_commands_are_left_alone(cmd, alice):
    for text in ("hi", "book a table", "trip plan", "mera order kahan hai", "paisa aa gaya", ""):
        assert await cmd.handle_text(alice.id, text) is None


async def test_commands_do_nothing_when_disabled(settings, store, clock, alice):
    from friday.refunds.service import RefundService

    c = RefundCommands(RefundService(settings, store, clock))
    assert await c.handle_text(alice.id, "Exampleair ka refund nahi aaya") is None
    assert await c.handle_button(alice.id, "refund:x:yes") is None


async def test_buttons(cmd, svc, alice):
    case = await svc.propose_from_trip_cancellation(alice.id, "leg1", "Exampleair")
    assert "track kar rahi" in (await cmd.handle_button(alice.id, f"refund:{case.id}:yes")).text
    assert "Kitna aaya" in (await cmd.handle_button(alice.id, f"refund:{case.id}:recd")).text
    assert "phir poochungi" in (await cmd.handle_button(alice.id, f"refund:{case.id}:notyet")).text
    await cmd.handle_button(alice.id, f"refund:{case.id}:asked")
    assert (await svc.store.get_case(alice.id, case.id)).state == S.REQUESTED
    assert await cmd.handle_button(alice.id, "trip:1:ok:2") is None
    assert await cmd.handle_button(alice.id, f"refund:{case.id}:bogus") is None
    assert "nahi mila" in (await cmd.handle_button(alice.id, "refund:nope:yes")).text


# ------------------------------------------------------------------ the trip hook
def trip_service(settings, clock, refunds, *, status=None):
    s = settings.model_copy(update={"trips_enabled": True, "trip_flight_watch_enabled": True})
    docs = MemoryDocStore()
    sender = FakeTripSender()
    status = status or FakeFlightStatus(clock)
    return TripService(s, MemoryTripStore(), clock, docs=docs, sender=sender, status=status, refunds=refunds), docs, status, sender


async def test_a_cancelled_flight_proposes_a_refund_case_and_waits_for_the_user(
    rsettings, svc, clock, alice, sender
):
    trips, docs, status, tsender = trip_service(rsettings, clock, svc)
    await docs.save(make_doc(alice.id, DocType.FLIGHT, FLIGHT_OUT))
    await trips.create_from_documents(alice.id)
    status.script("EX101", Scripted(status="cancelled"))
    clock.set(at(13, 7, 0))
    await trips.run_user(alice.id)
    assert "cancel" in tsender.texts(alice.id)[0]
    (case,) = await svc.store.list_cases(alice.id)
    assert (case.state, case.origin) == (S.SUSPECTED, Origin.TRIP_LEG)
    assert case.vendor_name == "Exampleair" and case.origin_ref  # no flight number in the name
    assert sender.sent == []  # proposing sent nothing; the reminder tick asks
    clock.set(at(13, 10, 0))  # (07:00 is quiet hours)
    out = await svc.run_user(alice.id)
    assert out[0].stage == "suspect_ask" and out[0].action == "sent"
    assert "Exampleair" in sender.texts(alice.id)[0]
    assert [b.id.split(":")[-1] for b in sender.sent[0][1].buttons] == ["yes", "no"]
    # and the same cancellation seen again does not make a second case
    await trips.run_user(alice.id)
    assert len(await svc.store.list_cases(alice.id)) == 1


async def test_trips_without_a_refund_tracker_are_unchanged(rsettings, clock, alice):
    trips, docs, status, tsender = trip_service(rsettings, clock, None)
    await docs.save(make_doc(alice.id, DocType.FLIGHT, FLIGHT_OUT))
    await trips.create_from_documents(alice.id)
    status.script("EX101", Scripted(status="cancelled"))
    clock.set(at(13, 7, 0))
    await trips.run_user(alice.id)
    assert "cancel" in tsender.texts(alice.id)[0]


async def test_a_refund_tracker_failure_does_not_break_the_trip_message(rsettings, clock, alice):
    class Broken:
        async def propose_from_trip_cancellation(self, *a, **k):
            raise RuntimeError("db down")

    trips, docs, status, tsender = trip_service(rsettings, clock, Broken())
    await docs.save(make_doc(alice.id, DocType.FLIGHT, FLIGHT_OUT))
    await trips.create_from_documents(alice.id)
    status.script("EX101", Scripted(status="cancelled"))
    clock.set(at(13, 7, 0))
    await trips.run_user(alice.id)
    assert "cancel" in tsender.texts(alice.id)[0]


async def test_refunds_off_means_the_hook_makes_no_case(settings, store, clock, alice):
    from friday.refunds.service import RefundService

    off = RefundService(settings, store, clock)  # switch default OFF
    trips, docs, status, tsender = trip_service(settings, clock, off)
    await docs.save(make_doc(alice.id, DocType.FLIGHT, FLIGHT_OUT))
    await trips.create_from_documents(alice.id)
    status.script("EX101", Scripted(status="cancelled"))
    clock.set(at(13, 7, 0))
    await trips.run_user(alice.id)
    assert await store.list_cases(alice.id) == []
    assert IST  # (the zone import is used by the fixtures above)
