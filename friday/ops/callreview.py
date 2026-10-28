"""Call review for the founder's TEST calls (docs/CALL_REVIEW.md).

Plain-text transcripts of the last N calls so the voice bot can be reviewed remotely. Privacy:
only calls whose destination is on the tester allow-list, never a call flagged as a real
vendor/third party, phone masked to the last 2 digits, 4-8 digit runs and e-mails redacted,
total size capped. Off unless FRIDAY_OPS_CALL_REVIEW_ENABLED=true (route and CLI).
"""

from __future__ import annotations

import os
import re
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import select

from friday.db.tables import CallRow, CallTurnRow
from friday.webchat.registry import allowed_numbers

DEFAULT_N = 5
MAX_N = 20
MAX_BYTES = 40_000
_SWITCH = "FRIDAY_OPS_CALL_REVIEW_ENABLED"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DIGITS = re.compile(r"(?<!\d)(?:\d[ -]?){3,7}\d(?!\d)")  # 4-8 digits, optional single separators
_SECRET = re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{10,}|\b[A-Za-z0-9_-]{32,}\b")
_FLAGS = ("real_vendor", "third_party")


def enabled() -> bool:
    v = os.environ.get(_SWITCH) or str(dotenv_values(".env").get(_SWITCH) or "")
    return v.strip().lower() in ("1", "true", "yes", "on")


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _SECRET.sub("[secret]", text)
    return _DIGITS.sub("[digits]", text)


def mask_phone(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    return ("*" * 8 + d[-2:]) if len(d) >= 2 else "***"


def _norm(phone: str | None) -> str:
    return re.sub(r"[^\d+]", "", phone or "")


def clamp_n(n: int | None) -> int:
    return max(1, min(MAX_N, n or DEFAULT_N))


def _all_redirected(settings: Any) -> bool:
    """Pilot guard: every outbound call is redirected to a tester's own number, so the stored
    destination (the business's number) never rang anyone else. Then those calls are reviewable."""
    return bool(getattr(settings, "vendor_call_redirect_to", None))


def _flagged(row: CallRow) -> bool:
    c = row.collected if isinstance(row.collected, dict) else {}
    return any(c.get(f) for f in _FLAGS)


def _dur(row: CallRow) -> str:
    if row.answered_at and row.ended_at:
        return f"{int((row.ended_at - row.answered_at).total_seconds())}s"
    return "not answered"


async def render_review(db: Any, settings: Any, n: int | None = None, max_bytes: int = MAX_BYTES) -> str:
    n = clamp_n(n)
    allowed = {_norm(p) for p in allowed_numbers(settings)}
    blocks: list[str] = []
    async with db.session() as s:
        rows = (await s.execute(select(CallRow).order_by(CallRow.started_at.desc()).limit(200))).scalars()
        rows = list(rows)
        redirected = _all_redirected(settings)
        picked = [
            r
            for r in rows
            if (_norm(r.to_phone) in allowed or (redirected and r.direction == "outbound")) and not _flagged(r)
        ][:n]
        for r in picked:
            tl = list(
                (
                    await s.execute(select(CallTurnRow).where(CallTurnRow.call_id == r.id).order_by(CallTurnRow.seq))
                ).scalars()
            )
            head = (
                f"=== call {r.id[:8]} | {r.started_at:%Y-%m-%d %H:%M:%S} UTC | outcome={r.outcome} "
                f"dial={r.dial_status} | {_dur(r)} | to {mask_phone(r.to_phone)} ==="
            )
            confs = [t.confidence for t in tl if t.confidence is not None]
            metrics = [
                f"hold_s={r.hold_seconds}",
                f"languages={','.join(r.languages_heard or []) or '-'}",
                f"turns={len(tl)}",
            ]
            if confs:
                metrics.append(f"asr_conf_avg={sum(confs) / len(confs):.2f} min={min(confs):.2f}")
            if r.error:
                metrics.append("error=" + redact(str(r.error))[:120])
            lines = [head, "metrics: " + " ".join(metrics)]
            for t in tl:
                c = f" [conf {t.confidence:.2f}]" if t.confidence is not None else ""
                lines.append(f"{t.speaker}: {redact(t.text)}{c}")
            blocks.append("\n".join(lines))
    if not blocks:
        return f"no test calls to show ({len(rows)} recent call rows in the database, redirect_active={redirected})\n"
    out, used = [], 0
    for b in blocks:
        size = len(b.encode()) + 2
        if used + size > max_bytes:
            out.append(b.encode()[: max(0, max_bytes - used)].decode("utf-8", "ignore") + "\n[truncated: size cap]")
            break
        out.append(b)
        used += size
    return "\n\n".join(out) + "\n"


def cli_review(settings: Any, n: int, out: Any = print) -> int:
    import asyncio

    from friday.core.container import Container

    if not enabled():
        out(f"call review is off: set {_SWITCH}=true (deploy/enable-web-test.sh does it)")
        return 2

    async def go() -> str:
        c = Container(settings)
        try:
            return await render_review(c.db, settings, n)
        finally:
            await c.aclose()

    out(asyncio.run(go()), end="")
    return 0
