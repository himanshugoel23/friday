"""Savings engine v1 (workstream W3): which of MY cards, and my bills. No sales pitch.

  wallet.py          the user's cards by bank + card NAME (never numbers), parsing, encrypted store
  rules.py           the verified card-rules table: model, validator, loader, staleness, CSV
  calculator.py      best_card(): pure, deterministic ranking; every rupee from the rules table
  categories.py      "Zomato pe 640" -> amount, category, merchant (keyword tables)
  bills.py           bill intake (forwarded text), confirmation, reminders for the proactive engine
  savings_ledger.py  recommendations + user-confirmed outcomes -> the monthly "Friday saved" figure
  commands.py        thin WhatsApp command handlers (the front door calls these)
  copy.py            ALL user-facing text (PENDING_FOUNDER_APPROVAL)
  store.py / dbmodel.py   repositories and tables (migration 0008)
  cli.py             `friday savings rules import|verify|list|export`

Design and process: docs/SAVINGS_ENGINE.md.
"""

from friday.savings.calculator import Confidence, Option, Ranking, best_card
from friday.savings.rules import CardRule, load_rules, validate_rule
from friday.savings.wallet import UserCard

__all__ = [
    "CardRule",
    "Confidence",
    "Option",
    "Ranking",
    "UserCard",
    "best_card",
    "load_rules",
    "validate_rule",
]
