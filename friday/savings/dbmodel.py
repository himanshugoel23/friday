"""Tables of the savings engine (migration 0008_savings_engine).

* ``wallet_cards``: one row per card a user holds. Bank, card NAME and every optional figure are
  encrypted (AES-GCM, AAD ``table.column``). There is no column for a number, CVV, expiry, OTP or
  PIN, and none is ever accepted. ``card_key_hmac`` is a blind index so a card is stored once.
* ``card_rules``: the verified rules table. Shared (not per user) and holds no personal data.
  There is no revenue or commission column.
* ``bills``: bills the user asked to track. ``due_on`` and ``status`` are plain (the reminder
  scan needs them); biller, amount and pay link are encrypted.
* ``savings_ledger``: recommendations and outcomes; spend, card and saving are encrypted.

``user_id`` is the erasure key of the per-user tables (DataPurger deletes by it).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from friday.core.clock import utcnow
from friday.core.crypto import EncryptedJSON, EncryptedText
from friday.db.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime


def _user_fk() -> Mapped[str]:
    return mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class WalletCardRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "wallet_cards"
    __table_args__ = (UniqueConstraint("user_id", "card_key_hmac"),)

    user_id: Mapped[str] = _user_fk()
    card_key_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    bank: Mapped[str] = mapped_column(EncryptedText("wallet_cards.bank"), nullable=False)
    card_name: Mapped[str] = mapped_column(EncryptedText("wallet_cards.card_name"), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON("wallet_cards.data"), nullable=False
    )


class CardRuleRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "card_rules"
    __table_args__ = (UniqueConstraint("card_key", "scope"),)

    card_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(200), nullable=False)  # category[@merchants]
    bank: Mapped[str] = mapped_column(String(80), nullable=False)
    card_name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(12), nullable=False)
    rate_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_cap_paise: Mapped[int | None] = mapped_column(Integer)
    per_txn_cap_paise: Mapped[int | None] = mapped_column(Integer)
    min_spend_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusions: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    merchants: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checked_on: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[str | None] = mapped_column(String(100))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BillRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "bills"

    user_id: Mapped[str] = _user_fk()
    status: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON("bills.data"), nullable=False)


class SavingsLedgerRow(IdMixin, Base):
    __tablename__ = "savings_ledger"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint_hmac"),)

    user_id: Mapped[str] = _user_fk()
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    fingerprint_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON("savings_ledger.data"), nullable=False
    )


__all__ = ["BillRow", "CardRuleRow", "SavingsLedgerRow", "WalletCardRow"]
