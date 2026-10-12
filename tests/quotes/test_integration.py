# ruff: noqa: E501
"""The flow on the REAL task engine, playbook and simulated telephony/directory/geocoder
(no network, no keys), including the test redirect and the pilot allow-list."""

from __future__ import annotations

import pytest

from friday.core.models import TaskStatus
from friday.quotes.models import State
from tests.e2e.harness import Friday
from tests.quotes.conftest import make_user
from tests.quotes.test_flow import conv_of

FOUNDER = "+918607549916"
GURGAON_VENDORS = {"+911245000001", "+911245000002", "+911245000004", "+911245000006"}


class Spy:
    def __init__(self) -> None:
        self.dialled: list[str] = []
        self.briefs: list = []


async def start_real(tmp_path, **settings):
    f = await Friday.start(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/i.db", media_dir=str(tmp_path / "m"),
        quotes_flow_enabled=True, playbooks_enabled=True, **settings,
    )
    spy = Spy()
    tel = f.c.telephony
    orig = tel.place_call

    async def place_call(req):
        spy.dialled.append(req.to_phone)
        return await orig(req)

    tel.place_call = place_call
    runner = f.c.call_runner
    orun = runner.run

    async def run(brief, *a, **k):
        spy.briefs.append(brief)
        return await orun(brief, *a, **k)

    runner.run = run
    f.flow = f.rt.pipeline.quotes
    return f, spy


@pytest.fixture
async def real(tmp_path):
    f, spy = await start_real(tmp_path)
    user = await make_user(f)
    yield f, spy, user
    await f.close()


REQ = "haircut kal 6 baje Sector 56 Gurgaon mein chahiye parlour"


async def test_real_engine_quote_only_then_booking(real):
    f, spy, rahul = real
    out = await rahul.say(REQ)
    assert "jagah mili" in out[-1]
    await rahul.tap("Haan")
    await f.settle()
    assert len(spy.dialled) == 3 and set(spy.dialled) <= GURGAON_VENDORS
    assert all(b.playbook == "salon_booking" for b in spy.briefs)
    assert all(b.playbook_inputs["playbook_mode"] == "quote_only" for b in spy.briefs)
    assert not any(b.delegation.granted for b in spy.briefs)  # a price check cannot book
    text = rahul.last()
    assert text.startswith("haircut ke quotes (kal shaam 6 baje):") and "Rs " in text
    tasks = [t for t in await rahul.tasks() if t.role == "vendor_quote"]
    assert len(tasks) == 3 and all(t.status == TaskStatus.COMPLETED for t in tasks)
    assert (await conv_of(f)).state == State.AWAITING_BOOK
    # no per-call chatter: the searching ack, the shortlist question, the quotes
    assert len(rahul.msgs()) == 3

    first_book = next(b for b in rahul.last_msg().buttons if b.id.split(":")[2] == "book")
    await rahul.tap_id(first_book.id)
    await f.settle()
    booking = [t for t in await rahul.tasks() if t.delegation.granted]
    assert len(booking) == 1
    b = booking[0]
    assert b.delegation.max_price_inr and b.spec.business_phone in GURGAON_VENDORS
    assert b.delegation.window_start and b.delegation.window_end  # this time only
    assert spy.briefs[-1].playbook_inputs["playbook_mode"] == "book"
    assert rahul.last().startswith(("Booking pakki", "Glow Unisex Salon mein booking nahi",
                                    "Royal Cuts Salon mein booking nahi",
                                    "Trendz Hair Studio mein booking nahi"))


async def test_redirect_mode_dials_only_the_test_number(tmp_path):
    f, spy = await start_real(tmp_path, vendor_call_redirect_to=FOUNDER)
    try:
        rahul = await make_user(f)
        await rahul.say(REQ)
        await rahul.tap("Haan")
        await f.settle()
        assert spy.dialled and set(spy.dialled) == {FOUNDER}  # never a vendor number
        assert not (set(spy.dialled) & GURGAON_VENDORS)
        names = {b.target.name for b in spy.briefs}
        assert names <= {"Glow Unisex Salon", "Royal Cuts Salon", "Trendz Hair Studio"} and names
        for b in spy.briefs:  # the script still speaks the real vendor's name
            assert b.playbook_inputs["business_name"] == b.target.name
            assert b.target.phone == FOUNDER
        # records stay keyed by the real vendor number, and the user still gets one message
        calls = [c for t in await rahul.tasks() for c in await rahul.calls(t)]
        assert calls and all(c.to_phone in GURGAON_VENDORS for c in calls)
        assert rahul.last()
        audit = await f.c.repos.audit.list_for_user((await rahul.user_row()).id) \
            if hasattr(f.c.repos.audit, "list_for_user") else None
        _ = audit
    finally:
        await f.close()


async def test_redirect_empty_by_default_and_normalised():
    from friday.core.config import Settings

    assert Settings(_env_file=None).vendor_call_redirect_to is None
    assert Settings(_env_file=None, vendor_call_redirect_to="").vendor_call_redirect_to is None
    s = Settings(_env_file=None, vendor_call_redirect_to="86075 49916")
    assert s.vendor_call_redirect_to == FOUNDER
    assert s.vendor_dial_number("+911245000001") == FOUNDER
    assert Settings(_env_file=None).vendor_dial_number("+911245000001") == "+911245000001"


async def test_allow_list_refuses_real_vendor_numbers(tmp_path):
    f, spy = await start_real(tmp_path, pilot_block_business_calls=True,
                              pilot_allowed_numbers=[FOUNDER])
    try:
        rahul = await make_user(f)
        await rahul.say(REQ)
        out = await rahul.tap("Haan")
        assert out == ["Test mode mein asli jagah ko call nahi kar sakti. Kisi ko call nahi gaya."]
        await f.settle()
        assert spy.dialled == []
    finally:
        await f.close()


async def test_allow_list_with_redirect_to_a_listed_number_works(tmp_path):
    f, spy = await start_real(tmp_path, pilot_block_business_calls=True,
                              pilot_allowed_numbers=[FOUNDER], vendor_call_redirect_to=FOUNDER)
    try:
        rahul = await make_user(f)
        await rahul.say(REQ)
        await rahul.tap("Haan")
        await f.settle()
        assert spy.dialled and set(spy.dialled) == {FOUNDER}
    finally:
        await f.close()


async def test_allow_list_refuses_a_redirect_to_an_unlisted_number(tmp_path):
    f, spy = await start_real(tmp_path, pilot_block_business_calls=True,
                              pilot_allowed_numbers=[FOUNDER], vendor_call_redirect_to="+919999999999")
    try:
        rahul = await make_user(f)
        await rahul.say(REQ)
        await rahul.tap("Haan")
        await f.settle()
        assert spy.dialled == []
    finally:
        await f.close()


async def test_dnc_vendor_is_never_shown_or_called(tmp_path):
    f, spy = await start_real(tmp_path)
    try:
        await f.c.number_pool.block("+911245000001", "dnc_request")
        rahul = await make_user(f)
        out = await rahul.say(REQ)
        assert "Glow Unisex Salon" not in out[-1]
        await rahul.tap("Haan")
        await f.settle()
        assert "+911245000001" not in spy.dialled
    finally:
        await f.close()


async def test_bangalore_request_uses_bangalore_vendors(real):
    f, spy, rahul = real
    out = await rahul.say("haircut kal shaam parlour Indiranagar Bangalore")
    assert "Looks Unisex Salon" in out[-1]
    assert (await conv_of(f)).slots.location.city == "bangalore"
