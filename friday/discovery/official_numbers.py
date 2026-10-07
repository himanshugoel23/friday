"""Curated, verified customer-care numbers (C26, US-35).

Data: ``friday/discovery/data/official_numbers.json`` (or ``Settings.official_numbers_path``).
In simulator mode, simworld care lines (``official: true``) take precedence for the
companies they cover, so simulated calls reach the simulated IVR, never a real line.
Numbers from web-search snippets are never used.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from friday.core.models import OfficialNumber
from friday.discovery.geo import phone_key
from friday.simworld import SimWorld, load_world

DATA_PATH = Path(__file__).with_name("data") / "official_numbers.json"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class OfficialNumbers:
    """``OfficialNumberDirectory`` implementation."""

    def __init__(
        self, entries: list[tuple[set[str], OfficialNumber]], *, sim: SimWorld | None = None
    ) -> None:
        self._entries = entries  # (normalised names incl. aliases, number)
        self._sim: list[tuple[set[str], OfficialNumber]] = []
        if sim is not None:
            for b in sim.businesses:
                if b.official and b.company:
                    self._sim.append(
                        (
                            {_norm(b.company)},
                            OfficialNumber(
                                company=b.company,
                                phone=b.phone,
                                purpose=None,
                                region=b.city,
                                source="simworld",
                            ),
                        )
                    )

    @classmethod
    def from_file(cls, path: str | Path | None = None, *, sim: SimWorld | None = None):
        data = json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))
        entries: list[tuple[set[str], OfficialNumber]] = []
        for company in data.get("companies", []):
            names = {_norm(company["company"]), *(_norm(a) for a in company.get("aliases", []))}
            for n in company.get("numbers", []):
                verified = n.get("verified_at")
                entries.append(
                    (
                        names,
                        OfficialNumber(
                            company=company["company"],
                            phone=n["phone"],
                            purpose=n.get("purpose"),
                            region=n.get("region"),
                            source=n.get("source", "curated"),
                            verified_at=date.fromisoformat(verified) if verified else None,
                        ),
                    )
                )
        return cls(entries, sim=sim)

    def _match(self, pool: list[tuple[set[str], OfficialNumber]], company: str):
        key = _norm(company)
        if not key:
            return []
        exact = [n for names, n in pool if key in names]
        if exact:
            return exact

        # "Airtel broadband" -> Airtel; "HDFC" -> HDFC Bank
        def prefix(a: str, b: str) -> bool:
            return len(b) >= 4 and a.startswith(b)

        return [n for names, n in pool if any(prefix(key, k) or prefix(k, key) for k in names)]

    async def lookup(self, company: str, *, purpose: str | None = None) -> list[OfficialNumber]:
        found = self._match(self._sim, company) or self._match(self._entries, company)
        if purpose and found:
            p = purpose.lower()
            preferred = [n for n in found if n.purpose and (n.purpose in p or p in n.purpose)]
            if preferred:
                return preferred + [n for n in found if n not in preferred]
        return found

    async def find_by_phone(self, phone: str) -> OfficialNumber | None:
        key = phone_key(phone)
        for _, n in [*self._sim, *self._entries]:
            if phone_key(n.phone) == key:
                return n
        return None

    async def companies(self) -> list[str]:
        return sorted({n.company for _, n in [*self._sim, *self._entries]})


def build_official_numbers(c) -> OfficialNumbers:  # c: Container
    s = c.settings
    sim = None if s.is_live else load_world()
    return OfficialNumbers.from_file(s.official_numbers_path, sim=sim)
