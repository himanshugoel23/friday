"""Scam / fake-number check (B16, C26, B-11) before calling or sharing details.

Signals, combined into a 0..1 trust score (0.5 = no evidence either way):

* known-scam list (bundled data + ``Settings.scam_numbers_path`` + simworld ``scam``)
  -> SCAM, never call, never share
* official customer-care directory match                         ++
* claims to be <company> but is not on its official list         --
  ... and is a personal mobile number                            -- (big-brand "care" mobiles)
* directory listings cross-check for the claimed name:
  several consistent listings ++ / one +; listings show a different number --
* listing quality: very few reviews -, reviews reporting fraud/OTP asks --
* Friday's own call history with the number (vendor memory), weighted by recency
  and by its last verdict                                         + / ++

Verdict: SCAM (listed) | SUSPICIOUS (< 0.35) | UNKNOWN | TRUSTED (>= 0.75).
``warn_user`` for SUSPICIOUS/SCAM; ``warning_text`` renders the user-facing warning.
"""

from __future__ import annotations

import contextlib
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from friday.core.clock import Clock, SystemClock
from friday.core.interfaces import (
    BusinessDirectory,
    BusinessRepository,
    OfficialNumberDirectory,
    ProviderError,
)
from friday.core.logging import get_logger, mask_phone
from friday.core.models import NumberCheck, NumberVerdict
from friday.discovery.geo import is_indian_mobile, names_match, phone_key
from friday.simworld import SimWorld, load_world

log = get_logger(__name__)

SCAM_LIST_PATH = Path(__file__).with_name("data") / "scam_numbers.txt"
SUSPICIOUS_BELOW = 0.35
TRUSTED_FROM = 0.75
_FRAUD_WORDS = re.compile(r"\b(scam|fraud|fake|otp|cheat(ed)?|never came|advance and)\b", re.I)


def load_scam_list(*paths: str | Path | None) -> set[str]:
    out: set[str] = set()
    for p in paths:
        if not p:
            continue
        path = Path(p)
        if not path.exists():
            log.warning("scam list %s not found", path)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(phone_key(line))
    return out


class NumberVerifierImpl:
    """``NumberVerifier``. Dependencies are optional; missing ones just give no signal."""

    def __init__(
        self,
        *,
        scam_numbers: set[str] | None = None,
        official: OfficialNumberDirectory | None = None,
        directory: BusinessDirectory | None = None,
        businesses: BusinessRepository | None = None,
        clock: Clock | None = None,
        listing_location: str = "",
    ) -> None:
        self.scam = {phone_key(p) for p in (scam_numbers or set())}
        self.official = official
        self.directory = directory
        self.businesses = businesses
        self.clock = clock or SystemClock()
        self.listing_location = listing_location

    async def verify(
        self, phone: str, *, claimed_name: str | None = None, company: str | None = None
    ) -> NumberCheck:
        now = self.clock.now()
        key = phone_key(phone)
        if key in self.scam:
            return NumberCheck(
                phone=phone,
                verdict=NumberVerdict.SCAM,
                score=0.0,
                signals=["on the known-scam list"],
                warn_user=True,
                checked_at=now,
            )
        score = 0.5
        signals: list[str] = []

        # ---- official directory (C26)
        if self.official is not None:
            match = await self.official.find_by_phone(phone)
            if match:
                score += 0.45
                signals.append(f"on {match.company}'s official customer-care list")
            elif company:
                listed = await self.official.lookup(company)
                if listed:
                    score -= 0.35
                    signals.append(f"not on {company}'s official customer-care list")
                    if is_indian_mobile(phone):
                        score -= 0.2
                        signals.append(f"a personal mobile number claiming to be {company}")
                elif is_indian_mobile(phone):
                    score -= 0.1
                    signals.append(f"{company} is not in the verified directory yet")

        # ---- directory listings cross-check (B-11)
        name = claimed_name or company
        if self.directory is not None and name:
            score += await self._listing_signals(phone, name, signals)

        # ---- Friday's own call history (B-11)
        if self.businesses is not None:
            score += await self._history_signals(phone, signals, now)

        score = max(0.0, min(1.0, round(score, 3)))
        if score < SUSPICIOUS_BELOW:
            verdict = NumberVerdict.SUSPICIOUS
        elif score >= TRUSTED_FROM:
            verdict = NumberVerdict.TRUSTED
        else:
            verdict = NumberVerdict.UNKNOWN
        log.info("verified %s -> %s (%.2f)", mask_phone(phone), verdict, score)
        return NumberCheck(
            phone=phone,
            verdict=verdict,
            score=score,
            signals=signals,
            warn_user=verdict in (NumberVerdict.SUSPICIOUS, NumberVerdict.SCAM),
            checked_at=now,
        )

    async def _listing_signals(self, phone: str, name: str, signals: list[str]) -> float:
        key = phone_key(phone)
        try:
            results = await self.directory.search(name, self.listing_location, limit=5)
        except ProviderError as e:
            log.warning("listing check failed: %s", e)
            return 0.0
        consistent = conflicting = 0
        few_reviews = fraud = False
        for cand in results:
            if not names_match(name, cand.name):
                continue
            if cand.phone is None or not cand.review_snippets:
                with contextlib.suppress(ProviderError):
                    cand = await self.directory.details(cand.place_id) or cand
            if not cand.phone:
                continue
            if phone_key(cand.phone) == key:
                consistent += 1
                if cand.review_count < 5:
                    few_reviews = True
                if any(_FRAUD_WORDS.search(s) for s in cand.review_snippets):
                    fraud = True
            else:
                conflicting += 1
        delta = 0.0
        if consistent >= 2:
            delta += 0.3
            signals.append(f"{consistent} consistent directory listings")
        elif consistent == 1:
            delta += 0.15
            signals.append("matches the directory listing")
        elif conflicting:
            delta -= 0.2
            signals.append(f"listings for {name} show a different number")
        if few_reviews:
            delta -= 0.05
            signals.append("listing has very few reviews")
        if fraud:
            delta -= 0.35
            signals.append("reviews report fraud or OTP requests")
        return delta

    async def _history_signals(self, phone: str, signals: list[str], now) -> float:
        try:
            biz = await self.businesses.get_by_phone(phone)
        except Exception as e:  # repository not ready / transient
            log.warning("call-history check failed: %r", e)
            return 0.0
        if biz is None:
            return 0.0
        delta = 0.0
        if biz.verification == NumberVerdict.SCAM:
            delta -= 0.5
            signals.append("previously flagged as a scam")
        elif biz.verification == NumberVerdict.SUSPICIOUS:
            delta -= 0.1
            signals.append("previously flagged as suspicious")
        if biz.last_called_at is not None:
            recent = now - biz.last_called_at <= timedelta(days=180)
            delta += 0.2 if recent else 0.1
            signals.append("Friday has called this number before")
            if biz.verification == NumberVerdict.TRUSTED:
                delta += 0.1
        return delta


def warning_text(check: NumberCheck, name: str | None = None) -> str | None:
    """User-facing warning (US-25.2) or None when no warning is needed."""
    who = name or "this business"
    if check.verdict == NumberVerdict.SCAM:
        return (
            f"⚠ The number given for {who} is on a known-scam list, so I won't call it "
            "or share anything with it."
        )
    if not check.warn_user:
        return None
    reasons = "; ".join(check.signals[:3]) or "I couldn't verify it"
    return f"⚠ I couldn't verify the number for {who}: {reasons}. Still call?"


def build_number_verifier(c) -> NumberVerifierImpl:  # c: Container
    s = c.settings
    scam = load_scam_list(SCAM_LIST_PATH, s.scam_numbers_path)
    if not s.is_live:
        world: SimWorld = load_world()
        scam |= {phone_key(b.phone) for b in world.businesses if b.scam}
    return NumberVerifierImpl(
        scam_numbers=scam,
        official=_optional(c, "official_numbers"),
        directory=_optional(c, "directory"),
        businesses=getattr(_optional(c, "repos"), "businesses", None),
        clock=c.clock,
    )


def _optional(c, name: str) -> Any:
    try:
        return c.get(name)
    except Exception as e:  # ComponentNotAvailable / missing key - signal just absent
        log.info("number verifier: %s unavailable (%s)", name, type(e).__name__)
        return None
