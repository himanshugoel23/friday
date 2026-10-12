"""Generic-type trades are accepted by name (Google gives them only the type "service")."""

from friday.core.models import BusinessCandidate
from friday.scouting.categories import get_category
from friday.scouting.eligibility import _type_ok
from friday.scouting.models import ScoutPlace


def place(name, types):
    c = BusinessCandidate(provider="g", place_id="x", name=name, phone="+911245000000")
    return ScoutPlace(candidate=c, types=types)


def test_generic_service_type_needs_a_name_hint():
    cat = get_category("pest_control")
    assert _type_ok(place("Sharma Pest Control", ["service"]), cat)
    assert not _type_ok(place("Sharma Sweets", ["service"]), cat)


def test_specific_type_still_passes_without_name_hint():
    assert _type_ok(place("Fixit", ["electrician", "service"]), get_category("appliance_repair"))
    assert not _type_ok(place("Bright Minds", ["school"]), get_category("pest_control"))
