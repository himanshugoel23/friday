"""Swiggy food ordering (``swiggy.food``), following the Zomato adapter.

``ADAPTERS`` / ``FAKE_SITES`` are resolved lazily (PEP 562) so that ``sites/adapters.py`` can import
this package without an import cycle. Keys are ``"<catalog site key>.<use case>"``.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "ADAPTERS":
        from friday.connectors.sites.swiggy.adapters import ADAPTERS

        return ADAPTERS
    if name == "FAKE_SITES":
        from friday.connectors.sites.fakes.swiggy_site import FAKE_SITES

        return FAKE_SITES
    raise AttributeError(name)


__all__ = ["ADAPTERS", "FAKE_SITES"]
