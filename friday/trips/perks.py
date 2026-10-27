# ruff: noqa: E501
"""The verified card-perks table (lounge access): model, validator, loader, CSV.

Same discipline as ``friday.savings.rules`` (it reuses its checks and constants): this module ships
the TABLE and the validator, NO real card offers. The only rows in the repo are EXAMPLE rows (fake
bank, ``example.invalid`` source) in ``friday/trips/data/example_perks.csv``. A row is served only
with a public source link, a past check date and a named PERSON as verifier (never "claude", "ai",
"bot"...), is marked ``served`` by that person, and is not an example (unless the dev flag is on).
There is no field for commission, referral or revenue.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.rules import _NOT_A_PERSON, EXAMPLE_VERIFIER, make_card_key


class PerkKind(StrEnum):
    DOMESTIC_LOUNGE = "domestic_lounge"
    INTL_LOUNGE = "intl_lounge"
    PRIORITY_PASS = "priority_pass"  # noqa: S105 - a perk name, not a secret
    GUEST_ACCESS = "guest_access"


LOUNGE_FOR_DOMESTIC = (PerkKind.DOMESTIC_LOUNGE, PerkKind.PRIORITY_PASS)
LOUNGE_FOR_INTL = (PerkKind.INTL_LOUNGE, PerkKind.PRIORITY_PASS)


class CardPerk(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    card_key: str = ""
    bank: str
    card_name: str
    perk: PerkKind
    visits_per_period: int | None = Field(default=None, ge=0)
    period: str = ""  # "quarter" | "year" | "month" | "" (as the source states it)
    conditions_text: str = Field(default="", max_length=400)
    min_spend_paise: int = Field(default=0, ge=0)
    valid_from: date | None = None
    valid_to: date | None = None
    source_url: str = ""
    checked_on: date | None = None
    verified_by: str | None = None
    status: Literal["draft", "served"] = "draft"  # a person flips it to served

    @model_validator(mode="after")
    def _fill_key(self) -> CardPerk:
        if not self.card_key:
            self.card_key = make_card_key(self.bank, self.card_name)
        return self

    @property
    def ident(self) -> tuple[str, str]:
        return (self.card_key, self.perk.value)

    @property
    def is_example(self) -> bool:
        return is_example_perk(self)


def is_example_perk(p: CardPerk) -> bool:
    host = (urlsplit(p.source_url).hostname or "").lower()
    return (
        host.endswith(".invalid")
        or p.bank.lower().startswith("example")
        or p.verified_by == EXAMPLE_VERIFIER
    )


@dataclass(frozen=True)
class PerkIssue:
    code: str
    message: str


def validate_perk(p: CardPerk, today: date, *, allow_examples: bool = False) -> list[PerkIssue]:
    """Everything wrong with a row. Empty list = the row may be served."""
    issues: list[PerkIssue] = []
    src = p.source_url.strip()
    if not src:
        issues.append(PerkIssue("missing_source", "source_url is required (a public bank page)"))
    else:
        parts = urlsplit(src)
        if parts.scheme not in {"http", "https"} or not parts.hostname or "." not in parts.hostname:
            issues.append(PerkIssue("bad_source_url", f"source_url is not a web link: {src[:60]}"))
    if p.checked_on is None:
        issues.append(PerkIssue("missing_checked_on", "checked_on date is required"))
    elif p.checked_on > today:
        issues.append(PerkIssue("future_checked_on", f"checked_on {p.checked_on} is in the future"))
    if (p.verified_by or "").strip().lower() in _NOT_A_PERSON:
        issues.append(PerkIssue("unverified", "verified_by must name the person who checked it"))
    if p.valid_from and p.valid_to and p.valid_from > p.valid_to:
        issues.append(PerkIssue("bad_validity_window", "valid_from is after valid_to"))
    if not p.bank.strip() or not p.card_name.strip():
        issues.append(PerkIssue("missing_card", "bank and card_name are required"))
    if p.status != "served":
        issues.append(PerkIssue("draft", "a person must mark the row served"))
    if is_example_perk(p) and not allow_examples:
        issues.append(PerkIssue("example_row", "EXAMPLE row: not a real offer, never served"))
    return issues


Confidence = Literal["high", "medium", "low", "unknown"]


def age_days(p: CardPerk, today: date) -> int | None:
    return None if p.checked_on is None else (today - p.checked_on).days


def confidence(p: CardPerk, today: date, config: SavingsConfig = DEFAULT_CONFIG) -> Confidence:
    """HIGH within 30 days of the check, MEDIUM up to 90, LOW beyond (the savings thresholds)."""
    age = age_days(p, today)
    if age is None:
        return "unknown"
    if age > config.very_stale_after_days:
        return "low"
    if age > config.stale_after_days:
        return "medium"
    return "high"


def is_active(p: CardPerk, today: date) -> bool:
    return (p.valid_from is None or p.valid_from <= today) and (
        p.valid_to is None or today <= p.valid_to
    )


@dataclass(frozen=True)
class RejectedPerk:
    perk: CardPerk
    issues: list[PerkIssue]


@dataclass
class PerkLoadResult:
    accepted: list[CardPerk] = field(default_factory=list)
    rejected: list[RejectedPerk] = field(default_factory=list)


def load_perks(
    perks: list[CardPerk], today: date, *, allow_examples: bool = False
) -> PerkLoadResult:
    out = PerkLoadResult()
    seen: set[tuple[str, str]] = set()
    for p in perks:
        issues = validate_perk(p, today, allow_examples=allow_examples)
        if p.ident in seen:
            issues.append(PerkIssue("duplicate", f"two rows for {p.card_key} / {p.perk.value}"))
        seen.add(p.ident)
        (out.rejected.append(RejectedPerk(p, issues)) if issues else out.accepted.append(p))
    return out


# ------------------------------------------------------------------ CSV
CSV_COLUMNS = (
    "bank",
    "card_name",
    "perk",
    "visits_per_period",
    "period",
    "conditions_text",
    "min_spend_paise",
    "valid_from",
    "valid_to",
    "source_url",
    "checked_on",
    "verified_by",
    "status",
)


@dataclass(frozen=True)
class PerkCsvRow:
    line: int
    perk: CardPerk | None
    error: str | None = None


def _opt_date(v: str | None) -> date | None:
    v = (v or "").strip()
    return date.fromisoformat(v) if v else None


def perks_from_csv(text: str) -> list[PerkCsvRow]:
    """A bad row becomes an error row; an unknown column (e.g. ``commission``) rejects the file."""
    reader = csv.DictReader(io.StringIO(text))
    unknown = [c for c in (reader.fieldnames or []) if c and c.strip() not in CSV_COLUMNS]
    if unknown:
        return [PerkCsvRow(1, None, f"unknown column(s): {', '.join(unknown)}")]
    rows: list[PerkCsvRow] = []
    for i, raw in enumerate(reader, start=2):
        raw = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(raw.values()):
            continue
        try:
            visits = raw.get("visits_per_period", "")
            rows.append(
                PerkCsvRow(
                    i,
                    CardPerk(
                        bank=raw.get("bank", ""),
                        card_name=raw.get("card_name", ""),
                        perk=raw.get("perk", "").lower(),  # type: ignore[arg-type]
                        visits_per_period=int(visits) if visits else None,
                        period=raw.get("period", ""),
                        conditions_text=raw.get("conditions_text", ""),
                        min_spend_paise=int(raw.get("min_spend_paise") or 0),
                        valid_from=_opt_date(raw.get("valid_from")),
                        valid_to=_opt_date(raw.get("valid_to")),
                        source_url=raw.get("source_url", ""),
                        checked_on=_opt_date(raw.get("checked_on")),
                        verified_by=raw.get("verified_by") or None,
                        status=(raw.get("status") or "draft").lower(),  # type: ignore[arg-type]
                    ),
                )
            )
        except (ValueError, TypeError) as e:
            rows.append(PerkCsvRow(i, None, str(e).splitlines()[0][:200]))
    return rows


def perks_to_csv(perks: list[CardPerk]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for p in perks:
        w.writerow(
            [
                p.bank,
                p.card_name,
                p.perk.value,
                "" if p.visits_per_period is None else p.visits_per_period,
                p.period,
                p.conditions_text,
                p.min_spend_paise,
                p.valid_from or "",
                p.valid_to or "",
                p.source_url,
                p.checked_on or "",
                p.verified_by or "",
                p.status,
            ]
        )
    return buf.getvalue()


def load_example_perks() -> list[CardPerk]:
    """The EXAMPLE rows bundled with the package (fake bank, example.invalid). Dev and tests only."""
    from importlib.resources import files

    text = files("friday.trips").joinpath("data/example_perks.csv").read_text(encoding="utf-8")
    rows = perks_from_csv(text)
    bad = [r for r in rows if r.perk is None]
    if bad:
        raise ValueError(f"example_perks.csv line {bad[0].line}: {bad[0].error}")
    return [r.perk for r in rows if r.perk is not None]


class PerkSource:
    """What the lounge hint needs: served perks for a day."""

    async def served_perks(self, today: date) -> list[CardPerk]:  # pragma: no cover - protocol
        raise NotImplementedError
