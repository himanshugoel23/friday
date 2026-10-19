"""Deterministic abuse and safety classifier for call requests (A2.7, A5.8, A5.9).

Keyword rules over the user's own words (English, romanised Hinglish, Devanagari). No model is
involved: a model may propose a call, only this code decides whether it is allowed. Each rule has
an ACTION (refuse or route) and a fixed copy key from ``friday.calls.copy``. Rules are ordered by
severity; the first match decides, all matches are reported.

Known limit: keyword rules miss clever phrasing and may over-block rare innocent sentences. That
is the safe direction; a human review path for refusals is a launch question (docs/LEGAL_MAP.md).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

REFUSE = "refuse"
ROUTE = "route"
OK = "ok"


@dataclass(frozen=True)
class Rule:
    category: str
    action: str  # refuse | route
    line_key: str
    pattern: re.Pattern[str]
    strike: bool = False  # counts as abuse against the user's standing


def _p(*alts: str) -> re.Pattern[str]:
    return re.compile("|".join(alts), re.I)


# Order = severity. Patterns run on normalised text (lowercase, punctuation to spaces).
RULES: tuple[Rule, ...] = (
    Rule(
        "self_harm",
        ROUTE,
        "route_selfharm",
        _p(
            r"\bsuicide\b",
            r"\bkhudkushi\b",
            r"\bkhud\s?kushi\b",
            r"\bend my (own )?life\b",
            r"\bkill myself\b",
            r"\bmar\s?jana chah",
            r"\bmarna chah",
            r"\bjeena nahi chah",
            r"\bzindagi (khatam|end)",
            r"\bkhud ko khatam",
            r"आत्महत्या",
            r"खुदकुशी",
            r"मरना चाह",
            r"जीना नहीं चाह",
        ),
    ),  # fmt: skip
    Rule(
        "emergency",
        ROUTE,
        "route_emergency",
        _p(
            r"\bambulance\b",
            r"\bfire brigade\b",
            r"\bdamkal\b",
            r"\bpolice (ko )?(bulao|bula)\b",
            r"\b(dial|call) 112\b",
            r"\b112 (par|pe|ko|number)\b",
            r"\baccident ho gaya\b",
            r"\bheart attack\b",
            r"\bsaans nahi\b",
            r"एम्बुलेंस",
            r"दमकल",
            r"पुलिस को बुला",
        ),
    ),  # fmt: skip
    Rule(
        "threat",
        REFUSE,
        "refuse_threat",
        _p(
            r"\bdhamki\b",
            r"\bdhamka",
            r"\bdhamkao\b",
            r"\bthreat",
            r"\bmaar (dunga|dungi|denge)\b",
            r"\bjaan se\b",
            r"\bdara(o|na|ne|kar)\b",
            r"\bdarao\b",
            r"\bbomb\b",
            r"\baag laga",
            r"\bsabak sikha",
            r"\bkill (him|her|them)\b",
            r"धमकी",
            r"जान से",
        ),
        strike=True,
    ),  # fmt: skip
    Rule(
        "scam",
        REFUSE,
        "refuse_scam",
        _p(
            r"\botp (maang|mang|le |lo\b|bol|puch|pooch|nikal)",
            r"\b(ask|get|take) (for )?(their |his |her )?(otp|pin|cvv)\b",
            r"\b(pin|cvv) (maang|mang|puch|pooch|bol)",
            r"\bkyc (update|expire|block)[^.]{0,30}(card|otp|pin)",
            r"\bbank (se|wala|officer) (ban|bol)[^.]{0,40}\b(otp|card|pin)\b",
            r"\blottery\b",
            r"\bgift card\b",
            r"\bpaise (nikalwa|mangwa|bhejne ko)",
            r"\bcard number (le|lo|maang|mang)",
            r"\bfake (call|job|offer|kyc)\b",
            r"\bscam\b",
        ),
        strike=True,
    ),  # fmt: skip
    Rule(
        "impersonation",
        REFUSE,
        "refuse_impersonation",
        _p(
            r"\bmeri awaaz\b",
            r"\bmere (naam|name) se (bol|baat|call)",
            r"\bmere jaisa bol",
            r"\b(bol|bolo|bolna|kehna|bata) ?(do|na)? (ki )?main \w+( \w+)? bol (raha|rahi) (hoon|hu)\b",
            r"\bpretend (to be|you are|you re)\b",
            r"\bact as (me|him|her|a )",
            r"\bspeak as me\b",
            r"\bsay (you are|you re) me\b",
            r"\b(bank|police|cbi|income tax|rbi|court)( wala| officer| waala)? ban (ke|kar)\b",
            r"\b(police|officer|inspector|manager) (bankar|ban ke|ban kar)\b",
            r"\bkisi aur ban",
            r"\bclone (my|the) voice\b",
            r"\bvoice clone\b",
            r"\bmeri voice\b",
        ),
        strike=True,
    ),  # fmt: skip
    Rule(
        "minor",
        REFUSE,
        "refuse_minor",
        _p(
            r"\bbach(ch|h)[ae] (ko|se)\b",
            r"\bbachchon (ko|se)\b",
            r"\bkid (ko|se)\b",
            r"\bchild (ko|se)\b",
            r"\bminor\b",
            r"\b(call|phone|ring) (the |a |his |her )?(child|kid)\b",
            r"\bchhote bach(ch|h)",
            r"\bto (a|the) (child|kid|minor)\b",
            r"बच्चे को",
            r"बच्चे से",
        ),
    ),  # fmt: skip
    Rule(
        "harassment",
        REFUSE,
        "refuse_harassment",
        _p(
            r"\bpareshan kar",
            r"\btang kar",
            r"\bharass",
            r"\bspam call",
            r"\bcall bomb",
            r"\bbaar baar call karte raho\b",
            r"\bnon ?stop call",
            r"\bgaali (do|dena|de)\b",
            r"\bbadtameezi\b",
            r"\binsult kar",
            r"\b(1\d|[2-9]\d|\d{3,}) baar (call|phone)\b",
            r"\b(1\d|[2-9]\d|\d{3,}) times (call|phone)\b",
            r"परेशान कर",
            r"गाली",
        ),
        strike=True,
    ),  # fmt: skip
    Rule(
        "prank",
        REFUSE,
        "refuse_prank",
        _p(
            r"\bprank\b",
            r"\bmazak (mein|me|karo|banao|udao)\b",
            r"\btroll\b",
            r"\bfool (them|him|her)\b",
            r"\bbevakoof (banao|bana)\b",
            r"\bmaza (lene|lena|lo) ke liye call\b",
            r"प्रैंक",
            r"मज़ाक में",
        ),
        strike=True,
    ),  # fmt: skip
    Rule(
        "medical_advice",
        ROUTE,
        "route_medical",
        _p(
            r"\b(dawai|dawa|medicine|tablet|dose) (batao|bata do|suggest|kitni|kitna|kya lu|konsi|kaun si)",
            r"\bkaun si (dawai|dawa|medicine)\b",
            r"\bkonsi (dawai|dawa|medicine)\b",
            r"\bdiagnos",
            r"\bprescri(be|ption dena)",
            r"\b(ilaaj|treatment) (batao|bata do|suggest)\b",
            r"\bdoctor (ban|bankar) (ke|kar)\b",
            r"\bmedical advice\b",
            r"\bwhat medicine\b",
            r"\bwhich (medicine|tablet)\b",
        ),
    ),  # fmt: skip
    Rule(
        "legal_advice",
        ROUTE,
        "route_legal",
        _p(
            r"\blegal advice\b",
            r"\bkanooni salah\b",
            r"\bkanoon (kya|batao)",
            r"\bvakil ban",
            r"\blawyer ban",
            r"\bpretend (to be )?(a )?(lawyer|advocate)\b",
            r"\bcourt mein kya karun\b",
        ),
    ),  # fmt: skip
)


@dataclass
class Classification:
    action: str = OK
    category: str | None = None
    line_key: str | None = None
    strike: bool = False
    categories: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.action == OK


_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\sऀ-ॿ]+")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = _PUNCT.sub(" ", t)
    return _SPACE.sub(" ", t).strip()


def classify(*texts: str | None) -> Classification:
    """First (most severe) matching rule decides; every matched category is listed."""
    joined = " . ".join(normalise(t) for t in texts if t)
    hits = [r for r in RULES if r.pattern.search(joined)]
    if not hits:
        return Classification()
    top = hits[0]
    return Classification(
        action=top.action,
        category=top.category,
        line_key=top.line_key,
        strike=any(h.strike for h in hits),
        categories=[h.category for h in hits],
    )
