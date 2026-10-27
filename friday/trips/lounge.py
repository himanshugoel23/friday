"""Lounge hint by card. Says something only when a PERSON-VERIFIED, served perk row matches a card
in the user's wallet; with no rule it says nothing (never guesses). Never mentions upgrades or new
cards (the neutrality rule of docs/SAVINGS_ENGINE.md): it only reads what the user already holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from friday.trips.models import LegKind, TripLeg
from friday.trips.perks import (
    LOUNGE_FOR_DOMESTIC,
    LOUNGE_FOR_INTL,
    CardPerk,
    Confidence,
    PerkSource,
    confidence,
    is_active,
)
from friday.trips.ports import WalletReader


@dataclass(frozen=True)
class LoungeHint:
    card_display: str
    perk: CardPerk
    confidence: Confidence
    airport: str


async def lounge_hints(
    user_id: str, leg: TripLeg, wallet: WalletReader | None, perks: PerkSource | None, today: date
) -> list[LoungeHint]:
    if leg.kind != LegKind.FLIGHT or wallet is None or perks is None:
        return []
    wanted = LOUNGE_FOR_INTL if leg.international else LOUNGE_FOR_DOMESTIC
    served = [
        p for p in await perks.served_perks(today) if p.perk in wanted and is_active(p, today)
    ]
    if not served:
        return []
    out: list[LoungeHint] = []
    for card in await wallet.list(user_id):
        mine = [p for p in served if p.card_key == card.card_key]
        if not mine:
            continue
        # the freshest verified row wins
        best = max(mine, key=lambda p: p.checked_on or date.min)
        out.append(
            LoungeHint(card.display, best, confidence(best, today), (leg.origin or "").upper())
        )
    return out
