"""SECURITY-32: retention job (proactive, once per IST day)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("friday.proactive.retention")

from friday.core.clock import IST  # noqa: E402
from friday.proactive.retention import RetentionJob  # noqa: E402
from tests.tasks.conftest import env, env_settings  # noqa: E402, F401


class Recorder:
    def __init__(self, ret=0):
        self.calls = []
        self.ret = ret

    def __getattr__(self, name):
        async def fn(*a, **k):
            self.calls.append((name, a))
            return self.ret

        return fn


async def test_recordings_older_than_30_days_deleted(env, tmp_path):  # noqa: F811
    env.container.settings.media_dir = str(tmp_path)
    old = tmp_path / "rec-old.wav"
    old.write_bytes(b"x")
    outside = tmp_path.parent / "not-media.wav"
    outside.write_bytes(b"x")
    tasks = Recorder(ret=[str(old), str(outside), None])
    env.repos.tasks = tasks
    now = datetime(2026, 3, 1, 4, 0, tzinfo=IST)
    out = await RetentionJob(env.container).run(now)
    name, (cutoff,) = tasks.calls[0]
    assert name == "purge_call_content_before" and cutoff == now - timedelta(days=30)
    assert out["recording_files"] == 1 and not old.exists() and outside.exists()


async def test_preconsent_data_purged_after_7_days(env):  # noqa: F811
    users, places, purger = Recorder(2), Recorder(1), Recorder(4)
    env.repos.users, env.repos.places, env.repos.purger = users, places, purger
    now = datetime(2026, 3, 1, 4, 0, tzinfo=IST)
    job = RetentionJob(env.container)
    out = await job.run_daily(now)
    assert users.calls[0] == ("purge_preconsent_before", (now - timedelta(days=7),))
    assert places.calls[0] == ("purge_ephemeral_before", (now - timedelta(hours=24),))
    assert purger.calls[0][0] == "process_pending_deletions"
    assert out["preconsent_users"] == 2 and out["pending_deletions"] == 4
    assert await job.run_daily(now + timedelta(hours=1)) is None  # once per IST day
    assert await job.run_daily(datetime(2026, 3, 2, 1, 0, tzinfo=IST)) is None  # before 03:00


async def test_retention_delegates_to_repo_job_body(env):  # noqa: F811
    seen = {}

    class Body:
        async def run(self, now, *, recording_days, preconsent_days):
            seen.update(now=now, rec=recording_days, pre=preconsent_days)
            return {"recordings": 3}

    env.repos.retention = Body()
    now = datetime(2026, 3, 1, 4, 0, tzinfo=IST)
    assert await RetentionJob(env.container).run(now) == {"recordings": 3}
    assert seen == {"now": now, "rec": 30, "pre": 7}
