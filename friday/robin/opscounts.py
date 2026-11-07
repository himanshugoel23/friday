# ruff: noqa: E501
"""Robin observability without PII (T05): counts only, for ``/ops-status/<token>/robin`` and the doctor.

Everything returned here is an integer or one short status word. Never an id, a name, a number, a time of day
(only an age in seconds) or a line of text: the incident ``data`` is read inside this module to count tiers and
scenarios and is dropped. ``bump`` is the metrics counter: it counts in process and writes one fixed-name
line through the logging layer (``friday.core.logging``, so the usual redaction applies).
"""

from __future__ import annotations

import os
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from friday.core.logging import get_logger
from friday.robin.dbmodel import RobinFamilyRow, RobinRecordRow

log = get_logger(__name__)

METRIC_NAMES = ("ticks", "tick_step_errors", "tick_errors", "alerts_raised", "sos", "device_sweeps_failed")
TIERS = ("info", "watch", "high", "emergency")
FAMILY_STATUSES = ("onboarding", "active", "paused")
STATUS_WORDS = ("ok", "off")  # the only strings the route may return as values
TICK_FILE_DEFAULT = "var/robin/last_tick"
_ACTIVE_INCIDENT = ("open", "running", "exhausted")

_COUNTERS: Counter[str] = Counter()


def bump(name: str, n: int = 1) -> None:
    """Count one event. Names are fixed (``METRIC_NAMES``); an unknown name is ignored, so nothing free-form is ever logged."""
    if name not in METRIC_NAMES:
        return
    _COUNTERS[name] += n
    log.info("metric robin.%s +%d", name, n)


def counter(name: str) -> int:
    return int(_COUNTERS.get(name, 0))


def reset_counters() -> None:
    _COUNTERS.clear()


def tick_file() -> Path:
    return Path(os.environ.get("FRIDAY_ROBIN_TICK_FILE") or TICK_FILE_DEFAULT)


def write_tick_marker() -> None:
    """Best effort: the scheduler leaves 'it ran just now' for ``friday doctor`` (a separate process). Holds one number."""
    try:
        p = tick_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(int(time.time())))
    except OSError:
        pass


def tick_age_s(now: float | None = None) -> int | None:
    """Seconds since the last scheduler tick, or None when nothing was ever recorded."""
    try:
        then = int(tick_file().read_text().strip())
    except (OSError, ValueError):
        return None
    return max(0, int((now if now is not None else time.time()) - then))


def device_counts(service: Any) -> tuple[int, int]:
    """(devices paired, devices whose heartbeat is missed = scenario S7 open). Integers only."""
    store = getattr(service, "store", None)
    if store is None:
        return 0, 0
    paired = missed = 0
    for pid in store.parent_ids():
        st = store.peek(pid)
        if st is not None and st.device is not None:
            paired += 1
            missed += 1 if st.s7_open else 0
    return paired, missed


async def robin_counts(hub: Any, device_service: Any = None) -> dict[str, Any]:
    """The counts document. ``hub`` is the RobinHub (None = Robin off). Safe to serialise as is."""
    if hub is None:
        return {"status": "off"}
    store = hub.ctx.store
    since = hub.ctx.clock.now() - timedelta(hours=24)
    fams = dict.fromkeys(FAMILY_STATUSES, 0)
    alerts = dict.fromkeys(TIERS, 0)
    checkins = {"done": 0, "unanswered": 0}
    sos = falls = incidents_active = 0
    async with store.db.session() as s:
        for status, n in (await s.execute(select(RobinFamilyRow.status, func.count()).group_by(RobinFamilyRow.status))).all():
            if status in fams:
                fams[status] = int(n)
        outbox = int((await s.execute(select(func.count()).select_from(RobinRecordRow).where(RobinRecordRow.kind == "pending", RobinRecordRow.status == "queued"))).scalar_one())
        for status, n in (await s.execute(select(RobinRecordRow.status, func.count()).where(RobinRecordRow.kind == "checkin", RobinRecordRow.at >= since).group_by(RobinRecordRow.status))).all():
            if status == "done":
                checkins["done"] = int(n)
            elif status == "unanswered":
                checkins["unanswered"] = int(n)
        rows = (await s.execute(select(RobinRecordRow).where(RobinRecordRow.kind == "incident").where((RobinRecordRow.at >= since) | RobinRecordRow.status.in_(_ACTIVE_INCIDENT)))).scalars().all()
        for r in rows:
            d = dict(r.data or {})  # decrypted here, counted, dropped
            if r.status in _ACTIVE_INCIDENT:
                incidents_active += 1
            if r.at < since:
                continue
            tier = str(d.get("tier") or "").lower()
            if tier in alerts:
                alerts[tier] += 1
            scenario = str(d.get("scenario") or "").lower()
            sos += 1 if scenario == "sos" else 0
            falls += 1 if scenario == "fall" else 0
    paired, missed = device_counts(device_service)
    last = getattr(hub, "last_tick_at", None)
    age = int((hub.ctx.clock.now() - last).total_seconds()) if last is not None else -1
    return {
        "status": "ok",
        "families": fams,
        "incidents_active": incidents_active,
        "alerts_24h": alerts,
        "sos_24h": sos,
        "falls_24h": falls,
        "checkins_24h": checkins,
        "devices_paired": paired,
        "heartbeats_missed": missed,
        "outbox_pending": outbox,
        "errors": counter("tick_step_errors") + counter("tick_errors") + counter("device_sweeps_failed"),
        "last_tick_age_s": max(age, -1),
    }
