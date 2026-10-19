"""The verified card-rules table: model, validator, loader, staleness and CSV import/export.

This module ships the TABLE and the checks. It ships NO real card offers: the only rows in the
repo are clearly marked EXAMPLE rows (fake bank, ``example.invalid`` source) in
``friday/savings/data/example_rules.csv``. Real rows are entered by a person from public bank pages
(see docs/SAVINGS_ENGINE.md) and only rows with a source, a past check date and a named verifier are
ever served.

    result = load_rules(rows, today=today)        # accepted + rejected (with reasons)
    rules_from_csv(text)                          # parse a CSV into rows (errors collected)
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from friday.savings.categories import RULE_CATEGORY_KEYS
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig

EXAMPLE_VERIFIER = "EXAMPLE_NOT_REAL"
# names that are not a person: a rule is verified by a human, never by automation
_NOT_A_PERSON = frozenset(
    {"", "claude", "ai", "bot", "auto", "automatic", "model", "gpt", "llm", "script", "none",
     "unknown", "n/a", "na", "todo", "tbd", "system"}
)


class RewardType(StrEnum):
    CASHBACK = "cashback"
    POINTS = "points"
    DISCOUNT = "discount"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


_NAME_NOISE = frozenset({"card", "cards", "credit", "debit"})


def make_card_key(bank: str, card_name: str) -> str:
    """Stable key shared by the wallet and the rules table: ``<bank-slug>/<card-slug>``.
    Filler words ("card", "credit") are ignored so 'Regalia' and 'Regalia Credit Card' match."""
    tokens = slug(card_name).split("-")
    core = [t for t in tokens if t not in _NAME_NOISE] or tokens
    return f"{slug(bank)}/{'-'.join(core)}"


def _split_list(value: str) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[;|]", value or "") if p.strip()]


class CardRule(BaseModel):
    """One row: what ONE card gives on ONE category (optionally only at some merchants).

    ``rate_bp`` is the reward rate in basis points (500 = 5%). Money is integer paise. For
    ``points`` the rate is the *value* of the points per rupee spent as stated by the source.
    There is deliberately NO field for commission, referral or any revenue: the ranking cannot
    see one (``extra='forbid'`` also rejects such a column in an import).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    card_key: str = ""
    bank: str
    card_name: str
    category: str
    reward_type: RewardType
    rate_bp: int = Field(ge=0)
    monthly_cap_paise: int | None = Field(default=None, ge=0)  # cap on the REWARD per month
    per_txn_cap_paise: int | None = Field(default=None, ge=0)  # cap on the REWARD per payment
    min_spend_paise: int = Field(default=0, ge=0)  # payment must be at least this
    exclusions: list[str] = Field(default_factory=list)  # category or merchant keys: no reward
    merchants: list[str] = Field(default_factory=list)  # empty = the whole category
    source_url: str = ""
    checked_on: date | None = None
    verified_by: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str = ""

    @field_validator("category")
    @classmethod
    def _category_known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in RULE_CATEGORY_KEYS:
            raise ValueError(f"unknown category {v!r}")
        return v

    @field_validator("exclusions", "merchants")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return sorted({x.strip().lower() for x in v if x.strip()})

    @model_validator(mode="after")
    def _fill_key(self) -> CardRule:
        if not self.card_key:
            self.card_key = make_card_key(self.bank, self.card_name)
        return self

    @property
    def scope(self) -> str:
        """Row identity inside a card: category plus merchant list."""
        return f"{self.category}@{','.join(self.merchants)}" if self.merchants else self.category

    @property
    def is_example(self) -> bool:
        return is_example(self)


# ------------------------------------------------------------------ validation


@dataclass(frozen=True)
class RuleIssue:
    code: str
    message: str


def is_example(rule: CardRule) -> bool:
    host = (urlsplit(rule.source_url).hostname or "").lower()
    return (
        host.endswith(".invalid")
        or rule.bank.lower().startswith("example")
        or rule.verified_by == EXAMPLE_VERIFIER
    )


def validate_rule(
    rule: CardRule,
    today: date,
    *,
    require_verified: bool = True,
    allow_examples: bool = False,
    config: SavingsConfig = DEFAULT_CONFIG,
) -> list[RuleIssue]:
    """Everything wrong with a row. Empty list = the row may be served."""
    issues: list[RuleIssue] = []
    src = rule.source_url.strip()
    if not src:
        issues.append(RuleIssue("missing_source", "source_url is required (a public bank page)"))
    else:
        parts = urlsplit(src)
        if parts.scheme not in {"http", "https"} or not parts.hostname or "." not in parts.hostname:
            issues.append(RuleIssue("bad_source_url", f"source_url is not a web link: {src[:60]}"))
    if rule.checked_on is None:
        issues.append(RuleIssue("missing_checked_on", "checked_on date is required"))
    elif rule.checked_on > today:
        issues.append(
            RuleIssue("future_checked_on", f"checked_on {rule.checked_on} is in the future")
        )
    if require_verified:
        who = (rule.verified_by or "").strip().lower()
        if who in _NOT_A_PERSON:
            issues.append(
                RuleIssue("unverified", "verified_by must name the person who checked it")
            )
    cap = (
        config.max_rate_bp_discount
        if rule.reward_type == RewardType.DISCOUNT
        else config.max_rate_bp_reward
    )
    if not 0 < rule.rate_bp <= cap:
        issues.append(RuleIssue("rate_out_of_range", f"rate_bp {rule.rate_bp} not in 1..{cap}"))
    if rule.valid_from and rule.valid_to and rule.valid_from > rule.valid_to:
        issues.append(RuleIssue("bad_validity_window", "valid_from is after valid_to"))
    if not rule.bank.strip() or not rule.card_name.strip():
        issues.append(RuleIssue("missing_card", "bank and card_name are required"))
    if is_example(rule) and not allow_examples:
        issues.append(RuleIssue("example_row", "EXAMPLE row: not a real offer, never served"))
    return issues


# ------------------------------------------------------------------ staleness


Freshness = Literal["fresh", "stale", "very_stale", "unknown"]


def rule_age_days(rule: CardRule, today: date) -> int | None:
    return None if rule.checked_on is None else (today - rule.checked_on).days


def freshness(rule: CardRule, today: date, config: SavingsConfig = DEFAULT_CONFIG) -> Freshness:
    age = rule_age_days(rule, today)
    if age is None:
        return "unknown"
    if age > config.very_stale_after_days:
        return "very_stale"
    if age > config.stale_after_days:
        return "stale"
    return "fresh"


def is_active(rule: CardRule, today: date) -> bool:
    """Inside its validity window (open ends allowed)."""
    return (rule.valid_from is None or rule.valid_from <= today) and (
        rule.valid_to is None or today <= rule.valid_to
    )


# ------------------------------------------------------------------ loader


@dataclass(frozen=True)
class RejectedRule:
    rule: CardRule
    issues: list[RuleIssue]


@dataclass
class LoadResult:
    accepted: list[CardRule] = field(default_factory=list)
    rejected: list[RejectedRule] = field(default_factory=list)

    def summary(self) -> str:
        return f"{len(self.accepted)} accepted, {len(self.rejected)} rejected"


def load_rules(
    rules: list[CardRule],
    today: date,
    *,
    allow_examples: bool = False,
    config: SavingsConfig = DEFAULT_CONFIG,
) -> LoadResult:
    """Keep only rows that pass the validator. Unverified rows are refused, not downgraded."""
    out = LoadResult()
    seen: set[tuple[str, str]] = set()
    for r in rules:
        issues = validate_rule(r, today, allow_examples=allow_examples, config=config)
        ident = (r.card_key, r.scope)
        if ident in seen:
            issues.append(RuleIssue("duplicate", f"two rows for {r.card_key} / {r.scope}"))
        seen.add(ident)
        if issues:
            out.rejected.append(RejectedRule(r, issues))
        else:
            out.accepted.append(r)
    return out


class RuleSource:
    """What the calculator and the handlers need from a rules store: verified rows for a day."""

    async def verified_rules(self, today: date) -> list[CardRule]:  # pragma: no cover - protocol
        raise NotImplementedError


# ------------------------------------------------------------------ CSV

CSV_COLUMNS = (
    "bank", "card_name", "category", "reward_type", "rate_bp", "monthly_cap_paise",
    "per_txn_cap_paise", "min_spend_paise", "exclusions", "merchants", "source_url",
    "checked_on", "verified_by", "valid_from", "valid_to", "notes",
)


@dataclass(frozen=True)
class CsvRow:
    line: int
    rule: CardRule | None
    error: str | None = None


def _opt_int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


def _opt_date(v: str | None) -> date | None:
    v = (v or "").strip()
    return date.fromisoformat(v) if v else None


def rules_from_csv(text: str) -> list[CsvRow]:
    """Parse CSV text. A bad row becomes ``CsvRow(error=...)``; the others still parse.
    An unknown column (e.g. ``commission_bp``) is an error for every row."""
    reader = csv.DictReader(io.StringIO(text))
    unknown = [c for c in (reader.fieldnames or []) if c and c.strip() not in CSV_COLUMNS]
    if unknown:
        return [CsvRow(1, None, f"unknown column(s): {', '.join(unknown)}")]
    rows: list[CsvRow] = []
    for i, raw in enumerate(reader, start=2):
        raw = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(raw.values()):
            continue
        try:
            rule = CardRule(
                bank=raw.get("bank", ""),
                card_name=raw.get("card_name", ""),
                category=raw.get("category", ""),
                reward_type=raw.get("reward_type", "").lower(),  # type: ignore[arg-type]
                rate_bp=int(raw.get("rate_bp") or -1),
                monthly_cap_paise=_opt_int(raw.get("monthly_cap_paise")),
                per_txn_cap_paise=_opt_int(raw.get("per_txn_cap_paise")),
                min_spend_paise=_opt_int(raw.get("min_spend_paise")) or 0,
                exclusions=_split_list(raw.get("exclusions", "")),
                merchants=_split_list(raw.get("merchants", "")),
                source_url=raw.get("source_url", ""),
                checked_on=_opt_date(raw.get("checked_on")),
                verified_by=raw.get("verified_by") or None,
                valid_from=_opt_date(raw.get("valid_from")),
                valid_to=_opt_date(raw.get("valid_to")),
                notes=raw.get("notes", ""),
            )
            rows.append(CsvRow(i, rule))
        except (ValueError, TypeError) as e:
            rows.append(CsvRow(i, None, str(e).splitlines()[0][:200]))
    return rows


def rules_to_csv(rules: list[CardRule]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rules:
        w.writerow(
            [
                r.bank, r.card_name, r.category, r.reward_type.value, r.rate_bp,
                "" if r.monthly_cap_paise is None else r.monthly_cap_paise,
                "" if r.per_txn_cap_paise is None else r.per_txn_cap_paise,
                r.min_spend_paise, ";".join(r.exclusions), ";".join(r.merchants), r.source_url,
                r.checked_on or "", r.verified_by or "", r.valid_from or "", r.valid_to or "",
                r.notes,
            ]
        )
    return buf.getvalue()


def load_example_rules() -> list[CardRule]:
    """The EXAMPLE rows bundled with the package (fake bank, example.invalid source). For tests,
    demos and the CLI's dry runs only: the loader refuses them unless ``allow_examples`` is set."""
    from importlib.resources import files

    text = files("friday.savings").joinpath("data/example_rules.csv").read_text(encoding="utf-8")
    rows = rules_from_csv(text)
    bad = [r for r in rows if r.rule is None]
    if bad:  # a broken bundled file is a bug, not user input
        raise ValueError(f"example_rules.csv line {bad[0].line}: {bad[0].error}")
    return [r.rule for r in rows if r.rule is not None]
