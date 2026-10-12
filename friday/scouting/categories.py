"""Category table for the 20 Wave 1 categories (docs/SCOPE_BUCKETS.md).

``queries``: Places text-search phrasings (English first, then Hinglish/Indian usage); the
query builder uses the first few. ``expected_types``: Google Places (New) type names we
HOPE the place carries; they are hypotheses that ``friday scout-report`` measures against
live data. ``services``: service key -> synonyms (EN/Hinglish, lowercase) used to match the
user's request and to find evidence in reviews. Pure data + tiny helpers.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    queries: list[str]
    expected_types: list[str]
    services: dict[str, list[str]] = Field(default_factory=dict)
    home_visit: bool = False  # vendor usually comes to the customer
    default_radius_km: float = (
        5.0  # nothing beyond this is ranked best (AGENT_ROSTER distance rule)
    )
    max_radius_km: float = 10.0  # hard cap: never shown beyond this, even if the caller widens
    # Google gives some trades only the generic type "service": accept those when the NAME says it
    name_keywords: list[str] = Field(default_factory=list)


def _c(key, label, queries, types, services, home_visit=False) -> Category:
    return Category(
        key=key,
        label=label,
        queries=queries,
        expected_types=types,
        services=services,
        home_visit=home_visit,
    )


CATEGORIES: dict[str, Category] = {
    c.key: c
    for c in [
        _c(
            "salon",
            "Salon / parlour / spa",
            ["salon", "beauty parlour", "hair salon", "parlour", "gents salon", "ladies parlour"],
            ["beauty_salon", "hair_salon", "hair_care", "spa", "barber_shop"],
            {
                "haircut": ["haircut", "hair cut", "cutting", "trim", "baal kat", "hair style"],
                "beard": ["beard", "shave", "shaving", "dadhi", "daadhi"],
                "facial": ["facial", "cleanup", "clean up", "face clean"],
                "waxing": ["wax", "waxing"],
                "hair_colour": ["colour", "color", "dye", "highlights", "balayage"],
                "hair_treatment": ["keratin", "smoothening", "rebonding", "hair spa"],
                "threading": ["threading", "eyebrow"],
                "mani_pedi": ["manicure", "pedicure"],
                "massage": ["massage", "champi", "head massage", "body spa"],
                "bridal_makeup": ["bridal", "makeup", "make up"],
            },
        ),
        _c(
            "clinic",
            "Doctors / dentists / clinics",
            ["clinic", "doctor", "dentist", "skin specialist", "dermatologist", "dant ka doctor"],
            [
                "doctor",
                "dentist",
                "dental_clinic",
                "medical_clinic",
                "skin_care_clinic",
                "health",
                "hospital",
            ],
            {
                "consultation": ["consultation", "checkup", "check up", "appointment", "consult"],
                "dental": ["dental", "teeth", "tooth", "root canal", "cleaning", "braces"],
                "skin": ["skin", "acne", "pimple", "hair fall", "dermatolog"],
                "ent": ["ent", "ear", "throat", "nose"],
                "paediatric": ["child", "kids", "pediatric", "paediatric", "baby"],
            },
        ),
        _c(
            "diagnostic_lab",
            "Diagnostic labs",
            ["diagnostic lab", "pathology lab", "blood test lab", "lab near me", "test lab"],
            ["medical_lab", "doctor", "health"],
            {
                "blood_test": ["blood test", "cbc", "sugar", "thyroid", "lipid", "vitamin"],
                "home_collection": ["home collection", "sample collection", "home visit", "ghar"],
                "scan": ["x-ray", "xray", "ultrasound", "mri", "ct scan", "ecg"],
                "full_body_checkup": ["full body", "health package", "checkup package"],
            },
            home_visit=True,
        ),
        _c(
            "appliance_repair",
            "AC / appliance repair",
            [
                "ac repair",
                "appliance repair",
                "washing machine repair",
                "fridge repair",
                "ac service",
                "ac mechanic",
            ],
            [
                "electronics_store",
                "home_appliance_repair_service",
                "air_conditioning_contractor",
                "hvac_contractor",
                "store",
            ],
            {
                "ac_service": ["ac service", "ac repair", "ac gas", "air conditioner", "split ac"],
                "washing_machine": ["washing machine", "washer"],
                "refrigerator": ["fridge", "refrigerator"],
                "tv": ["tv repair", "television", "led tv"],
                "geyser": ["geyser", "water heater"],
                "microwave": ["microwave", "oven"],
            },
            home_visit=True,
        ),
        _c(
            "home_repair",
            "Plumber / electrician / carpenter",
            [
                "plumber",
                "electrician",
                "carpenter",
                "plumber near me",
                "bijli mistri",
                "nal mistri",
            ],
            ["plumber", "electrician", "general_contractor", "carpenter", "painter", "locksmith"],
            {
                "plumbing": ["plumb", "tap", "leak", "pipe", "nal", "bathroom fitting"],
                "electrical": ["electric", "wiring", "switch", "fan", "bijli", "inverter"],
                "carpentry": ["carpent", "furniture", "door", "wardrobe", "lakdi"],
                "painting": ["paint", "painting", "putty"],
            },
            home_visit=True,
        ),
        _c(
            "packers_movers",
            "Packers and movers",
            [
                "packers and movers",
                "movers and packers",
                "home shifting",
                "relocation services",
                "saman shifting",
            ],
            ["moving_company", "storage", "courier_service", "store"],
            {
                "house_shifting": ["house shifting", "home shifting", "relocation", "shifting"],
                "packing": ["packing", "packers"],
                "vehicle_transport": ["car transport", "bike transport", "vehicle"],
                "storage": ["storage", "warehouse"],
            },
            home_visit=True,
        ),
        _c(
            "pest_control",
            "Pest control",
            [
                "pest control",
                "termite control",
                "cockroach control",
                "keede makode",
                "pest control service",
            ],
            ["pest_control_service", "store", "home_improvement_store", "general_contractor"],
            {
                "cockroach": ["cockroach", "roach"],
                "termite": ["termite", "deemak", "wood borer"],
                "bed_bugs": ["bed bug", "bedbug", "khatmal"],
                "rodent": ["rat", "rodent", "mice", "chuha"],
                "mosquito": ["mosquito", "machhar", "fogging"],
            },
            home_visit=True,
        ),
        _c(
            "car_service",
            "Car service / garage / car wash",
            [
                "car service",
                "car garage",
                "car repair",
                "car wash",
                "car mechanic",
                "gaadi service",
            ],
            ["car_repair", "car_wash", "car_dealer", "auto_parts_store", "store"],
            {
                "general_service": ["service", "servicing", "oil change", "general service"],
                "denting_painting": ["denting", "painting", "dent", "scratch"],
                "wash_detailing": ["wash", "detailing", "polish", "ceramic", "foam wash"],
                "ac_repair": ["ac", "cooling"],
                "tyres_alignment": ["tyre", "tire", "alignment", "balancing"],
                "battery": ["battery"],
            },
        ),
        _c(
            "restaurant_banquet",
            "Restaurants / banquet / caterers",
            [
                "restaurant",
                "banquet hall",
                "caterer",
                "party hall",
                "best restaurant",
                "dawat hall",
            ],
            [
                "restaurant",
                "banquet_hall",
                "event_venue",
                "catering_service",
                "cafe",
                "meal_takeaway",
            ],
            {
                "table_booking": ["table", "reservation", "booking", "seating"],
                "banquet": ["banquet", "hall", "party", "function"],
                "catering": ["catering", "caterer", "buffet"],
                "veg": ["veg", "vegetarian", "jain", "pure veg"],
                "private_dining": ["private dining", "birthday", "anniversary"],
            },
        ),
        _c(
            "coaching_classes",
            "Coaching / hobby classes / schools",
            [
                "coaching classes",
                "tuition classes",
                "coaching institute",
                "hobby classes",
                "dance classes",
                "music classes",
                "school",
            ],
            [
                "school",
                "primary_school",
                "secondary_school",
                "preschool",
                "university",
                "tutoring_service",
                "dance_school",
                "music_school",
                "art_school",
                "store",
            ],
            {
                "school_admission": ["admission", "school", "nursery", "kg"],
                "exam_coaching": ["jee", "neet", "upsc", "cat", "ielts", "coaching", "board"],
                "tuition": ["tuition", "maths", "science", "english"],
                "dance_music": ["dance", "music", "guitar", "singing", "piano"],
                "art_craft": ["art", "drawing", "craft", "painting"],
            },
        ),
        _c(
            "pg_rental",
            "PG / rental / real estate",
            [
                "pg accommodation",
                "paying guest",
                "flat for rent",
                "property dealer",
                "real estate agent",
                "girls pg",
                "boys pg",
            ],
            [
                "real_estate_agency",
                "lodging",
                "apartment_rental_agency",
                "guest_house",
                "hostel",
                "rental_service",
            ],
            {
                "pg": ["pg", "paying guest", "hostel"],
                "flat_rent": ["flat", "rent", "bhk", "apartment", "kiraya"],
                "buy_sell": ["buy", "sell", "property", "plot"],
                "food_included": ["food", "meals", "mess"],
            },
        ),
        _c(
            "electronics_dealer",
            "Mobile and electronics dealers",
            [
                "mobile shop",
                "mobile phone dealer",
                "electronics shop",
                "laptop dealer",
                "mobile repair",
            ],
            ["cell_phone_store", "electronics_store", "store", "home_goods_store"],
            {
                "mobile_phone": ["mobile", "phone", "iphone", "samsung", "oneplus"],
                "laptop": ["laptop", "macbook"],
                "repair": ["repair", "screen", "display", "battery"],
                "accessories": ["charger", "cover", "earphone", "headphone", "accessories"],
                "tv_appliance": ["tv", "fridge", "washing machine"],
            },
        ),
        _c(
            "gym_yoga",
            "Gyms and yoga",
            [
                "gym",
                "fitness center",
                "yoga classes",
                "yoga studio",
                "zumba classes",
                "gym near me",
            ],
            [
                "gym",
                "fitness_center",
                "yoga_studio",
                "sports_activity_location",
                "sports_club",
                "health",
            ],
            {
                "gym_membership": ["membership", "gym", "workout", "equipment"],
                "personal_training": ["personal trainer", "personal training", "trainer", "pt"],
                "yoga": ["yoga", "meditation", "pranayam"],
                "zumba_aerobics": ["zumba", "aerobics", "dance fitness"],
                "trial": ["trial", "demo", "free session"],
            },
        ),
        _c(
            "event_services",
            "Event services: photographer, decorator, DJ",
            [
                "event planner",
                "photographer",
                "decorator",
                "dj for party",
                "event management",
                "birthday decorator",
            ],
            ["event_planner", "photographer", "event_venue", "store", "wedding_planner"],
            {
                "photography": ["photo", "photographer", "shoot", "album", "candid"],
                "videography": ["video", "videographer", "reel", "drone"],
                "decoration": ["decor", "decoration", "balloon", "theme", "stage"],
                "dj_sound": ["dj", "sound", "music", "speaker"],
                "birthday": ["birthday", "kids party", "anniversary"],
            },
        ),
        _c(
            "vet_pet",
            "Vets and pet grooming",
            ["vet", "veterinary clinic", "pet grooming", "pet clinic", "dog doctor", "pet shop"],
            ["veterinary_care", "pet_store", "pet_care_service", "animal_hospital", "dog_trainer"],
            {
                "vet_consultation": ["vet", "doctor", "checkup", "consultation", "treatment"],
                "vaccination": ["vaccine", "vaccination", "deworm"],
                "grooming": ["groom", "grooming", "bath", "haircut", "spa"],
                "boarding": ["boarding", "daycare", "stay"],
                "surgery": ["surgery", "spay", "neuter"],
            },
        ),
        _c(
            "wedding_vendors",
            "Wedding vendors: makeup, mehendi, planners",
            [
                "bridal makeup artist",
                "mehendi artist",
                "wedding planner",
                "wedding photographer",
                "shaadi planner",
                "wedding decorator",
            ],
            [
                "wedding_planner",
                "beauty_salon",
                "event_planner",
                "photographer",
                "florist",
                "store",
            ],
            {
                "bridal_makeup": ["bridal", "makeup", "make up", "hd makeup", "airbrush"],
                "mehendi": ["mehendi", "mehndi", "henna"],
                "planning": ["wedding planner", "planning", "shaadi", "coordination"],
                "photography": ["photo", "pre wedding", "candid", "video"],
                "decoration": ["decor", "mandap", "stage", "flowers"],
            },
        ),
        _c(
            "driving_school",
            "Driving schools",
            [
                "driving school",
                "car driving classes",
                "learn driving",
                "driving training",
                "gaadi sikhna",
            ],
            ["driving_school", "school", "store", "car_rental"],
            {
                "car_learning": ["car", "four wheeler", "learn", "driving lesson"],
                "two_wheeler": ["bike", "scooty", "scooter", "two wheeler", "activa"],
                "licence_help": ["licence", "license", "dl", "rto", "test"],
                "female_trainer": ["lady trainer", "female trainer", "women"],
            },
        ),
        _c(
            "cab_travel",
            "Cab hire / travel agents",
            [
                "cab service",
                "taxi service",
                "travel agent",
                "outstation cab",
                "tour operator",
                "cab on rent",
            ],
            [
                "travel_agency",
                "taxi_service",
                "car_rental",
                "taxi_stand",
                "tour_agency",
                "transportation_service",
            ],
            {
                "outstation": ["outstation", "one way", "round trip", "airport", "drop"],
                "local_hire": ["local", "hourly", "8 hours", "full day"],
                "tour_package": ["tour", "package", "holiday", "trip"],
                "tempo_traveller": ["tempo traveller", "traveller", "bus", "group"],
                "tickets_visa": ["ticket", "visa", "passport", "flight"],
            },
        ),
        _c(
            "laundry_tailor",
            "Laundry / dry-clean / tailors",
            [
                "dry cleaner",
                "laundry service",
                "tailor",
                "boutique tailoring",
                "ladies tailor",
                "darji",
            ],
            [
                "laundry",
                "dry_cleaning_service",
                "tailor",
                "clothing_alteration_service",
                "clothing_store",
                "store",
            ],
            {
                "dry_clean": ["dry clean", "drycleaning", "suit", "saree", "blanket"],
                "wash_iron": ["wash", "iron", "press", "laundry", "fold"],
                "stitching": ["stitch", "stitching", "blouse", "suit", "kurta", "tailor"],
                "alteration": ["alteration", "alter", "fitting", "length"],
                "pickup_delivery": ["pickup", "pick up", "delivery", "doorstep"],
            },
            home_visit=True,
        ),
        _c(
            "florist_gift",
            "Florists and gift shops",
            ["florist", "flower shop", "gift shop", "bouquet", "cake and flowers", "phool wala"],
            ["florist", "gift_shop", "store", "bakery", "flower_shop"],
            {
                "bouquet": ["bouquet", "flowers", "roses", "phool"],
                "same_day_delivery": ["same day", "delivery", "midnight", "on time"],
                "gift_hamper": ["hamper", "gift", "personalised", "personalized", "chocolate"],
                "cake": ["cake", "bakery"],
                "decor_flowers": ["decoration", "garland", "mala", "event flowers"],
            },
        ),
    ]
}

# (default, hard max) km per category, from docs/AGENT_ROSTER.md "Distance rule".
RADII: dict[str, tuple[float, float]] = {
    **dict.fromkeys(["salon", "gym_yoga", "florist_gift", "pg_rental"], (5, 10)),
    **dict.fromkeys(["clinic", "diagnostic_lab", "vet_pet"], (8, 15)),
    "restaurant_banquet": (5, 12),
    **dict.fromkeys(
        ["appliance_repair", "home_repair", "pest_control", "laundry_tailor"], (10, 20)
    ),
    **dict.fromkeys(
        ["packers_movers", "event_services", "wedding_vendors", "cab_travel"], (20, 40)
    ),
    **dict.fromkeys(["coaching_classes", "driving_school"], (8, 15)),
    **dict.fromkeys(["car_service", "electronics_dealer"], (8, 15)),  # not in the doc: our pick
}
for _k, (_d, _m) in RADII.items():
    CATEGORIES[_k].default_radius_km = float(_d)
    CATEGORIES[_k].max_radius_km = float(_m)

assert len(CATEGORIES) == 20 and set(RADII) == set(CATEGORIES)


def effective_radius_km(category: Category, requested: float | None) -> float:
    """Caller (project manager) may widen; never past the hard max, never below 0.5."""
    r = category.default_radius_km if requested is None else requested
    return max(0.5, min(r, category.max_radius_km))


def get_category(key: str) -> Category:
    try:
        return CATEGORIES[key]
    except KeyError:
        raise KeyError(f"unknown category {key!r}; known: {', '.join(CATEGORIES)}") from None


def build_queries(category: Category, area: str, *, max_queries: int = 3) -> list[str]:
    """Agent 5-lite: plain table lookup. The searcher appends the area itself."""
    return list(category.queries[: max(1, max_queries)])


def _has_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}", text) is not None


def match_services(category: Category, wanted: list[str]) -> list[str]:
    """Map free-text wanted services onto service keys (closed vocabulary).

    Unmatched words are kept as-is (literal terms) so nothing the user asked is lost.
    """
    out: list[str] = []
    for w in wanted:
        low = w.strip().lower()
        if not low:
            continue
        best: tuple[int, str] | None = None
        for k, syn in category.services.items():
            if low == k or low.replace(" ", "_") == k:
                best = (999, k)
                break
            for t in syn:
                if _has_term(low, t) and (best is None or len(t) > best[0]):
                    best = (len(t), k)
        hit = best[1] if best else None
        out.append(hit or low)
    return list(dict.fromkeys(out))


def service_terms(category: Category, label: str) -> list[str]:
    return category.services.get(label) or [label.replace("_", " ")]


# Measured 2026-10-12 (docs/SCOUTING.md): for these, Google's types are generic ("service"), so the
# place name must carry one of these words (lowercase substring) as well.
_NAME_KEYWORDS: dict[str, list[str]] = {
    "appliance_repair": [
        "ac ", "a.c", "air con", "appliance", "refrigerator", "fridge", "washing machine",
        "repair", "cooling", "geyser", "microwave", "hvac", "service centre", "service center",
    ],
    "pest_control": ["pest", "termite", "fumigation", "disinfect", "cockroach", "rodent", "sanit"],
    "home_repair": [
        "plumb", "electric", "carpent", "paint", "repair", "handyman", "contractor", "interior",
        "locksmith", "waterproof", "maintenance", "fabricat",
    ],
    "coaching_classes": [
        "coaching", "classes", "academy", "tutorial", "tuition", "institute", "education",
        "learning", "ielts", "study", "training",
    ],
    "driving_school": ["driving", "motor training", "car training", "learn"],
    "event_services": [
        "event", "decor", "wedding", "planner", "photo", "catering", "dj", "entertain", "tent",
        "party", "balloon",
    ],
    "wedding_vendors": [
        "wedding", "bridal", "bride", "makeup", "mehendi", "mehandi", "photo", "planner", "decor",
    ],
    "packers_movers": ["packers", "movers", "relocation", "shifting", "logistics", "transport"],
}
for _k, _w in _NAME_KEYWORDS.items():
    CATEGORIES[_k].name_keywords = _w
_EXTRA_TYPES = {
    "appliance_repair": ["electrician", "general_contractor", "home_goods_store"],
    "packers_movers": ["transportation_service", "shipping_service"],
    "wedding_vendors": ["makeup_artist", "body_art_service"],
    "event_services": ["wedding_venue", "florist"],
}
for _k, _t in _EXTRA_TYPES.items():
    CATEGORIES[_k].expected_types += [t for t in _t if t not in CATEGORIES[_k].expected_types]
