"""The registry Friday starts with. Honest about what is real: nothing browser-driven is live."""

from __future__ import annotations

from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status


def build_default_registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(Registration(
        "zomato", "food", BackendKind.deep_link, Status.live, "0.1",
        fallback_url="https://www.zomato.com", note="link only: user finishes in the app"))
    reg.register(Registration(
        "zomato", "food", BackendKind.scripted_browser, Status.off, "0.1",
        note="selectors tuned on a FAKE site only; real pages unverified"))
    # every other cataloged site: a link the user finishes on by hand (works today, no automation)
    from friday.connectors.catalog import SITES

    for spec in SITES:
        if spec.mode == "blocked" or spec.key == "zomato":
            continue
        for use_case in spec.use_cases or (spec.category,):
            reg.register(Registration(
                spec.key, use_case, BackendKind.deep_link, Status.live, "0.1",
                fallback_url=spec.home, note="link only: user finishes in the app"))
    reg.seed_kill_from_env()
    return reg
