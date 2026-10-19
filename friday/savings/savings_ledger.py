"""The savings ledger: every recommendation and what the user says they did.

"Friday ne is mahine Rs X bachaye" is computed ONLY from entries the user confirmed:

* an entry counts when the user reports "used the recommended card" (one confirmation, final);
* the saving is the recommended card's reward minus a stated counterfactual, floored at 0:
  the card the user marked as usual, else the next-best card in their wallet; with a single card
  there is nothing to compare to and the saving is Rs 0 (we do not invent a comparison);
* entries from low-confidence rules (stale or unverified) are logged but never counted;
* the same purchase asked twice on one day is ONE entry, and a confirmation is idempotent, so
  nothing is counted twice.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import Clock, ist_date
from friday.core.models import new_id
from friday.savings.calculator import Confidence, Ranking
from friday.savings.wallet import UserCard


class Outcome(StrEnum):
    PENDING = "pending"
    USED_RECOMMENDED = "used_recommended"
    USED_OTHER = "used_other"
    SKIPPED = "skipped"  # did not buy / not using a card


class BaselineKind(StrEnum):
    USUAL_CARD = "usual_card"
    NEXT_BEST = "next_best"
    NONE = "none"


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str
    on_date: date  # IST date of the recommendation
    created_at: datetime
    spend_paise: int
    category: str
    merchant: str | None = None
    recommended_card_key: str
    recommended_reward_paise: int
    rule_scope: str = ""  # the cap key the reward counts against
    confidence: int  # Confidence permille at recommendation time
    baseline_kind: BaselineKind = BaselineKind.NONE
    baseline_card_key: str | None = None
    baseline_reward_paise: int = 0
    outcome: Outcome = Outcome.PENDING
    used_card_key: str | None = None
    confirmed_at: datetime | None = None
    saved_paise: int = 0  # set once, when the user confirms "used_recommended"

    @property
    def month(self) -> str:
        return f"{self.on_date:%Y-%m}"

    @property
    def counted(self) -> bool:
        """Does this entry contribute to the monthly figure?"""
        return (
            self.outcome == Outcome.USED_RECOMMENDED
            and self.confirmed_at is not None
            and self.confidence > int(Confidence.LOW)
        )


def fingerprint_source(
    user_id: str, on_date: date, spend_paise: int, category: str, merchant: str | None
) -> str:
    """What makes two asks 'the same purchase' (hashed by the store with the blind-index key)."""
    raw = f"{user_id}|{on_date.isoformat()}|{spend_paise}|{category}|{merchant or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


class LedgerStore(Protocol):
    async def get_by_fingerprint(self, user_id: str, fp: str) -> LedgerEntry | None: ...
    async def get(self, user_id: str, entry_id: str) -> LedgerEntry | None: ...
    async def add(self, entry: LedgerEntry, fp: str) -> None: ...
    async def save(self, entry: LedgerEntry) -> None: ...
    async def list_month(self, user_id: str, month: str) -> list[LedgerEntry]: ...


def _baseline(
    ranking: Ranking, wallet: list[UserCard]
) -> tuple[BaselineKind, str | None, int]:
    top = ranking.top
    if top is None:
        return BaselineKind.NONE, None, 0
    usual = next((c for c in wallet if c.usual), None)
    if usual is not None:
        other = next((o for o in ranking.options if o.card_key == usual.card_key), None)
        if other is not None:
            return BaselineKind.USUAL_CARD, other.card_key, other.reward_paise
    for o in ranking.options:
        if o.card_key != top.card_key:
            return BaselineKind.NEXT_BEST, o.card_key, o.reward_paise
    return BaselineKind.NONE, None, 0


class SavingsLedger:
    def __init__(self, store: LedgerStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    async def record_recommendation(
        self, user_id: str, ranking: Ranking, wallet: list[UserCard]
    ) -> LedgerEntry | None:
        """Log what was recommended. Returns the existing entry when the same purchase was
        already asked today. None when there is no ranked card (nothing was recommended)."""
        top = ranking.top
        if top is None:
            return None
        now = self.clock.now()
        today = ist_date(now)
        fp = fingerprint_source(
            user_id, today, ranking.spend_paise, ranking.category, ranking.merchant
        )
        existing = await self.store.get_by_fingerprint(user_id, fp)
        if existing is not None:
            return existing
        kind, base_key, base_reward = _baseline(ranking, wallet)
        entry = LedgerEntry(
            user_id=user_id,
            on_date=today,
            created_at=now,
            spend_paise=ranking.spend_paise,
            category=ranking.category,
            merchant=ranking.merchant,
            recommended_card_key=top.card_key,
            recommended_reward_paise=top.reward_paise,
            rule_scope=top.rule_scope,
            confidence=int(top.confidence),
            baseline_kind=kind,
            baseline_card_key=base_key,
            baseline_reward_paise=base_reward,
        )
        await self.store.add(entry, fp)
        return entry

    async def report_outcome(
        self,
        user_id: str,
        entry_id: str,
        outcome: Outcome,
        used_card_key: str | None = None,
    ) -> tuple[LedgerEntry | None, bool]:
        """The user's answer. Returns (entry, changed). Only the FIRST answer is kept: a repeated
        tap or message never changes (or re-counts) a settled entry."""
        entry = await self.store.get(user_id, entry_id)
        if entry is None:
            return None, False
        if entry.outcome != Outcome.PENDING or outcome == Outcome.PENDING:
            return entry, False
        entry.outcome = outcome
        entry.confirmed_at = self.clock.now()
        if outcome == Outcome.USED_RECOMMENDED:
            entry.used_card_key = entry.recommended_card_key
            if entry.baseline_kind != BaselineKind.NONE:  # no counterfactual -> nothing saved
                entry.saved_paise = max(
                    0, entry.recommended_reward_paise - entry.baseline_reward_paise
                )
        elif outcome == Outcome.USED_OTHER:
            entry.used_card_key = used_card_key
        await self.store.save(entry)
        return entry, True

    async def month_entries(self, user_id: str, month: str) -> list[LedgerEntry]:
        return await self.store.list_month(user_id, month)

    async def monthly_summary(self, user_id: str, month: str | None = None) -> MonthlySummary:
        month = month or f"{ist_date(self.clock.now()):%Y-%m}"
        entries = await self.store.list_month(user_id, month)
        counted = [e for e in entries if e.counted]
        return MonthlySummary(
            month=month,
            saved_paise=sum(e.saved_paise for e in counted),
            counted=len(counted),
            logged=len(entries),
            awaiting_answer=sum(1 for e in entries if e.outcome == Outcome.PENDING),
            low_confidence_not_counted=sum(
                1
                for e in entries
                if e.outcome == Outcome.USED_RECOMMENDED and not e.counted
            ),
            baselines=sorted({e.baseline_kind.value for e in counted}),
        )


class MonthlySummary(BaseModel):
    month: str
    saved_paise: int
    counted: int
    logged: int
    awaiting_answer: int
    low_confidence_not_counted: int
    baselines: list[str]
