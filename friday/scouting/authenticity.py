"""Agent 9: review authenticity judge. Rules first; optional LLM hook for text patterns.

Output is a score plus flags with reasons. Honest limits: Places gives at most 5 reviews
per place and no reviewer history, so rules are weak with few reviews (``confidence``
says so) and the ranker blends toward a neutral prior by confidence.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from friday.scouting.models import AuthenticityReport, AuthFlag, PlaceReviews, Review

GENERIC_PRAISE = {
    "good",
    "nice",
    "best",
    "superb",
    "awesome",
    "excellent",
    "great",
    "amazing",
    "fine",
    "super",
    "wonderful",
    "perfect",
    "osm",
    "gud",
    "bahut accha",
    "very good",
    "nice place",
    "good service",
    "best service",
    "great service",
    "nice service",
    "good place",
    "best salon",
    "good salon",
    "nice salon",
    "highly recommended",
    "must visit",
    "top class",
}
BURST_WINDOW_HOURS = 48
_LLM_PENALTY = 0.2
_WORD = re.compile(r"[a-z0-9ऀ-ॿ]+")


class TextFlag(BaseModel):
    """Closed output of the optional LLM text-pattern judge."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["TEMPLATE_TEXT", "KEYWORD_STUFFING", "UNRELATED", "PROMOTIONAL"]
    review_ids: list[str]
    detail: str = ""


class TextPatternJudge(Protocol):
    async def judge(self, place_name: str, reviews: list[Review]) -> list[TextFlag]: ...


def _norm(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _is_generic(text: str) -> bool:
    n = _norm(text)
    words = n.split()
    return bool(words) and (
        n in GENERIC_PRAISE or (len(words) <= 3 and set(words) <= _all_generic_words())
    )


_GENERIC_WORDS: set[str] | None = None


def _all_generic_words() -> set[str]:
    global _GENERIC_WORDS
    if _GENERIC_WORDS is None:
        _GENERIC_WORDS = {w for p in GENERIC_PRAISE for w in p.split()} | {
            "very",
            "so",
            "really",
            "service",
            "place",
            "salon",
            "staff",
            "ok",
            "okay",
            "ever",
        }
    return _GENERIC_WORDS


def _burst(reviews: list[Review]) -> AuthFlag | None:
    dated = sorted((r for r in reviews if r.published_at), key=lambda r: r.published_at)
    if len(dated) < 4:
        return None
    best: list[Review] = []
    for i in range(len(dated)):
        win = [
            r
            for r in dated[i:]
            if (r.published_at - dated[i].published_at).total_seconds() <= BURST_WINDOW_HOURS * 3600
        ]
        if len(win) > len(best):
            best = win
    share = len(best) / len(dated)
    if len(best) >= 3 and share >= 0.6:
        return AuthFlag(
            code="REVIEW_BURST",
            detail=(
                f"{len(best)} of {len(dated)} sampled reviews "
                f"posted within {BURST_WINDOW_HOURS}h"
            ),
            penalty=0.3 if share >= 0.8 else 0.2,
            review_ids=[r.review_id for r in best],
        )
    return None


def _duplicates(reviews: list[Review]) -> AuthFlag | None:
    ids: set[str] = set()
    norms = [(r.review_id, _norm(r.text)) for r in reviews]
    for i in range(len(norms)):
        for j in range(i + 1, len(norms)):
            a, b = norms[i][1], norms[j][1]
            if len(a.split()) < 4 or len(b.split()) < 4:
                continue  # short texts coincide naturally; handled by generic-praise rule
            if a == b or SequenceMatcher(None, a, b).ratio() >= 0.85:
                ids.update((norms[i][0], norms[j][0]))
    if ids:
        return AuthFlag(
            code="DUPLICATE_TEXT",
            detail=f"{len(ids)} reviews are copies or near-copies of each other",
            penalty=0.35 if len(ids) >= 3 else 0.25,
            review_ids=sorted(ids),
        )
    return None


def _generic(reviews: list[Review]) -> AuthFlag | None:
    if len(reviews) < 3:
        return None
    hits = [r for r in reviews if _is_generic(r.text)]
    if len(hits) / len(reviews) >= 0.6:
        return AuthFlag(
            code="SHORT_GENERIC_PRAISE",
            detail=f"{len(hits)} of {len(reviews)} reviews are one-line generic praise",
            penalty=0.2,
            review_ids=[r.review_id for r in hits],
        )
    return None


def _low_history(reviews: list[Review]) -> AuthFlag | None:
    known = [r for r in reviews if r.author_review_count is not None]
    if len(known) < 3:
        return None
    few = [r for r in known if r.author_review_count <= 1]
    if len(few) / len(known) >= 0.6:
        return AuthFlag(
            code="LOW_HISTORY_REVIEWERS",
            detail=f"{len(few)} of {len(known)} reviewers have written 1 review or none else",
            penalty=0.25,
            review_ids=[r.review_id for r in few],
        )
    return None


def _rating_oddity(
    reviews: list[Review], rating: float | None, count: int | None
) -> AuthFlag | None:
    rated = [r.rating for r in reviews if r.rating]
    if len(rated) < 3 or rating is None:
        return None
    mean = sum(rated) / len(rated)
    if all(x == 5 for x in rated) and rating >= 4.9 and (count or 0) < 50:
        return AuthFlag(
            code="RATING_ODDITY",
            detail=f"perfect {rating} from only {count} ratings, every sampled review 5 stars",
            penalty=0.2,
        )
    if abs(mean - rating) >= 2.0:
        return AuthFlag(
            code="RATING_ODDITY",
            detail=f"sampled reviews average {mean:.1f} but the listing shows {rating}",
            penalty=0.1,
        )
    return None


def _confidence(n: int) -> Literal["low", "medium", "high"]:
    return "low" if n < 3 else ("medium" if n < 5 else "high")


def judge_rules(
    pr: PlaceReviews, *, rating: float | None = None, review_count: int | None = None
) -> AuthenticityReport:
    revs = pr.reviews
    if not revs:
        return AuthenticityReport(
            place_id=pr.place_id,
            genuine_score=0.5,
            confidence="low",
            flags=[AuthFlag(code="NO_REVIEWS", detail="no review text available", penalty=0.0)],
        )
    flags = [
        f
        for f in (
            _burst(revs),
            _duplicates(revs),
            _generic(revs),
            _low_history(revs),
            _rating_oddity(revs, rating, review_count),
        )
        if f
    ]
    score = max(0.0, 1.0 - sum(f.penalty for f in flags))
    return AuthenticityReport(
        place_id=pr.place_id,
        genuine_score=round(score, 3),
        confidence=_confidence(len(revs)),
        flags=flags,
        reviews_seen=len(revs),
    )


_LLM_CODES = {
    "TEMPLATE_TEXT": "LLM_TEMPLATE_TEXT",
    "KEYWORD_STUFFING": "LLM_KEYWORD_STUFFING",
    "UNRELATED": "LLM_UNRELATED",
    "PROMOTIONAL": "LLM_PROMOTIONAL",
}


async def judge_authenticity(
    pr: PlaceReviews,
    place_name: str = "",
    *,
    rating: float | None = None,
    review_count: int | None = None,
    text_judge: TextPatternJudge | None = None,
) -> AuthenticityReport:
    report = judge_rules(pr, rating=rating, review_count=review_count)
    if text_judge is None or not pr.reviews:
        return report
    try:
        tflags = await text_judge.judge(place_name, pr.reviews)
    except Exception:  # LLM trouble never blocks the rules verdict
        return report
    known = {r.review_id for r in pr.reviews}
    flags = list(report.flags)
    seen_codes = set()
    for tf in tflags:
        ids = [i for i in tf.review_ids if i in known]  # code verifies ids exist
        if not ids or tf.code in seen_codes:
            continue
        seen_codes.add(tf.code)
        flags.append(
            AuthFlag(
                code=_LLM_CODES[tf.code],
                detail=tf.detail or tf.code.lower(),
                penalty=_LLM_PENALTY,
                review_ids=ids,
            )
        )
    score = max(0.0, 1.0 - sum(f.penalty for f in flags))
    return report.model_copy(
        update={"flags": flags, "genuine_score": round(score, 3), "llm_used": True}
    )
