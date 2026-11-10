# ruff: noqa: E501
"""T19: `friday doctor --section robin` prints a "pilot readiness" line that names (never shows values of) what is missing for go-live."""

from __future__ import annotations

import asyncio
from pathlib import Path

from friday.core.config import Settings
from friday.ops import doctor as d

PLANTED_TOKEN = "planted-token-value-0001"
PLANTED_KEY = "planted-key-value-0002"


def mk(tmp_path: Path, **kw) -> Settings:
    kw.setdefault("database_url", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    kw.setdefault("pause_file", str(tmp_path / "var" / "PAUSED"))
    return Settings(_env_file=None, env="test", **kw)


def readiness(sec: d.Section):
    (c,) = [c for c in sec.checks if c.message.startswith("pilot readiness")]
    return c


def test_default_settings_list_every_gap_by_name_and_do_not_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    sec = d.check_robin(mk(tmp_path))
    c = readiness(sec)
    assert c.status == d.WARN  # a warning, never a failure: the doctor stays green while Robin is off
    for name in (
        "FRIDAY_ROBIN_ENABLED", "FRIDAY_ROBIN_DEVICE_ENABLED", "FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED", "FRIDAY_ROBIN_FORWARDED_CALLS_ENABLED",
        "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "SARVAM_API_KEY", "FRIDAY_GRIEVANCE_EMAIL", "FRIDAY_SUPPORT_INBOX",
        "FRIDAY_PUBLIC_BASE_URL", "FRIDAY_PILOT_ALLOWED_NUMBERS", "FRIDAY_MODE=live", "PENDING",
    ):
        assert name in c.message, name
    assert not [x for x in sec.checks if x.status == d.FAIL]


def test_authority_and_listen_in_are_never_on_the_to_do_list(tmp_path):
    msg = readiness(d.check_robin(mk(tmp_path))).message
    assert "AUTHORITY" not in msg and "LISTEN_IN" not in msg


def test_values_never_appear_and_set_items_drop_off_the_list(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    s = mk(
        tmp_path, robin_enabled=True, robin_device_enabled=True, whatsapp_access_token=PLANTED_TOKEN, whatsapp_phone_number_id="123456789",
        sarvam_api_key=PLANTED_KEY, grievance_email="officer@example.invalid", public_base_url="https://robin.example.invalid",
    )
    msg = readiness(d.check_robin(s)).message
    assert PLANTED_TOKEN not in msg and PLANTED_KEY not in msg and "123456789" not in msg and "example.invalid" not in msg
    for gone in ("FRIDAY_ROBIN_ENABLED (", "FRIDAY_ROBIN_DEVICE_ENABLED (", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "SARVAM_API_KEY", "FRIDAY_GRIEVANCE_EMAIL", "FRIDAY_PUBLIC_BASE_URL"):
        assert gone not in msg, gone
    assert "FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED" in msg


def test_concierge_staff_list_is_checked_by_env_name_only(tmp_path):
    s = mk(tmp_path, robin_enabled=True, robin_concierge_enabled=True)
    assert "ROBIN_CONCIERGE_STAFF (staff list" in "\n".join(d.robin_pilot_missing(s, {}))
    assert not [m for m in d.robin_pilot_missing(s, {"ROBIN_CONCIERGE_STAFF": "x"}) if m.startswith("ROBIN_CONCIERGE_STAFF")]


def test_runs_in_the_driver_with_robin_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_ROBIN_TICK_FILE", str(tmp_path / "tick"))
    secs = asyncio.run(d.run_sections(mk(tmp_path), offline=True, only="robin"))
    text, passed = d.render(secs, offline=True, as_json=False, secret_values=[])
    assert "pilot readiness" in text and passed
