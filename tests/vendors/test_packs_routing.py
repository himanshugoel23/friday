"""Category packs and routing of non-salon categories to archetype playbooks."""

from __future__ import annotations

from friday.playbooks.model import PENDING_DIR
from friday.playbooks.select import matching_playbook, playbook_fields
from friday.scouting.categories import CATEGORIES
from friday.vendors.packs import ARCHETYPES, PACKS, is_excluded, pack_for


def test_every_wave1_category_has_a_pack_and_a_known_archetype():
    assert set(PACKS) == set(CATEGORIES)
    for p in PACKS.values():
        assert p.archetype in (*ARCHETYPES, "salon_booking")
        if p.price_min is not None and p.price_max is not None:
            assert p.price_min < p.price_max


def test_pack_lookup_by_key_and_free_text_and_exclusions():
    assert pack_for("clinic").archetype == "quote_and_slot"
    assert pack_for("my AC repair guy").key == "appliance_repair"
    assert pack_for("cab").archetype == "cab_booking"
    assert pack_for("loan agent") is None and is_excluded("need a lawyer")
    assert pack_for("") is None and pack_for("zzz unknown") is None


def test_pending_playbooks_are_never_routed_in_production():
    # production data/ has no archetype playbook until the founder approves and promotes it
    assert matching_playbook("booking", "clinic", "get price", None) is None


def test_routing_fills_inputs_when_the_archetype_is_available():
    pb = matching_playbook("booking", "clinic", "fees", PENDING_DIR)
    assert pb is not None and pb.id == "quote_and_slot"
    f = playbook_fields(
        task_type="booking", category="clinic", goal="fees", item="skin consultation",
        when_text=None, preferred_times=[], beneficiary_name=None, constraints=["mode: quote_only"],
        budget_max_inr=None, requester_name="Himanshu Goel", business_name="Dr Sharma Clinic",
        directory=PENDING_DIR,
    )
    assert f["playbook"] == "quote_and_slot"
    inp = f["playbook_inputs"]
    assert inp["service"] == "skin consultation" and inp["category"] == "clinic"
    assert inp["price_min"] == "100" and inp["price_max"] == "3000"


def test_archetypes_per_category_and_switches():
    arch = {k: p.archetype for k, p in PACKS.items()}
    assert arch["pg_rental"] == "pg_rental" and arch["cab_travel"] == "cab_booking"
    assert arch["restaurant_table"] == "table_booking"
    assert arch["hotel_stay"] == "hotel_booking" and arch["banquet_hall"] == "banquet_booking"
    assert "restaurant_banquet" not in PACKS and len(PACKS) == 22
    assert not {"rental", "table_or_venue"} & set(ARCHETYPES)
    for k in ("electronics_dealer", "florist_gift"):
        assert arch[k] == "stock_and_price"
    for k in ("coaching_classes", "gym_yoga", "driving_school", "event_services",
              "wedding_vendors"):
        assert arch[k] == "enquiry"
    for k in ("clinic", "diagnostic_lab", "car_service", "vet_pet", "laundry_tailor"):
        assert arch[k] == "quote_and_slot"
    for k in ("appliance_repair", "home_repair", "packers_movers", "pest_control"):
        assert arch[k] == "home_service_visit" and PACKS[k].switches["q_visit"] == "yes"
    assert PACKS["restaurant_table"].switches["q_price"] == "no"
    assert PACKS["hotel_stay"].switches["q_price"] == "yes"
    assert PACKS["banquet_hall"].switches["q_price"] == "yes"
    assert PACKS["banquet_hall"].switches["q_visit"] == "yes"
    for k in ("event_services", "wedding_vendors"):
        assert PACKS[k].switches == {"q_date": "yes", "price_word": "charges"}
    for k in ("coaching_classes", "gym_yoga", "driving_school", "clinic", "vet_pet"):
        assert PACKS[k].switches["price_word"] == "fees"
    # the advance / exchange switches are never set by a pack (only by the user's own words)
    assert all("q_ask_advance" not in p.switches and "q_exchange" not in p.switches
               for p in PACKS.values())


def test_free_text_routes_the_three_split_categories():
    assert pack_for("hotel room booking").key == "hotel_stay"
    assert pack_for("marriage hall").key == "banquet_hall"
    assert pack_for("cafe").key == "restaurant_table"


def test_facts_travel_in_constraints_and_come_back():
    from friday.vendors.facts import fact_constraints, facts_from_constraints

    cons = fact_constraints({"event_date": "5 December", "guests": "200", "bogus": "x",
                             "event_city": "", "q_ask_advance": "yes"})
    assert cons == ["fact: event_date=5 December", "fact: guests=200", "fact: q_ask_advance=yes"]
    assert facts_from_constraints(["mode: quote_only", *cons, "fact: nope=1"]) == {
        "event_date": "5 December", "guests": "200", "q_ask_advance": "yes"}
