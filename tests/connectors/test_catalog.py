from friday.connectors import catalog as C
from friday.connectors.defaults import build_default_registry
from friday.connectors.session.credentials import is_blocked


def test_every_requested_site_is_in_the_catalog():
    for key in ("zomato", "swiggy", "zepto", "blinkit", "uber", "ola", "rapido", "makemytrip",
                "bookmyshow", "irctc", "redbus"):
        assert C.site(key), key
    assert {s.category for s in C.SITES} >= {"food", "grocery", "ride", "stay", "train", "bus"}


def test_keys_unique_and_hosts_present():
    keys = [s.key for s in C.SITES]
    assert len(keys) == len(set(keys))
    assert all(
        s.hosts and s.home.startswith("https://") and s.category in C.CATEGORIES for s in C.SITES
    )


def test_nothing_is_automated_until_cleared_enabled_and_supervised():
    for s in C.SITES:
        assert C.effective_mode(s.key) in ("deeplink", "blocked")
        assert C.effective_mode(s.key, {s.key}) in ("deeplink", "blocked")  # still unverified legal
    assert C.effective_mode("zomato", {"zomato"}, supervised=True) == "deeplink"


def test_cleared_scripted_site_runs_only_with_enable_and_supervision(monkeypatch):
    import dataclasses

    cleared = dataclasses.replace(C.site("zomato"), legal=C.LEGAL_CLEARED)
    monkeypatch.setitem(C.BY_KEY, "zomato", cleared)
    assert C.effective_mode("zomato", {"zomato"}, supervised=True) == "scripted"
    assert C.effective_mode("zomato", {"zomato"}, supervised=False) == "deeplink"
    assert C.effective_mode("zomato", set(), supervised=True) == "deeplink"


def test_amazon_and_irctc_follow_the_normal_gate():
    assert C.site("amazon").mode != "blocked" and C.effective_mode("amazon") == "deeplink"
    assert C.site("irctc").mode != "blocked"
    assert C.effective_mode("irctc") == "deeplink"  # link today, like every uncleared site
    assert not is_blocked("irctc", C.policy_hosts("irctc"))  # its login can be saved
    assert is_blocked("hdfc", ["netbanking.hdfcbank.com"])  # banks still never


def test_hosts_resolve_back_to_sites():
    assert C.find_for_host("m.uber.com").key == "uber"
    assert C.find_for_host("api.zeptonow.com").key == "zepto"
    assert C.find_for_host("evil.example") is None


def test_default_registry_hands_a_link_for_every_unblocked_site():
    reg = build_default_registry()
    for s in C.SITES:
        if s.mode == "blocked":
            assert reg.fallback_url(s.key, s.use_cases[0]) is None
        else:
            uc = (s.use_cases or (s.category,))[0]
            assert reg.select(s.key, uc) is not None and reg.fallback_url(s.key, uc) == s.home
