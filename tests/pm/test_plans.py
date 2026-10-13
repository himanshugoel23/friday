import pytest

from friday.pm.plans import build_template, message, slot_question
from friday.pm.taxonomy import bucket_keys, buckets, categories, category_keys

ARCH = ["quote", "availability", "book", "service_visit", "information"]


def test_taxonomy_matches_scouting_table():
    from friday.scouting.categories import CATEGORIES

    assert len(bucket_keys()) == 10 and len(category_keys()) == 22
    assert set(category_keys()) == set(CATEGORIES)


@pytest.mark.parametrize("cat", category_keys())
@pytest.mark.parametrize("arch", ARCH)
def test_every_category_archetype_builds(cat, arch):
    t = build_template(arch, cat)
    assert t.radius_km <= t.hard_max_km
    assert t.radius_steps[0] == t.radius_km and t.radius_steps[-1] <= t.hard_max_km
    assert "report" in t.steps and t.required
    assert set(t.required).isdisjoint(t.optional)
    assert all(s in t.steps for s in ("locate", "search", "shortlist", "consent", "calls"))


def test_radii_match_roster():
    c = categories()
    assert (c["salon"].radius_km, c["salon"].hard_max_km) == (5, 10)
    assert (c["clinic"].radius_km, c["clinic"].hard_max_km) == (8, 15)
    assert (c["restaurant_table"].radius_km, c["restaurant_table"].hard_max_km) == (5, 12)
    assert (c["appliance_repair"].radius_km, c["appliance_repair"].hard_max_km) == (10, 20)
    assert (c["packers_movers"].radius_km, c["packers_movers"].hard_max_km) == (20, 40)
    assert (c["coaching_classes"].radius_km, c["coaching_classes"].hard_max_km) == (8, 15)


def test_overrides_and_archetypes():
    assert "details" in build_template("quote", "pest_control").required
    assert "people_count" in build_template("book", "restaurant_table").required
    assert "details" not in build_template("book", "restaurant_table").required
    assert "details" not in build_template("quote", "salon").required
    assert "delegation" in build_template("book", "salon").required
    assert build_template("book", "salon").call_mode == "first_success"
    assert "reviews" not in build_template("information", "salon").steps
    assert build_template("service_visit", "home_repair").defaults["when"] == "today"
    assert build_template("quote", "salon").radius_steps == [5.0, 8.0, 10.0]


def test_buckets_map_to_archetypes():
    assert buckets()["book"].archetype == "book"
    assert buckets()["complaint"].archetype == "handoff"
    assert build_template("handoff").steps == []


def test_call_wording_is_short_and_chat_has_every_message():
    for slot in ("where", "service", "when", "budget", "for_whom", "delegation", "details"):
        for lang in ("en", "hinglish"):
            assert len(slot_question(slot, lang, None, "call")) <= 40
    assert message("ack", "en", "call") != message("ack", "en", "whatsapp_text")
