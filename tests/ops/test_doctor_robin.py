# ruff: noqa: E501
"""Doctor section 13 (Robin): switches, authority lock, lines, migrations, scheduler. Fakes only; nothing is dialled."""

from __future__ import annotations

import time
from pathlib import Path

from friday.core.config import Settings
from friday.ops import doctor as d
from friday.robin import opscounts


def mk(tmp_path: Path, **kw) -> Settings:
    kw.setdefault("database_url", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    kw.setdefault("pause_file", str(tmp_path / "var" / "PAUSED"))
    return Settings(_env_file=None, env="test", **kw)


def lines_of(sec: d.Section, status: str) -> str:
    return "\n".join(c.message for c in sec.checks if c.status == status)


def test_section_is_registered_and_runs_in_the_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    assert "robin" in d.SECTIONS and d.TITLES["robin"]
    import asyncio

    secs = asyncio.run(d.run_sections(mk(tmp_path), offline=True, only="robin"))
    assert [s.name for s in secs] == ["robin"] and d.FAIL not in [c.status for c in secs[0].checks]


def test_default_settings_pass_with_robin_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    sec = d.check_robin(mk(tmp_path))
    assert not [c for c in sec.checks if c.status == d.FAIL]
    text = "\n".join(c.message for c in sec.checks)
    assert "FRIDAY_ROBIN_ENABLED=off" in text and "FRIDAY_ROBIN_DEVICE_ENABLED=off" in text
    assert "dry-run on" in text and "PENDING" in text
    assert "0019" in text and "0020" in text and "care protocol component present" in text
    assert any(c.status == d.SKIP for c in sec.checks)  # scheduler/channel not judged while off


def test_authority_live_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    for extra in ({}, {"robin_authority_calls_enabled": True}, {"robin_enabled": True}):
        sec = d.check_robin(mk(tmp_path, robin_authority_dry_run=False, **extra))
        assert "AUTHORITY_DRY_RUN=false" in lines_of(sec, d.FAIL), extra
    text, passed = d.render([d.check_robin(mk(tmp_path, robin_authority_dry_run=False))], offline=True, as_json=False, secret_values=[])
    assert passed is False and "DOCTOR FAIL" in text


def test_authority_calls_on_but_dry_run_is_only_a_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    sec = d.check_robin(mk(tmp_path, robin_authority_calls_enabled=True))
    assert not lines_of(sec, d.FAIL) and "only logged" in lines_of(sec, d.WARN)


def test_listen_in_on_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    assert "LISTEN_IN" in lines_of(d.check_robin(mk(tmp_path, robin_listen_in_enabled=True)), d.WARN)


def test_device_on_without_family_core_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    assert "not mounted" in lines_of(d.check_robin(mk(tmp_path, robin_device_enabled=True)), d.WARN)


def test_lines_status_is_reported(tmp_path, monkeypatch):
    from friday.robin import lines

    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    assert "spoken lines status: PENDING" in lines_of(d.check_robin(mk(tmp_path)), d.OK)
    monkeypatch.setattr(lines, "LINE_STATUS", lines.APPROVED)
    assert "spoken lines status: APPROVED" in lines_of(d.check_robin(mk(tmp_path)), d.OK)


def test_missing_migration_fails_when_robin_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    monkeypatch.setattr(d, "known_revisions", lambda: {"0019_robin_family"})
    assert "0020_robin_device is missing" in lines_of(d.check_robin(mk(tmp_path, robin_enabled=True)), d.FAIL)
    assert not lines_of(d.check_robin(mk(tmp_path)), d.FAIL)  # off: only a warning


def test_scheduler_and_last_tick_when_on(tmp_path, monkeypatch):
    tick = tmp_path / "tick"
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tick))
    s = mk(tmp_path, robin_enabled=True)
    assert "no tick recorded" in lines_of(d.check_robin(s), d.WARN)
    opscounts.write_tick_marker()
    assert "scheduler task running; last tick" in lines_of(d.check_robin(s), d.OK)
    sec = d.check_robin(s, now=time.time() + 3600)
    assert "scheduler looks stopped" in lines_of(sec, d.WARN)


def test_parent_channel_line(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    assert "WhatsApp is not configured" in lines_of(d.check_robin(mk(tmp_path, robin_enabled=True)), d.WARN)
    s = mk(tmp_path, robin_enabled=True, whatsapp_access_token="PLANTED-token-1", whatsapp_phone_number_id="12345")  # noqa: S106
    assert "WhatsApp is configured" in lines_of(d.check_robin(s), d.OK)
    assert "PLANTED-token-1" not in "\n".join(c.message for c in d.check_robin(s).checks)  # no secret value in a line
