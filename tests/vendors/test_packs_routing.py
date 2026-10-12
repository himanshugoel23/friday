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
    assert pack_for("cab").archetype == "rental"
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


def test_table_needs_party_size_and_date_else_normal_policy():
    kw = dict(
        task_type="booking", category="restaurant_banquet", goal="table", item="table",
        preferred_times=[], beneficiary_name=None, budget_max_inr=None,
        requester_name="Himanshu", business_name="Spice Garden", directory=PENDING_DIR,
    )
    assert playbook_fields(when_text="aaj raat 8 baje", constraints=[], **kw) == {}
    f = playbook_fields(when_text="aaj raat 8 baje", constraints=["party_size: 4"], **kw)
    assert f["playbook_inputs"]["party_size"] == "4"
    assert f["playbook_inputs"]["unit_phrase"] == "per head ka kharcha"
