"""Summariser: what happened, in the user's language, with no secrets (deterministic, one job)."""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.connectors.contract import format_rupees
from friday.connectors.sites.copy import render


@dataclass
class Facts:
    use_case: str  # "food" | "movie"
    merchant: str = ""
    lines: str = ""
    address: str = ""
    movie: str = ""
    when: str = ""
    amount_paise: int = 0
    injection_seen: bool = False
    repaired: bool = False
    extra: dict[str, str] = field(default_factory=dict)


def summarise(f: Facts, lang: str) -> str:
    notes = ""
    if f.injection_seen:
        notes += render("note_injection", lang)
    if f.repaired:
        notes += render("note_repaired", lang)
    common = dict(merchant=f.merchant, lines=f.lines, amount=format_rupees(f.amount_paise),
                  notes=notes)
    if f.use_case == "movie":
        return render("summary_movie", lang, movie=f.movie, when=f.when, **common)
    return render("summary_food", lang, address=f.address, **common)
