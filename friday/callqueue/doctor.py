# ruff: noqa: E501
"""Doctor section for the call queue (read-only; never prints a phone number)."""

from __future__ import annotations

from typing import Any

from friday.callqueue.limits import resolve
from friday.callqueue.store import QueueStore


def check(settings: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    lim = resolve(settings)
    if not settings.call_queue_enabled:
        out.append(
            (
                "ok",
                "call queue OFF (FRIDAY_CALL_QUEUE_ENABLED is not true): calls dial directly; "
                "Vobiz's own account queue paces them",
            )
        )
        out.append(
            (
                "ok",
                f"limits it would use: {lim.max_concurrent} concurrent, {lim.cps:g} start/s "
                f"(source: {lim.source})",
            )
        )
        return out
    out.append(
        (
            "ok",
            f"call queue ON: {lim.max_concurrent} concurrent, {lim.cps:g} start/s (source: {lim.source})",
        )
    )
    if lim.source == "default":
        out.append(
            (
                "warn",
                "limits are the built-in defaults; run the Vobiz probe or set "
                "FRIDAY_CALL_QUEUE_MAX_CONCURRENT / FRIDAY_CALL_QUEUE_CPS",
            )
        )
    try:
        store = QueueStore(settings.call_queue_db)
        counts = store.counts()
        store.close()
    except Exception as e:  # noqa: BLE001
        out.append(
            ("fail", f"queue state is not usable ({type(e).__name__}); check FRIDAY_CALL_QUEUE_DB")
        )
        return out
    out.append(
        ("ok", f"queue state readable: {counts['waiting']} waiting, {counts['active']} active")
    )
    if counts["stale"]:
        out.append(
            (
                "warn",
                f"{counts['stale']} active slot(s) are past their deadline; the next call reclaims them",
            )
        )
    if counts["waiting"] > 20:
        out.append(("warn", f"{counts['waiting']} calls are waiting for a slot"))
    return out
