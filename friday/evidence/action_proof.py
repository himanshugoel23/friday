# ruff: noqa: E501
"""PROOF cards for every completed or attempted action (docs/STYLE_GUIDE.md, rule 6; docs/PROOF.md).

Covers calls, lookups, cart / checkout previews and form submits. A card says what / where / when /
amount / reference / link and, for a failed or stopped attempt, what was SEEN. Results of
``friday.sitemcp`` and ``friday.browser_agent`` are consumed through ``adapt_result``, which reads
only plain fields by name (attributes or dict keys), so those packages stay untouched and a missing
field just leaves a line out.

Rules kept from PROOF.md: a screenshot is stored and offered only when the caller says it was painted
over (``masked``); anything else is dropped. Every item gets ``expires_at`` (retention days) and is
removed by the same ``expire`` / erasure paths as the other evidence. A checkout preview is never
"done": it always reads "stopped at the payment step, nothing was charged".
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from friday.calls.privacy import scrub
from friday.core.clock import format_ist
from friday.core.models import CallOutcome, CallResult, DialStatus, Task, TaskResult
from friday.evidence import collector
from friday.evidence.models import EvidenceItem, EvidenceKind, EvidenceLevel, Redaction
from friday.replywriter import status_words as sw
from friday.style.builders import ProofCard, proof_card

KINDS = ("call", "lookup", "cart", "checkout", "form")
_DONE = {"ok", "done", "success", "succeeded", "submitted", "completed", "complete", "found", "booked"}
_STOPPED = {"stopped", "preview", "awaiting_payment", "needs_payment", "payment", "checkout"}
_FAILED = {"failed", "error", "blocked", "timeout", "unavailable", "no_result", "captcha", "denied"}
MAX_TEXT = 160


@dataclass
class ActionProof:
    user_id: str
    task_id: str
    kind: str
    outcome: str  # done | attempted | checkout | failed
    what: str
    where: str = ""
    when: datetime | None = None
    amount: str = ""
    reference: str = ""
    link: str = ""
    seen: str = ""
    screenshot: bytes | None = None
    masked: bool = False
    code: str = ""  # internal status code of a failed attempt (no_result, blocked ...): turned into plain words in the card
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class ProofMessage:
    text: str
    items: list[EvidenceItem]
    media: bytes | None = None  # a masked screenshot to send with the card, else None
    media_key: str | None = None


def _get(obj: Any, *names: str) -> Any:
    for n in names:
        v = obj.get(n) if isinstance(obj, Mapping) else getattr(obj, n, None)
        if v not in (None, "", b""):
            return v
    return None


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return scrub(str(value).strip())[:limit] if value not in (None, "") else ""


def safe_link(url: Any) -> str:
    """http(s) only, no query or fragment (those can hold tokens)."""
    try:
        p = urlparse(str(url or ""))
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    return f"{p.scheme}://{p.hostname}{p.path}"[:200]


def _money(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return f"Rs {value:,.0f}"
    return _clean(value, 40)


def outcome_of(raw: Any, kind: str) -> str:
    word = str(raw or "").strip().lower()
    if kind == "checkout":  # a checkout preview never completes a payment
        return "failed" if word in _FAILED else "checkout"
    if word in _DONE:
        return "done"
    if word in _STOPPED:
        return "checkout"
    if word in _FAILED:
        return "failed"
    return "attempted"


def adapt_result(
    result: Any, *, kind: str, what: str, user_id: str, task_id: str, now: datetime
) -> ActionProof:
    """Turn a sitemcp / browser_agent result (object or dict) into an ``ActionProof``."""
    url = _get(result, "url", "link", "page_url", "final_url")
    shot = _get(result, "screenshot", "screenshot_bytes", "shot")
    outcome = outcome_of(_get(result, "status", "outcome", "overall"), kind)
    raw = str(_get(result, "status", "outcome", "overall") or "").strip().lower()
    return ActionProof(
        user_id=user_id,
        task_id=task_id,
        kind=kind if kind in KINDS else "lookup",
        outcome=outcome,
        code=raw if outcome in ("failed", "attempted") and raw not in ("", "ok") else "",
        what=_clean(what, 120),
        where=_clean(_get(result, "site", "host") or (urlparse(str(url)).hostname if url else ""), 60),
        when=now,
        amount=_money(_get(result, "total", "amount", "price")),
        reference=_clean(_get(result, "reference", "ref", "order_id", "booking_ref", "confirmation"), 60),
        link=safe_link(url),
        seen=_clean(_get(result, "seen", "message", "error", "summary", "title")),
        screenshot=shot if isinstance(shot, (bytes, bytearray)) else None,
        masked=bool(_get(result, "masked", "screenshot_masked")),
    )


def adapt_call(
    task: Task, result: CallResult, summary: TaskResult | None, *, now: datetime, retention_days: int = 90
) -> ActionProof:
    """A finished call as a proof. A reference counts only when ``collector.from_call`` found it in
    what the callee said; an unanswered or failed call is an 'attempted' card with what happened."""
    items = collector.from_call(task, result, summary, now=now, retention_days=retention_days)
    ref = next((i.payload.get("ref", "") for i in items if i.payload.get("ref")), "")
    ok = bool(items)
    who = task.target.name if task.target else ""
    if ok:
        seen = ""
    elif result.dial_status != DialStatus.ANSWERED:
        seen = f"call not answered ({result.dial_status.value})"
    else:
        seen = f"call ended: {result.outcome.value if isinstance(result.outcome, CallOutcome) else result.outcome}"
    return ActionProof(
        user_id=task.requester_user_id,
        task_id=task.id,
        kind="call",
        outcome="done" if ok else "attempted",
        what=_clean(task.spec.goal or "call", 120),
        where=_clean(who, 60),
        when=now,
        reference=collector.mask_ref(ref) if ref else "",
        seen=seen,
    )


class ProofService:
    """Builds the card, stores the evidence (with expiry) and keeps a masked screenshot."""

    def __init__(self, store: Any, objects: Any = None, *, retention_days: int = 90, lang: str = "hinglish") -> None:
        self.store, self.objects = store, objects
        self.days, self.lang = retention_days, lang

    async def record(self, proof: ActionProof, *, now: datetime | None = None, lang: str | None = None) -> ProofMessage:
        now = now or proof.when or datetime.now().astimezone()
        lang = lang or self.lang
        expires = collector.expiry(now, self.days)
        # a user never sees an internal code (no_result, lookup:blocked ...): say what happened in plain words
        plain = nxt = ""
        if proof.outcome in ("failed", "attempted") and (proof.code or sw.is_code(proof.seen)):
            plain = sw.what_happened(proof.code or proof.seen, lang)
            nxt = sw.next_step([], lang)
        if sw.is_code(proof.seen):  # the plain sentence already says it; never print the code
            proof.seen = ""
        items: list[EvidenceItem] = [
            EvidenceItem(
                user_id=proof.user_id,
                task_id=proof.task_id,
                kind=EvidenceKind.ACTION_PROOF,
                level=EvidenceLevel.OBSERVED,
                summary=proof.what[:200],
                payload={
                    k: v[:200]
                    for k, v in {
                        "kind": proof.kind, "outcome": proof.outcome, "where": proof.where, "amount": proof.amount,
                        "ref": proof.reference, "link": proof.link, "seen": proof.seen,
                    }.items()
                    if v
                },
                captured_at=now,
                expires_at=expires,
                source=proof.kind,
            )
        ]
        media = key = None
        if proof.screenshot and proof.masked:  # PROOF.md: an unmasked screenshot is dropped, never kept or sent
            media = bytes(proof.screenshot)
            if self.objects is not None:
                key = await self.objects.put(
                    f"evidence/{proof.user_id}/{proof.task_id}/{proof.kind}.png", media, content_type="image/png"
                )
            items.append(
                EvidenceItem(
                    user_id=proof.user_id, task_id=proof.task_id, kind=EvidenceKind.SCREENSHOT,
                    level=EvidenceLevel.OBSERVED, captured_at=now, expires_at=expires,
                    sha256=hashlib.sha256(media).hexdigest(), object_key=key, redaction=Redaction.MASKED,
                    source=proof.kind, payload={"where": proof.where} if proof.where else {},
                )
            )
        if self.store is not None:
            await self.store.add_items(items)
        card = ProofCard(
            outcome=proof.outcome, what=proof.what, where=proof.where,
            when=format_ist(now) if proof.when or now else "", amount=proof.amount, reference=proof.reference,
            link=proof.link, seen=proof.seen, has_screenshot=media is not None, plain=plain, next_step=nxt,
            keep_days=self.days if self.store is not None else None,  # never promise retention that is not stored
        )
        return ProofMessage(text=proof_card(card, lang), items=items, media=media, media_key=key)


async def send_card(
    pipeline: Any, user: Any, result: Any, *, kind: str, what: str, lang: str, task_id: str | None = None
) -> ProofMessage | None:
    """Record a PROOF card for ``result`` and send it as its own message (a second message for a second
    idea). Only when the style layer is on; never raises: a proof failure must not break the answer."""
    from friday.core.models import new_id

    if not getattr(getattr(pipeline, "settings", None), "style_layer_enabled", False):
        return None
    # evidence_items.task_id is a foreign key to tasks: a card is stored only for a real task (call, browser
    # task). A task-less lookup card is still sent, without the retention line (nothing is kept for it).
    store = getattr(getattr(pipeline, "repos", None), "evidence", None) if task_id else None
    try:
        now = pipeline.clock.now()
        proof = adapt_result(result, kind=kind, what=what, user_id=user.id, task_id=task_id or new_id(), now=now)  # synthetic id is never stored
        days = int(getattr(pipeline.settings, "proof_retention_days", 90))
        msg = await ProofService(store, getattr(pipeline, "objects", None), retention_days=days).record(proof, now=now, lang=lang)
        await pipeline.reply(user, msg.text)
        return msg
    except Exception:  # noqa: BLE001
        from friday.core.logging import get_logger

        get_logger(__name__).info("proof card failed (%s)", kind, exc_info=True)
        return None
