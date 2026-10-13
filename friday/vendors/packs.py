"""Category packs: NO spoken words here, only data that picks the archetype playbook and fills its
inputs (price sanity range, fee unit, question switches). The words live in the playbooks
(friday/playbooks/pending/<archetype>.yaml, one place to edit: docs/CALL_SCRIPTS_EDIT_HERE.md).

Categories follow ``friday.scouting.categories.CATEGORIES`` (docs/SCOPE_BUCKETS.md). Medical
categories only ever ask for fees and availability. Excluded categories (emergency, adult, loans /
insurance cold-sell, legal) have no pack, so no call is ever routed for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ARCHETYPES = (
    "quote_and_slot", "stock_and_price", "home_service_visit", "enquiry", "pg_rental",
    "cab_booking", "table_booking", "hotel_booking", "banquet_booking",
)
EXCLUDED_WORDS = (
    "emergency", "ambulance", "escort", "adult", "loan", "insurance", "lawyer", "legal", "advocate",
    "court", "police",
)


@dataclass(frozen=True)
class Pack:
    key: str  # scouting category key
    archetype: str  # playbook id, or "salon_booking" (live, already approved)
    default_service: str
    price_min: int | None = None
    price_max: int | None = None
    unit_phrase: str = ""  # fee unit, only for archetypes that need it
    estimate_max: int | None = None
    keywords: tuple[str, ...] = ()  # matched against the task category/goal text
    switches: dict[str, str] = field(default_factory=dict)  # q_* question switches


def _p(key, archetype, service, lo, hi, *, unit="", est=None, kw=(), **switches) -> Pack:
    return Pack(key, archetype, service, lo, hi, unit, est, tuple(kw), dict(switches))


PACKS: dict[str, Pack] = {
    p.key: p
    for p in [
        _p("salon", "salon_booking", "haircut", 50, 15000,
           kw=("salon", "parlour", "parlor", "barber", "beauty", "spa")),
        _p("clinic", "quote_and_slot", "consultation", 100, 3000,
           price_word="fees", q_appointment="yes",
           kw=("clinic", "doctor", "dentist", "physio", "dermat", "paediatric", "gynae")),
        _p("diagnostic_lab", "quote_and_slot", "blood test", 50, 15000,
           kw=("lab", "diagnostic", "pathology", "scan", "mri", "x-ray", "xray")),
        _p("appliance_repair", "home_service_visit", "repair", 100, 1000, est=15000, q_visit="yes",
           kw=("appliance", "ac repair", "ac service", "fridge", "washing machine", "geyser",
               "tv repair", "microwave")),
        _p("home_repair", "home_service_visit", "repair", 100, 1000, est=30000, q_visit="yes",
           kw=("plumber", "electrician", "carpenter", "painter", "home repair", "handyman",
               "carpentry")),
        _p("packers_movers", "home_service_visit", "shifting", 0, 2000, est=150000, q_visit="yes",
           kw=("packers", "movers", "shifting", "relocation")),
        _p("pest_control", "home_service_visit", "pest control", 0, 1500, est=15000, q_visit="yes",
           kw=("pest", "termite", "cockroach", "bedbug")),
        _p("car_service", "quote_and_slot", "car service", 200, 40000,
           kw=("car service", "car wash", "garage", "mechanic", "bike service", "denting")),
        _p("restaurant_table", "table_booking", "table", 100, 6000,
           unit="per head ka kharcha", q_price="no",
           kw=("restaurant", "cafe", "dining", "table")),
        _p("hotel_stay", "hotel_booking", "room", 500, 100000, unit="ek raat ka rate",
           q_price="yes", kw=("hotel", "resort", "homestay", "room booking", "stay")),
        _p("banquet_hall", "banquet_booking", "banquet hall", 5000, 3000000,
           unit="ek event ka charge", q_price="yes", q_visit="yes",
           kw=("banquet", "party hall", "function hall", "marriage hall")),
        _p("coaching_classes", "enquiry", "classes", 500, 200000, price_word="fees",
           kw=("coaching", "tuition", "tutor", "classes", "institute")),
        _p("pg_rental", "pg_rental", "PG room", 2000, 60000, unit="ek mahine ka kiraya",
           kw=("pg", "hostel", "paying guest", "flat rent", "room rent")),
        _p("electronics_dealer", "stock_and_price", "mobile", 200, 500000,
           kw=("electronics", "mobile shop", "laptop", "dealer", "showroom")),
        _p("gym_yoga", "enquiry", "membership", 300, 100000, price_word="fees",
           kw=("gym", "yoga", "fitness", "zumba", "pilates")),
        _p("event_services", "enquiry", "event", 1000, 2000000, q_date="yes",
           price_word="charges",
           kw=("event", "decorator", "dj", "catering", "photographer", "tent")),
        _p("vet_pet", "quote_and_slot", "consultation", 100, 20000,
           price_word="fees",
           kw=("vet", "pet", "dog", "cat grooming")),
        _p("wedding_vendors", "enquiry", "wedding", 5000, 5000000, q_date="yes",
           price_word="charges",
           kw=("wedding", "mehendi", "makeup artist", "bridal", "pandit")),
        _p("driving_school", "enquiry", "driving classes", 1000, 30000, price_word="fees",
           kw=("driving school", "driving class", "learn driving")),
        _p("cab_travel", "cab_booking", "cab", 5, 100, unit="per km ka rate",
           kw=("cab", "taxi", "travel", "tempo traveller", "car rental", "driver")),
        _p("laundry_tailor", "quote_and_slot", "laundry", 20, 5000,
           kw=("laundry", "dry clean", "tailor", "stitching", "alteration")),
        _p("florist_gift", "stock_and_price", "bouquet", 100, 30000,
           kw=("florist", "flower", "bouquet", "gift", "cake", "bakery")),
    ]
}


def is_excluded(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in EXCLUDED_WORDS)


def pack_for(text: str | None) -> Pack | None:
    """The pack for a category key or free text ("clinic"); None if none or excluded."""
    t = (text or "").lower().strip()
    if not t or is_excluded(t):
        return None
    if t in PACKS:
        return PACKS[t]
    best: tuple[int, Pack] | None = None
    for p in PACKS.values():
        for k in p.keywords:
            if k in t and (best is None or len(k) > best[0]):
                best = (len(k), p)
    return best[1] if best else None
