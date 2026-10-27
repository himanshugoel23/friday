"""Category-adapter loader: grocery, ride, stay, bus, train, shopping, swiggy (default OFF).

Each category is its own package under ``friday/connectors/sites/<name>/`` exporting ``ADAPTERS``
(``"<site>.<use case>"`` -> adapter class, same protocol as ``FoodAdapter`` / ``MovieAdapter``) and
``FAKE_SITES`` (fake-site factories for tests and ``friday browser-sim``). They are imported lazily
and an absent or broken package is skipped, so the flow works with whatever has landed.

``adapter_for(site, use_case)`` is the one lookup the planner and the flow use.
"""

from __future__ import annotations

import importlib
from typing import Any

PACKAGES = ("grocery", "ride", "stay", "bus", "train", "shopping", "swiggy")
_BASE = "friday.connectors.sites"

_loaded = False
_adapters: dict[str, Any] = {}
_fakes: dict[str, Any] = {}
_present: list[str] = []
_failed: dict[str, str] = {}


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from friday.connectors.sites.adapters import ADAPTERS as BASE

    _adapters.update(BASE)
    for name in PACKAGES:
        try:
            mod = importlib.import_module(f"{_BASE}.{name}")
        except ModuleNotFoundError as e:
            if e.name and e.name.startswith(f"{_BASE}.{name}"):
                continue  # the package has not landed yet
            _failed[name] = type(e).__name__
            continue
        except ImportError as e:  # a broken package must not stop the others
            _failed[name] = type(e).__name__
            continue
        _present.append(name)
        for key, cls in dict(getattr(mod, "ADAPTERS", {}) or {}).items():
            _adapters.setdefault(key, cls)
        for key, fake in dict(getattr(mod, "FAKE_SITES", {}) or {}).items():
            _fakes.setdefault(key, fake)


def reload() -> None:
    """Forget what was loaded (tests, or after a package landed in a running process)."""
    global _loaded
    _loaded = False
    _adapters.clear()
    _fakes.clear()
    _present.clear()
    _failed.clear()
    importlib.invalidate_caches()


def all_adapters() -> dict[str, Any]:
    _load()
    return dict(_adapters)


def all_fake_sites() -> dict[str, Any]:
    _load()
    return dict(_fakes)


def present_packages() -> list[str]:
    _load()
    return list(_present)


def missing_packages() -> list[str]:
    _load()
    return [p for p in PACKAGES if p not in _present]


def failed_packages() -> dict[str, str]:
    """Packages that exist but failed to import (name -> exception type, never a message)."""
    _load()
    return dict(_failed)


def adapter_for(site_key: str, use_case: str) -> Any | None:
    """The adapter class for ``<site>.<use case>``, or None (the user then gets the link)."""
    _load()
    return _adapters.get(f"{(site_key or '').strip().lower()}.{(use_case or '').strip().lower()}")


def has_adapter(site_key: str, use_case: str) -> bool:
    return adapter_for(site_key, use_case) is not None


def sites_with_adapters() -> set[str]:
    _load()
    return {k.split(".", 1)[0] for k in _adapters}
