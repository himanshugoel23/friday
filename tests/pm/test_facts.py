# ruff: noqa: E501
"""Project-manager fact questions: ask only what the request lacks, one at a time."""

from friday.pm.classifier import KeywordClassifier
from friday.pm.factslots import export_facts
from friday.pm.manager import ProjectManager
from friday.pm.state import MemoryTaskStore
from friday.pm.steps import FakeStepAgents
from friday.pm.taxonomy import category_keys
from friday.quotes.calls import EngineVendorCalls
from friday.vendors.facts import FACTS, facts_from_constraints
from friday.vendors.packs import PACKS


class FixedClassifier(KeywordClassifier):
    def __init__(self, category, bucket="quote"):
        super().__init__()
        self.cat, self.bkt = category, bucket

    async def classify(self, text, channel="whatsapp_text"):
        from friday.pm.classifier import Classification

        return Classification(bucket=self.bkt, category=self.cat, confidence=0.95)


def pm_for(category, bucket="quote"):
    return ProjectManager(classifier=FixedClassifier(category, bucket), agents=FakeStepAgents(),
                          store=MemoryTaskStore(), id_factory=lambda: "t1")


async def run_dialog(category, first, answers, bucket="quote"):
    """Returns (asked slots in order, final task)."""
    pm = pm_for(category, bucket)
    await pm.handle_message(first, task_id=None)
    asked = []
    queue = list(answers) if not isinstance(answers, dict) else None
    for _ in range(30):
        t = pm.store.load("t1")
        if t.pending is None or t.pending.kind != "slot":
            break
        slot = t.pending.slot
        if queue is not None:
            if not queue:
                break
            a = queue.pop(0)
        elif slot in answers:
            a = answers[slot]
        elif slot in ("service", "where"):
            a = {"service": "service", "where": "Sector 45 Gurgaon"}[slot]
        else:
            break
        if slot not in ("service", "where"):
            asked.append(slot)
        await pm.handle_message(a, task_id="t1")
    t = pm.store.load("t1")
    if t.pending is not None and t.pending.kind == "slot" and t.pending.slot not in asked:
        asked.append(t.pending.slot)
    return asked, t


def test_split_categories_exist_and_total_is_22():
    keys = category_keys()
    assert len(keys) == 22 and "restaurant_banquet" not in keys
    assert {"restaurant_table", "hotel_stay", "banquet_hall"} <= set(keys)
    assert set(keys) == set(PACKS)


async def test_events_ask_type_date_venue_city_guests_unless_given():
    asked, t = await run_dialog(
        "event_services", "DJ chahiye Sector 45 Gurgaon mein, 200 guests, 5 December",
        ["shaadi", "Taj Banquet", "Gurgaon"])
    assert t.slots["guests"] == "200" and t.slots["event_date"] == "5 december"
    assert asked == ["event_type", "event_venue", "event_city"]
    f = export_facts(t.slots)
    assert f["event_type"] == "shaadi" and f["event_city"] == "Gurgaon" and f["guests"] == "200"


async def test_salon_plain_haircut_asks_no_venue_question():
    asked, t = await run_dialog("salon", "haircut kitna lega Sector 45 Gurgaon", [])
    assert "at_venue" not in asked and t.slots["at_venue"] is False
    assert not any(s in asked for s in ("event_type", "event_venue", "people_count"))


async def test_makeup_at_venue_gate_then_event_questions():
    asked, t = await run_dialog(
        "salon", "bridal makeup chahiye Sector 45 Gurgaon", {
            "at_venue": "venue par aayegi", "event_type": "shaadi", "event_date": "5 December",
            "event_venue": "Hotel Leela", "event_city": "Gurgaon", "people_count": "3"})
    assert asked[0] == "at_venue" and t.slots["at_venue"] is True
    assert asked[1:] == ["event_type", "event_date", "event_venue", "event_city", "people_count"]
    assert t.slots["people_count"] == "3"


async def test_makeup_at_parlour_skips_the_event_questions():
    asked, t = await run_dialog("salon", "bridal makeup chahiye Sector 45 Gurgaon", ["parlour jaungi"])
    assert asked == ["at_venue"] and t.slots["at_venue"] is False
    assert "event_venue" not in asked


async def test_electronics_exchange_followups_only_if_yes():
    asked, t = await run_dialog(
        "electronics_dealer", "iPhone 15 ka price Sector 45 Gurgaon", ["haan", "iPhone 11", "2021", "chal raha hai"])
    assert asked[0] == "exchange" and asked[1:] == ["old_phone_model", "old_phone_year", "old_phone_condition"]
    assert export_facts(t.slots)["q_exchange"] == "yes"
    asked, t = await run_dialog("electronics_dealer", "iPhone 15 ka price Sector 45 Gurgaon", ["nahi"])
    assert asked == ["exchange"] and "q_exchange" not in export_facts(t.slots)


async def test_restaurant_table_date_time_people_and_no_price_or_amount_question():
    asked, t = await run_dialog(
        "restaurant_table", "table book karna hai restaurant Sector 45 Gurgaon", ["kal", "8 baje", "4"],
        bucket="book")
    assert asked[:3] == ["date", "time", "people_count"]
    assert "budget" not in asked and "q_ask_advance" not in t.slots


async def test_advance_is_asked_about_only_when_the_user_mentions_it():
    _, t = await run_dialog("banquet_hall", "banquet hall chahiye Sector 45 Gurgaon, advance kitna hoga bhi pooch lena", [])
    assert t.slots["q_ask_advance"] == "yes"
    assert export_facts(t.slots)["q_ask_advance"] == "yes"


async def test_hotel_optional_questions_can_be_skipped():
    asked, t = await run_dialog(
        "hotel_stay", "hotel room chahiye Jaipur", {
            "checkin_date": "20 December", "checkout_date": "22 December", "guests": "2",
            "room_count": "1", "room_type": "skip", "budget": "skip"})
    assert asked[:4] == ["checkin_date", "checkout_date", "guests", "room_count"]
    assert "room_type" in asked and "budget" in asked
    assert "room_type" not in t.slots and "budget" not in t.slots
    assert t.pending is None or t.pending.slot not in ("room_type", "budget")


async def test_banquet_asks_type_date_guests_veg_then_optional_rooms_and_extras():
    asked, t = await run_dialog(
        "banquet_hall", "banquet hall chahiye Sector 45 Gurgaon", ["birthday", "10 March", "80", "veg", "skip", "DJ"])
    assert asked == ["event_type", "event_date", "guests", "veg_nonveg", "rooms_needed", "extras_needed"]
    f = export_facts(t.slots)
    assert f["extras_needed"] == "DJ" and "rooms_needed" not in f


async def test_packers_pg_cab_florist_question_lists():
    asked, _ = await run_dialog("packers_movers", "packers chahiye Dwarka mein", ["2 BHK saaman", "Noida", "3rd floor lift hai", "kal"])
    assert asked[:4] == ["items_description", "to_place", "floor_info", "date"]
    asked, _ = await run_dialog("pg_rental", "PG chahiye Sector 45 Gurgaon", ["girls pg", "single", "1 January", "Riya", "Delhi", "Infosys", "Delhi", "skip"])
    assert asked[:6] == ["sharing_type", "move_in_date", "occupant_name", "occupant_from", "occupant_job", "occupant_location"]
    asked, _ = await run_dialog("cab_travel", "cab chahiye", ["Dwarka", "airport", "kal subah 6 baje", "3", "2 bags", "one way"])
    assert asked[:6] == ["from_place", "to_place", "pickup_time", "people_count", "luggage", "trip_type"]
    asked, _ = await run_dialog("florist_gift", "bouquet chahiye Sector 45 Gurgaon", ["Sector 50", "kal"])
    assert set(asked[:2]) == {"delivery_area", "date"}


async def test_every_fact_slot_is_a_known_fact_or_gate():
    from friday.pm.plans import fact_slots

    gates = {"at_venue", "exchange"}
    assert fact_slots() - gates <= set(FACTS)


def test_facts_reach_the_task_constraints_of_the_call():
    from types import SimpleNamespace

    from friday.core.models import Delegation
    from friday.quotes.models import Conv, Vendor

    conv = Conv(user_id="u", category="banquet_hall")
    conv.extra["facts"] = export_facts({"event_date": "10 March", "guests": "80", "q_ask_advance": "yes", "at_venue": True})
    v = Vendor(place_id="p", name="Grand Hall", phone="+911234567890")
    spec = EngineVendorCalls(SimpleNamespace(), None)._spec(
        conv, v, book=False, when_text=None, ceiling=None, delegation=Delegation())
    assert facts_from_constraints(spec.constraints) == {
        "event_date": "10 March", "guests": "80", "q_ask_advance": "yes"}
    assert "mode: quote_only" in spec.constraints
