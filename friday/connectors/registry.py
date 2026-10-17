"""Connector registry: (site, use case) -> backends, each with a status, version and kill switch.

Selection prefers backends in the order official MCP > deep link > scripted browser > LLM browser,
but only those whose status is ``live``. Nothing live -> ``select`` returns None and the caller
hands the user a "finish in the app" link instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BackendKind(StrEnum):
    official_mcp = "official_mcp"
    deep_link = "deep_link"
    scripted_browser = "scripted_browser"
    llm_browser = "llm_browser"


class Status(StrEnum):
    live = "live"
    degraded = "degraded"
    off = "off"


PREFERENCE: tuple[BackendKind, ...] = (
    BackendKind.official_mcp,
    BackendKind.deep_link,
    BackendKind.scripted_browser,
    BackendKind.llm_browser,
)
KILL_ENV = "FRIDAY_CONNECTORS_KILL"  # CSV of "site.use_case" (or "all") that must be off


@dataclass
class Registration:
    site: str
    use_case: str
    backend: BackendKind
    status: Status
    version: str
    connector: Any = None  # the object implementing the use-case Protocol (None for a bare link)
    fallback_url: str | None = None  # where the user can finish by hand
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.site}.{self.use_case}"


@dataclass
class ConnectorRegistry:
    _items: list[Registration] = field(default_factory=list)
    _killed: set[str] = field(default_factory=set)
    _all_killed: bool = False

    def register(self, reg: Registration) -> None:
        self._items = [
            r for r in self._items
            if not (r.key == reg.key and r.backend == reg.backend)
        ]
        self._items.append(reg)

    def all(self) -> list[Registration]:
        return list(self._items)

    # ---- kill switch (in memory; the env var seeds it at start-up)
    def kill(self, site: str, use_case: str) -> None:
        self._killed.add(f"{site}.{use_case}")

    def revive(self, site: str, use_case: str) -> None:
        self._killed.discard(f"{site}.{use_case}")

    def kill_all(self, on: bool = True) -> None:
        self._all_killed = on

    def seed_kill_from_env(self, env: Mapping[str, str] | None = None) -> None:
        raw = (env if env is not None else os.environ).get(KILL_ENV, "")
        for part in (p.strip() for p in raw.split(",")):
            if part == "all":
                self._all_killed = True
            elif part:
                self._killed.add(part)

    def is_killed(self, site: str, use_case: str) -> bool:
        return self._all_killed or f"{site}.{use_case}" in self._killed

    # ---- status
    def set_status(self, site: str, use_case: str, backend: BackendKind, status: Status) -> None:
        for r in self._items:
            if r.key == f"{site}.{use_case}" and r.backend == backend:
                r.status = status

    def _candidates(self, site: str, use_case: str) -> list[Registration]:
        return [r for r in self._items if r.key == f"{site}.{use_case}"]

    def select(self, site: str, use_case: str, fulfils: bool = False) -> Registration | None:
        """Best LIVE backend by PREFERENCE, or None (killed, degraded or off).
        ``fulfils=True`` skips bare links (no connector object): they can only be handed to the
        user as "finish in the app", they cannot run the use case."""
        if self.is_killed(site, use_case):
            return None
        live = [
            r for r in self._candidates(site, use_case)
            if r.status == Status.live and (r.connector is not None or not fulfils)
        ]
        live.sort(key=lambda r: PREFERENCE.index(r.backend))
        return live[0] if live else None

    def fallback_url(self, site: str, use_case: str) -> str | None:
        """A public link the user can finish on by hand (works even when killed)."""
        for r in self._candidates(site, use_case):
            if r.fallback_url:
                return r.fallback_url
        return None

    def describe(self) -> Iterable[dict[str, str]]:
        for r in sorted(self._items, key=lambda r: (r.key, PREFERENCE.index(r.backend))):
            status = Status.off if self.is_killed(r.site, r.use_case) else r.status
            yield {
                "connector": r.key, "backend": r.backend.value, "status": status.value,
                "version": r.version, "note": r.note,
            }
