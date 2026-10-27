# ruff: noqa: E501
"""Every category end to end through BrowserFlow (planner -> questions -> approval -> login -> payment)
on the FAKE sites of every package, plus the category-specific rules (waitlist phrase, foreign
currency, sold-out substitute, captcha hand-over, ride start code, read-only info)."""

from __future__ import annotations

import dataclasses

import pytest

from friday.connectors.sites import categories
from friday.connectors.sites import category_sim as cs

CASES = cs.cases()
PARAMS = [(k, m) for k, c in CASES.items() for m in c.modes]


def test_every_fake_site_has_a_case_and_every_catalog_use_case_is_covered():
    assert set(CASES) == set(categories.all_fake_sites())
    have = {k.split(".", 1)[1] for k in CASES}
    assert {"grocery", "ride", "hotel", "flight", "bus", "train", "train_info", "shopping", "food"} <= have
    assert not categories.missing_packages() and not categories.failed_packages()
    assert len(CASES) >= 24


@pytest.mark.parametrize("key,mode", PARAMS, ids=[f"{k}:{m}" for k, m in PARAMS])
async def test_site_flow(key, mode):
    r = await cs.run_case(CASES[key], mode)
    assert r.ok(), (r.problems(), [(m.kind, m.text[:120]) for m in r.messages])
    blob = " ".join(m.text for m in r.messages) + (r.task.model_dump_json() if r.task else "")
    assert "scam@" not in blob and "Fake-Pw-7Qz" not in blob


@pytest.mark.parametrize("key", ["blinkit.grocery", "uber.ride", "makemytrip.hotel", "redbus.bus",
                                 "irctc.train", "amazon.shopping", "swiggy.food"])
async def test_hinglish_run_reaches_the_same_end(key):
    r = await cs.run_case(CASES[key], "happy", "hi")
    assert r.phase == "done", [(m.kind, m.text[:100]) for m in r.messages]


@pytest.mark.parametrize("key", [k for k, c in CASES.items() if "price_rise" in c.modes])
async def test_price_rise_after_approval_asks_again_never_silently_goes_on(key):
    r = await cs.run_case(CASES[key], "price_rise")
    cards = r.cards
    assert len(cards) == 2 and r.task.reapprovals >= 1
    assert "approved up to" in cards[1].text


# ---------------------------------------------------------------- category rules
async def test_waitlisted_train_needs_the_exact_phrase_and_a_yes_is_not_enough():
    case = dataclasses.replace(CASES["ixigo.train"], answers={**CASES["ixigo.train"].answers, "train": "12952"})
    seen = {}

    def hook(flow):
        seen["flow"] = flow

    r = await cs.run_case(case, "happy", flow_hook=hook)
    # the harness pressed Yes once: Friday must now be waiting for the phrase, nothing booked
    assert r.phase == "await_approval" and r.task.notes.get("await_phrase")
    assert "WAITLIST OK" in r.messages[-1].text and "payment" not in r.kinds
    flow = seen["flow"]
    await flow.handle_text(cs.USER, "yes")  # not the phrase
    await flow.idle()
    assert flow._store.active(cs.USER).phase.value == "await_approval"  # noqa: SLF001
    await flow.handle_text(cs.USER, "waitlist ok")
    await flow.idle()
    st = flow._store.active(cs.USER)  # noqa: SLF001
    assert st.phase.value == "await_payment" and st.proposal.details["extra_approval_given"] is True


async def test_foreign_currency_ends_with_the_link_before_anything_is_clicked():
    case = dataclasses.replace(CASES["booking.hotel"], knobs={"currency": "USD"})
    r = await cs.run_case(case, "happy")
    assert r.phase == "failed" and r.kinds[-1] == "outcome" and "booking.com" in r.messages[-1].text
    assert "approval" not in r.kinds and "payment" not in r.kinds


def _butter_planner(flow):
    """The rule planner does not read brands; give the flow a plan that carries one."""
    from friday.connectors.sites.planner import Plan

    class P:
        async def plan(self, text):
            return Plan(connector="blinkit.grocery", site="blinkit", use_case="grocery", slots={
                "items": [{"query": "butter", "qty": 1, "brand": "golden churn"}]})

    flow._planner = P()  # noqa: SLF001
    return flow


async def _sold_out_run():
    case = dataclasses.replace(CASES["blinkit.grocery"], knobs={"sold_out": {"butter"}})
    seen = {}

    def hook(f):
        seen["flow"] = _butter_planner(f)

    return await cs.run_case(case, "happy", flow_hook=hook), seen["flow"]


async def test_sold_out_grocery_item_asks_before_substituting():
    r, flow = await _sold_out_run()
    assert r.phase == "clarify" and r.task.pending_slot == "substitute"
    assert "out of stock" in r.messages[-1].text.lower() and "Meadow" in r.messages[-1].text
    assert "approval" not in r.kinds and "payment" not in r.kinds
    await flow.handle_text(cs.USER, "meadow")  # the user picks the offered alternative
    await flow.idle()
    st = flow._store.active(cs.USER)  # noqa: SLF001
    assert st.phase.value == "await_approval" and "_sub" not in st.slots
    assert "Meadow" in st.proposal.lines[0]  # a different product, only because the user chose it


async def test_sold_out_skip_asks_what_to_order_instead_of_buying_something_else():
    r, flow = await _sold_out_run()
    await flow.handle_text(cs.USER, "skip it")
    await flow.idle()
    st = flow._store.active(cs.USER)  # noqa: SLF001
    assert st.phase.value == "clarify" and st.pending_slot == "items" and r.kinds.count("approval") == 0


async def test_captcha_on_any_category_stops_with_the_link_and_no_retry():
    for key, knob in (("zepto.grocery", {"block": "captcha"}), ("uber.ride", {"block": "captcha"}),
                      ("redbus.bus", {"block": "captcha"})):
        r = await cs.run_case(dataclasses.replace(CASES[key], knobs=knob), "happy")
        assert r.phase == "failed" and "payment" not in r.kinds, key
        assert "human check" in r.messages[-1].text, (key, r.messages[-1].text)


async def test_ride_is_booked_without_payment_and_the_start_code_is_only_a_link():
    r = await cs.run_case(CASES["uber.ride"], "happy")
    assert r.phase == "done" and "payment" not in r.kinds
    last = r.messages[-1].text
    assert "ride-start code" in last.lower() or "code" in last.lower()
    assert "4821" not in " ".join(m.text for m in r.messages) + r.task.model_dump_json()
    assert "/ride/code/" in last


async def test_erail_is_read_only_no_approval_no_login_no_booking():
    r = await cs.run_case(CASES["erail.train_info"], "happy")
    assert r.phase == "done" and "approval" not in r.kinds and "payment" not in r.kinds
    assert not any("book_confirm" in c for s in r.provider.sessions for c in getattr(s, "calls", []))


async def test_unknown_or_uncleared_site_gets_a_link_not_a_task():
    # the production gate (catalog.effective_mode): nothing cleared -> link for every category
    from friday.connectors.flow import BrowserFlow

    msgs = []

    async def send(m):
        msgs.append(m)

    f = BrowserFlow(send=send, registry=cs.make_registry(), sessions=None, otp=None, profile=lambda u: cs.PROFILE,  # type: ignore[arg-type]
                    login_link=lambda t: "", base_urls={}, enabled=lambda: True, mode_of=lambda s: "deeplink")
    for text, host in (("Blinkit se doodh mangao", "blinkit.com"), ("Uber book karo airport", "uber.com"),
                       ("Delhi se Jaipur bus", "redbus.in"), ("Goa mein hotel", "makemytrip.com"),
                       ("Amazon se buds kharidna", "amazon.in"), ("irctc train NDLS se BCT", "irctc.co.in")):
        msgs.clear()
        assert await f.handle_text("u", text)
        assert [m.kind for m in msgs] == ["outcome"] and host in msgs[0].text, text
        assert f._store.active("u") is None  # noqa: SLF001
