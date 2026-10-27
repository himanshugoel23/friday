# ruff: noqa: E501
"""The site catalog: every website Friday may help with, as DATA (docs/BROWSER_SITE_COVERAGE.md).

Adding a site is one entry here, not a new module. For each site the catalog says what kind of help
exists today (``mode``), whether the real site may be automated (``legal``), how login works, which
host names the private browser may reach and the password vault may bind to, and the public page
the user can always finish on by hand.

Modes, best first:  official (the site's own API / partner programme)  >  scripted (a selector-based
connector exists)  >  deeplink (Friday hands over the link; the user finishes in the app)  >
blocked (never automated). A real-site run needs ALL of: mode scripted/official, ``legal ==
"cleared"`` for that site, the site named in ``FRIDAY_BROWSER_SITES_ENABLED``, and a founder-
supervised session. Nothing is cleared today, so every real site resolves to ``deeplink``.

HOST NAMES AND URLS ARE FROM GENERAL KNOWLEDGE AND UNVERIFIED: check each before enabling a site.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

CATEGORIES = ("food", "grocery", "ride", "stay", "train", "bus", "flight", "movies", "shopping")
LEGAL_UNVERIFIED = "unverified"
LEGAL_CLEARED = "cleared"
LEGAL_BLOCKED = "blocked"


@dataclass(frozen=True)
class SiteSpec:
    key: str
    name: str
    category: str
    hosts: tuple[str, ...]
    home: str  # the public page the user can finish on by hand
    mode: str = "deeplink"  # official | scripted | deeplink | blocked
    legal: str = LEGAL_UNVERIFIED  # unverified | cleared | blocked
    login: str = "otp_on_site"  # otp_on_site | password | google | none
    irreversible: str = "place order"  # the one click that needs an approval
    adapter: str = ""  # dotted path once a scripted adapter exists
    note: str = ""
    use_cases: tuple[str, ...] = field(default_factory=tuple)


def _s(key: str, name: str, category: str, hosts: str, home: str, **kw) -> SiteSpec:  # type: ignore[no-untyped-def]
    return SiteSpec(key, name, category, tuple(h.strip() for h in hosts.split(",")), home, **kw)


SITES: tuple[SiteSpec, ...] = (
    # ---- food
    _s("zomato", "Zomato", "food", "www.zomato.com,*.zomato.com", "https://www.zomato.com",
       mode="scripted", adapter="friday.connectors.sites.zomato_agent", use_cases=("food",),
       note="selectors tuned on a FAKE site only; real pages unverified; blocks datacenter IPs"),
    _s("swiggy", "Swiggy", "food", "www.swiggy.com,*.swiggy.com", "https://www.swiggy.com",
       use_cases=("food",), note="invite-led developer programme reported (unverified): prefer official access; challenge page seen from our server"),
    # ---- grocery / quick commerce
    _s("zepto", "Zepto", "grocery", "www.zeptonow.com,*.zeptonow.com", "https://www.zeptonow.com",
       use_cases=("grocery",), note="app-first; web ordering coverage unverified"),
    _s("blinkit", "Blinkit", "grocery", "blinkit.com,*.blinkit.com", "https://blinkit.com",
       use_cases=("grocery",), note="app-first; web ordering coverage unverified"),
    _s("bigbasket", "BigBasket", "grocery", "www.bigbasket.com,*.bigbasket.com", "https://www.bigbasket.com",
       use_cases=("grocery",)),
    _s("instamart", "Swiggy Instamart", "grocery", "www.swiggy.com", "https://www.swiggy.com/instamart",
       use_cases=("grocery",)),
    # ---- rides
    _s("uber", "Uber", "ride", "m.uber.com,*.uber.com", "https://m.uber.com", irreversible="request ride",
       use_cases=("ride",), note="check Uber's official ride-request API first; asks OTP"),
    _s("ola", "Ola", "ride", "www.olacabs.com,*.olacabs.com", "https://www.olacabs.com", irreversible="request ride",
       use_cases=("ride",), note="web booking availability unverified (Instinct review: cab apps without web booking)"),
    _s("rapido", "Rapido", "ride", "www.rapido.bike,*.rapido.bike", "https://www.rapido.bike", irreversible="request ride",
       use_cases=("ride",), note="app-first; web booking unverified"),
    # ---- stays and travel
    _s("makemytrip", "MakeMyTrip", "stay", "www.makemytrip.com,*.makemytrip.com", "https://www.makemytrip.com",
       irreversible="confirm booking", use_cases=("hotel", "flight", "bus", "train"), note="heavy anti-bot expected (unverified)"),
    _s("goibibo", "Goibibo", "stay", "www.goibibo.com,*.goibibo.com", "https://www.goibibo.com",
       irreversible="confirm booking", use_cases=("hotel", "flight", "bus")),
    _s("booking", "Booking.com", "stay", "www.booking.com,*.booking.com", "https://www.booking.com",
       irreversible="confirm booking", use_cases=("hotel",), note="often priced in a foreign currency or needs a foreign card route (Instinct review)"),
    _s("agoda", "Agoda", "stay", "www.agoda.com,*.agoda.com", "https://www.agoda.com", irreversible="confirm booking",
       use_cases=("hotel",)),
    _s("oyo", "OYO", "stay", "www.oyorooms.com,*.oyorooms.com", "https://www.oyorooms.com", irreversible="confirm booking",
       use_cases=("hotel",)),
    _s("cleartrip", "Cleartrip", "flight", "www.cleartrip.com,*.cleartrip.com", "https://www.cleartrip.com",
       irreversible="confirm booking", use_cases=("flight", "hotel")),
    # ---- trains
    _s("irctc", "IRCTC", "train", "www.irctc.co.in,*.irctc.co.in", "https://www.irctc.co.in", login="password",
       irreversible="book ticket", use_cases=("train",),
       note="link hand-over today; no scripted adapter yet; whether the site's terms allow automated booking is unverified (check before enabling)"),
    _s("erail", "eRail (info only)", "train", "erail.in,*.erail.in", "https://erail.in", login="none",
       irreversible="none", use_cases=("train_info",), note="read-only seat and timetable information; no booking"),
    _s("ixigo", "ixigo", "train", "www.ixigo.com,*.ixigo.com", "https://www.ixigo.com", irreversible="confirm booking",
       use_cases=("train", "flight", "bus"), note="a possible partner route for train booking; terms unverified"),
    # ---- buses
    _s("redbus", "redBus", "bus", "www.redbus.in,*.redbus.in", "https://www.redbus.in", irreversible="confirm booking",
       use_cases=("bus",)),
    _s("abhibus", "AbhiBus", "bus", "www.abhibus.com,*.abhibus.com", "https://www.abhibus.com", irreversible="confirm booking",
       use_cases=("bus",)),
    # ---- movies
    _s("bookmyshow", "BookMyShow", "movies", "in.bookmyshow.com,*.bookmyshow.com", "https://in.bookmyshow.com",
       mode="scripted", adapter="friday.connectors.sites.movies.bookmyshow", irreversible="confirm tickets",
       use_cases=("movie",), note="selectors tuned on a FAKE site only"),
    # ---- shopping
    _s("amazon", "Amazon India", "shopping", "www.amazon.in,*.amazon.in", "https://www.amazon.in",
       irreversible="place order", use_cases=("shopping",),
       note="link hand-over today; no scripted adapter yet; automation terms unverified (conditions of use mention robots): check before enabling"),
    _s("flipkart", "Flipkart", "shopping", "www.flipkart.com,*.flipkart.com", "https://www.flipkart.com",
       use_cases=("shopping",), note="terms unverified"),
)

BY_KEY = {s.key: s for s in SITES}


def site(key: str) -> SiteSpec | None:
    return BY_KEY.get((key or "").strip().lower())


def by_category(category: str) -> list[SiteSpec]:
    return [s for s in SITES if s.category == category]


def find_for_host(host: str) -> SiteSpec | None:
    h = (host or "").lower().rstrip(".")
    for s in SITES:
        for pat in s.hosts:
            if h == pat or (pat.startswith("*.") and h.endswith(pat[1:])):
                return s
    return None


def _has_adapter(s: SiteSpec) -> bool:
    """True when a scripted adapter (fake-tested) exists for any use case of this site."""
    try:
        from friday.connectors.sites import categories

        return any(categories.has_adapter(s.key, u) for u in (s.use_cases or (s.category,)))
    except Exception:  # noqa: BLE001 - the loader must never break the catalog
        return False


def effective_mode(key: str, enabled: Collection[str] = frozenset(), *, supervised: bool = False,
                   cleared: Collection[str] | None = None,
                   adapter: bool | None = None) -> str:
    """What Friday may actually do on this site right now: ``official`` | ``scripted`` |
    ``deeplink`` | ``blocked``. A site is automated only when a scripted/official backend exists
    (``mode`` or a loaded adapter), its legal status is ``cleared`` (the constant on the entry OR
    the founder's ``cleared`` set, FRIDAY_BROWSER_LEGAL_CLEARED), it is named in ``enabled`` AND the
    session is founder-supervised. ``adapter`` overrides the adapter lookup (tests)."""
    s = site(key)
    if s is None or s.mode == "blocked" or s.legal == LEGAL_BLOCKED:
        return "blocked"
    is_cleared = s.legal == LEGAL_CLEARED or s.key in {c.strip().lower() for c in (cleared or ())}
    backend = s.mode in ("scripted", "official") or (_has_adapter(s) if adapter is None else adapter)
    if backend and is_cleared and s.key in {e.strip().lower() for e in enabled} and supervised:
        return s.mode if s.mode in ("scripted", "official") else "scripted"
    return "deeplink"


def policy_hosts(key: str) -> set[str]:
    s = site(key)
    return set(s.hosts) if s else set()


def coverage() -> dict[str, dict[str, list[str]]]:
    """Category -> mode -> site keys, for docs and the doctor."""
    out: dict[str, dict[str, list[str]]] = {}
    for s in SITES:
        out.setdefault(s.category, {}).setdefault(s.mode, []).append(s.key)
    return out
