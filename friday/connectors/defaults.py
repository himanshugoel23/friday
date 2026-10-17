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
    reg.seed_kill_from_env()
    return reg
