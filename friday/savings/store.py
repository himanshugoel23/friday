"""Repositories of the savings engine. Every per-user method filters by ``user_id``.

    repos = SavingsRepos(db, clock)
    await repos.wallet.upsert(card)         # UserCard (encrypted at rest)
    await repos.rules.verified(today)       # only rows that pass the validator
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select

from friday.core.clock import Clock, SystemClock
from friday.core.crypto import get_field_cipher
from friday.db.session import Database
from friday.savings.bills import Bill, BillStatus
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.dbmodel import BillRow, CardRuleRow, SavingsLedgerRow, WalletCardRow
from friday.savings.rules import CardRule, LoadResult, RewardType, load_rules
from friday.savings.savings_ledger import LedgerEntry
from friday.savings.wallet import UserCard

_WALLET_DATA_SKIP = {"id", "user_id", "bank", "card_name"}


def _blind(label: str, value: str) -> str:
    return get_field_cipher().blind_index(value, label=label)


class WalletRepo:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db, self.clock = db, clock or SystemClock()

    @staticmethod
    def _card(r: WalletCardRow) -> UserCard:
        return UserCard.model_validate(
            {**r.data, "id": r.id, "user_id": r.user_id, "bank": r.bank, "card_name": r.card_name}
        )

    async def list(self, user_id: str) -> list[UserCard]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(WalletCardRow)
                    .where(WalletCardRow.user_id == user_id)
                    .order_by(WalletCardRow.created_at, WalletCardRow.id)
                )
            ).scalars()
            return [self._card(r) for r in rows]

    async def get_by_key(self, user_id: str, card_key: str) -> UserCard | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(WalletCardRow).where(
                        WalletCardRow.user_id == user_id,
                        WalletCardRow.card_key_hmac == _blind("wallet", f"{user_id}|{card_key}"),
                    )
                )
            ).scalar_one_or_none()
            return self._card(row) if row else None

    async def upsert(self, card: UserCard) -> UserCard:
        """Insert, or update the row with the same card key. Returns the stored card."""
        if not card.user_id:
            raise ValueError("card.user_id is required")
        fp = _blind("wallet", f"{card.user_id}|{card.card_key}")
        data = card.model_dump(mode="json", exclude=_WALLET_DATA_SKIP)
        now = self.clock.now()
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(WalletCardRow).where(
                        WalletCardRow.user_id == card.user_id, WalletCardRow.card_key_hmac == fp
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = WalletCardRow(id=card.id, user_id=card.user_id, card_key_hmac=fp,
                                    created_at=now)
                s.add(row)
            row.bank, row.card_name, row.data, row.updated_at = (
                card.bank, card.card_name, data, now
            )
            await s.flush()
            return self._card(row)

    async def remove(self, user_id: str, card_key: str) -> bool:
        fp = _blind("wallet", f"{user_id}|{card_key}")
        async with self.db.session() as s:
            res = await s.execute(
                delete(WalletCardRow).where(
                    WalletCardRow.user_id == user_id, WalletCardRow.card_key_hmac == fp
                )
            )
            return bool(res.rowcount)

    async def delete_all(self, user_id: str) -> int:
        async with self.db.session() as s:
            res = await s.execute(delete(WalletCardRow).where(WalletCardRow.user_id == user_id))
            return int(res.rowcount or 0)


def _rule(r: CardRuleRow) -> CardRule:
    return CardRule(
        card_key=r.card_key, bank=r.bank, card_name=r.card_name, category=r.category,
        reward_type=RewardType(r.reward_type), rate_bp=r.rate_bp,
        monthly_cap_paise=r.monthly_cap_paise, per_txn_cap_paise=r.per_txn_cap_paise,
        min_spend_paise=r.min_spend_paise, exclusions=list(r.exclusions or []),
        merchants=list(r.merchants or []), source_url=r.source_url, checked_on=r.checked_on,
        verified_by=r.verified_by, valid_from=r.valid_from, valid_to=r.valid_to, notes=r.notes,
    )


class RulesRepo:
    """The rules table. ``verified`` is what the engine serves; drafts stay out of it."""

    def __init__(
        self, db: Database, clock: Clock | None = None, config: SavingsConfig = DEFAULT_CONFIG
    ) -> None:
        self.db, self.clock, self.config = db, clock or SystemClock(), config

    async def all(self) -> list[CardRule]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(CardRuleRow).order_by(CardRuleRow.card_key, CardRuleRow.scope)
                )
            ).scalars()
            return [_rule(r) for r in rows]

    async def upsert(self, rule: CardRule) -> bool:
        """Insert or replace the row of (card_key, scope). True if it was new. Drafts (no verifier)
        are allowed here; they are simply never served."""
        now = self.clock.now()
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(CardRuleRow).where(
                        CardRuleRow.card_key == rule.card_key, CardRuleRow.scope == rule.scope
                    )
                )
            ).scalar_one_or_none()
            new = row is None
            if row is None:
                row = CardRuleRow(card_key=rule.card_key, scope=rule.scope, created_at=now)
                s.add(row)
            row.bank, row.card_name, row.category = rule.bank, rule.card_name, rule.category
            row.reward_type, row.rate_bp = rule.reward_type.value, rule.rate_bp
            row.monthly_cap_paise, row.per_txn_cap_paise = (
                rule.monthly_cap_paise, rule.per_txn_cap_paise
            )
            row.min_spend_paise = rule.min_spend_paise
            row.exclusions, row.merchants = list(rule.exclusions), list(rule.merchants)
            row.source_url, row.checked_on, row.verified_by = (
                rule.source_url, rule.checked_on, rule.verified_by
            )
            row.valid_from, row.valid_to, row.notes = rule.valid_from, rule.valid_to, rule.notes
            row.updated_at = now
            return new

    async def verify(
        self, card_key: str, scope: str | None, *, by: str, checked_on: date,
        source_url: str | None = None,
    ) -> int:
        """A person confirms row(s) of a card against the public page. Returns rows changed."""
        async with self.db.session() as s:
            q = select(CardRuleRow).where(CardRuleRow.card_key == card_key)
            if scope:
                q = q.where(CardRuleRow.scope == scope)
            rows = list((await s.execute(q)).scalars())
            for r in rows:
                r.verified_by, r.checked_on, r.updated_at = by, checked_on, self.clock.now()
                if source_url:
                    r.source_url = source_url
            return len(rows)

    async def load(self, today: date) -> LoadResult:
        return load_rules(
            await self.all(), today, allow_examples=self.config.allow_example_rules,
            config=self.config,
        )

    async def verified(self, today: date) -> list[CardRule]:
        return (await self.load(today)).accepted

    # RuleSource protocol
    verified_rules = verified


class BillRepo:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db, self.clock = db, clock or SystemClock()

    @staticmethod
    def _bill(r: BillRow) -> Bill:
        return Bill.model_validate(
            {**r.data, "id": r.id, "user_id": r.user_id, "status": r.status,
             "confirmed": r.confirmed, "due_date": r.due_on, "created_at": r.created_at}
        )

    async def save(self, bill: Bill) -> Bill:
        if not bill.user_id:
            raise ValueError("bill.user_id is required")
        data = bill.model_dump(
            mode="json", exclude={"id", "user_id", "status", "confirmed", "due_date", "created_at"}
        )
        now = self.clock.now()
        async with self.db.session() as s:
            row = await s.get(BillRow, bill.id)
            if row is not None and row.user_id != bill.user_id:
                raise PermissionError("bill belongs to another user")
            if row is None:
                row = BillRow(id=bill.id, user_id=bill.user_id, created_at=bill.created_at)
                s.add(row)
            row.status, row.confirmed, row.due_on = bill.status.value, bill.confirmed, bill.due_date
            row.data, row.updated_at = data, now
            return bill

    async def get(self, user_id: str, bill_id: str) -> Bill | None:
        async with self.db.session() as s:
            row = await s.get(BillRow, bill_id)
            return self._bill(row) if row and row.user_id == user_id else None

    async def list_for_user(
        self, user_id: str, *, statuses: tuple[BillStatus, ...] | None = None,
        confirmed_only: bool = True,
    ) -> list[Bill]:
        async with self.db.session() as s:
            q = select(BillRow).where(BillRow.user_id == user_id)
            if confirmed_only:
                q = q.where(BillRow.confirmed.is_(True))
            if statuses:
                q = q.where(BillRow.status.in_([x.value for x in statuses]))
            rows = (await s.execute(q.order_by(BillRow.due_on, BillRow.id))).scalars()
            return [self._bill(r) for r in rows]

    async def active_for_user(self, user_id: str) -> list[Bill]:
        return await self.list_for_user(
            user_id, statuses=(BillStatus.PENDING, BillStatus.SNOOZED)
        )

    async def delete_all(self, user_id: str) -> int:
        async with self.db.session() as s:
            res = await s.execute(delete(BillRow).where(BillRow.user_id == user_id))
            return int(res.rowcount or 0)


class LedgerRepo:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db, self.clock = db, clock or SystemClock()

    @staticmethod
    def _entry(r: SavingsLedgerRow) -> LedgerEntry:
        return LedgerEntry.model_validate({**r.data, "id": r.id, "user_id": r.user_id})

    async def get_by_fingerprint(self, user_id: str, fp: str) -> LedgerEntry | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(SavingsLedgerRow).where(
                        SavingsLedgerRow.user_id == user_id,
                        SavingsLedgerRow.fingerprint_hmac == _blind("ledger", fp),
                    )
                )
            ).scalar_one_or_none()
            return self._entry(row) if row else None

    async def get(self, user_id: str, entry_id: str) -> LedgerEntry | None:
        async with self.db.session() as s:
            row = await s.get(SavingsLedgerRow, entry_id)
            return self._entry(row) if row and row.user_id == user_id else None

    async def add(self, entry: LedgerEntry, fp: str) -> None:
        async with self.db.session() as s:
            s.add(
                SavingsLedgerRow(
                    id=entry.id, user_id=entry.user_id, month=entry.month,
                    fingerprint_hmac=_blind("ledger", fp), outcome=entry.outcome.value,
                    created_at=entry.created_at,
                    data=entry.model_dump(mode="json", exclude={"id", "user_id"}),
                )
            )

    async def save(self, entry: LedgerEntry) -> None:
        async with self.db.session() as s:
            row = await s.get(SavingsLedgerRow, entry.id)
            if row is None or row.user_id != entry.user_id:
                raise KeyError(entry.id)
            row.outcome = entry.outcome.value
            row.data = entry.model_dump(mode="json", exclude={"id", "user_id"})

    async def list_month(self, user_id: str, month: str) -> list[LedgerEntry]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(SavingsLedgerRow)
                    .where(SavingsLedgerRow.user_id == user_id, SavingsLedgerRow.month == month)
                    .order_by(SavingsLedgerRow.created_at, SavingsLedgerRow.id)
                )
            ).scalars()
            return [self._entry(r) for r in rows]

    async def delete_all(self, user_id: str) -> int:
        async with self.db.session() as s:
            res = await s.execute(
                delete(SavingsLedgerRow).where(SavingsLedgerRow.user_id == user_id)
            )
            return int(res.rowcount or 0)


class SavingsRepos:
    """All four stores over one Database (the lead can attach this to ``Repositories``)."""

    def __init__(
        self, db: Database, clock: Clock | None = None, config: SavingsConfig = DEFAULT_CONFIG
    ) -> None:
        self.wallet = WalletRepo(db, clock)
        self.rules = RulesRepo(db, clock, config)
        self.bills = BillRepo(db, clock)
        self.ledger = LedgerRepo(db, clock)
