"""SECURITY-32: data retention, run once per IST day by the proactive tick.

* call recordings + transcript turns + mid-call question text older than
  ``recording_retention_days`` (30) - summaries/results are kept
* users who never gave DPDP consent, older than ``preconsent_retention_days`` (7)
* ephemeral places ("current location" pins) older than 24 h
* queued "delete my data" requests (``pending_deletions``)

Exactly once per day across replicas/shards via ``IdempotencyStore.first_seen``.
Repository methods are Backend A's (optional until merged); local recording files
under ``Settings.media_dir`` are removed here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from friday.core.clock import ist_date, to_ist
from friday.core.logging import get_logger
from friday.tasks.ports import call_opt, repo

log = get_logger(__name__)

RECORDING_RETENTION_DAYS = 30
PRECONSENT_RETENTION_DAYS = 7
EPHEMERAL_PLACE_HOURS = 24
RUN_HOUR_IST = 3  # quiet time


class RetentionJob:
    def __init__(self, c: Any) -> None:
        self.c = c
        self.settings = c.settings
        self.clock = c.clock

    def _days(self, name: str, default: int) -> int:
        return int(getattr(self.settings, name, None) or default)

    async def run_daily(self, now: datetime) -> dict[str, int] | None:
        """Runs at most once per IST day (first tick at/after 03:00 IST)."""
        if to_ist(now).hour < RUN_HOUR_IST:
            return None
        idem = None
        try:
            idem = self.c.get("idempotency")
        except Exception:  # noqa: BLE001
            idem = None
        key = f"retention:{ist_date(now).isoformat()}"
        if idem is not None and not await idem.first_seen(key, ttl_s=3 * 86400):
            return None
        out = await self.run(now)
        out["quality_transcripts"] = await self._purge_quality(now)
        return out

    async def _purge_quality(self, now: datetime) -> int:
        """Stored call transcripts past their retention window (friday/quality)."""
        from friday.quality.store import TranscriptStore

        try:
            return await TranscriptStore.from_container(self.c).purge_expired(now)
        except Exception as e:  # noqa: BLE001 - never stop the rest of the retention job
            log.warning("quality transcript purge failed: %s", type(e).__name__)
            return 0

    async def run(self, now: datetime) -> dict[str, int]:
        repos = self.c.get("repos")
        rec_cutoff = now - timedelta(
            days=self._days("recording_retention_days", RECORDING_RETENTION_DAYS)
        )
        pre_cutoff = now - timedelta(
            days=self._days("preconsent_retention_days", PRECONSENT_RETENTION_DAYS)
        )
        eph_cutoff = now - timedelta(hours=EPHEMERAL_PLACE_HOURS)
        # Backend A's job body (friday.db.retention.run_retention) when the bundle exposes
        # it as ``repos.retention.run(now, recording_days=, preconsent_days=)``.
        body = getattr(repo(repos, "retention"), "run", None)
        if body is not None:
            out = await body(
                now,
                recording_days=self._days("recording_retention_days", RECORDING_RETENTION_DAYS),
                preconsent_days=self._days("preconsent_retention_days", PRECONSENT_RETENTION_DAYS),
            )
            log.info("retention run: %s", out)
            return dict(out)
        tasks = repo(repos, "tasks")
        out: dict[str, int] = {}
        removed = await call_opt(tasks, "purge_call_content_before", rec_cutoff, default=None)
        urls: list[str] = []
        if isinstance(removed, list):
            urls = [u for u in removed if u]
            out["calls"] = len(removed)
        elif isinstance(removed, int):
            out["calls"] = removed
        out["recording_files"] = self._delete_local(urls)
        out["preconsent_users"] = int(
            await call_opt(repo(repos, "users"), "purge_preconsent_before", pre_cutoff, default=0)
            or 0
        )
        out["ephemeral_places"] = int(
            await call_opt(repo(repos, "places"), "purge_ephemeral_before", eph_cutoff, default=0)
            or 0
        )
        out["pending_deletions"] = int(
            await call_opt(repo(repos, "purger"), "process_pending_deletions", default=0) or 0
        )
        log.info("retention run: %s", out)
        return out

    def _delete_local(self, urls: list[str]) -> int:
        """Recordings stored under media_dir (dev/simulator). Object-store recordings are
        deleted by the repository / lifecycle rule (S-6)."""
        base = Path(self.settings.media_dir).resolve()
        n = 0
        for url in urls:
            path_str = url.removeprefix("file://")
            try:
                path = Path(path_str).resolve()
            except (OSError, ValueError):
                continue
            if base in path.parents and path.is_file():
                path.unlink()
                n += 1
        return n
