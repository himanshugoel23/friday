"""The lab must be physically unable to message real people."""

from __future__ import annotations

import pytest

from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.config import Settings
from friday.integration.sim import PersonaTelephony
from friday.lab.app import create_lab_app
from friday.lab.safety import (
    LabRefused,
    assert_no_live_channel,
    is_fake_number,
    lab_settings,
)
from tests.lab.conftest import SECRET_ENV


def test_app_refuses_to_start_when_the_settings_say_live():
    with pytest.raises(LabRefused):
        create_lab_app(env=Settings(_env_file=None, mode="live"))


def test_app_refuses_to_start_when_the_environment_says_live(monkeypatch):
    monkeypatch.setenv("FRIDAY_MODE", "live")
    with pytest.raises(LabRefused):
        create_lab_app()  # reads the environment itself


def test_cli_refuses_in_live_mode(monkeypatch, capsys):
    from friday.cli import main

    monkeypatch.setenv("FRIDAY_MODE", "live")
    assert main(["lab"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_live_environment_with_the_flag_still_builds_a_simulator_world(make_lab, monkeypatch):
    monkeypatch.setenv("FRIDAY_MODE", "live")
    lab = make_lab(env=Settings(_env_file=None, mode="live"), allow_live_env=True)
    w = lab.world
    assert w.settings.mode == "simulator" and not w.settings.is_live
    assert isinstance(w.c.messaging, SimulatorChannel)
    assert_no_live_channel(w.settings, w.c)


def test_the_lab_has_no_live_channel_configured(lab, monkeypatch):
    w = lab.world
    s = w.settings
    assert not s.is_live
    assert s.resolve_whatsapp() == "simulator"
    assert s.resolve_sms() == "fake"
    assert s.resolve_telephony() == "simulator"
    assert s.resolve_llm() == "fake"
    assert s.whatsapp_access_token is None and s.whatsapp_app_secret is None
    assert s.sarvam_api_key is None and s.msg91_auth_key is None
    assert isinstance(w.c.messaging, SimulatorChannel)
    assert isinstance(w.c.sms, FakeSMS)
    assert isinstance(w.telephony, PersonaTelephony)
    # the consumer stack dials only through the persona line
    assert isinstance(w.router.calls.orchestrator.engine.factory, PersonaTelephony)
    # nothing real was ever built in this container
    from friday.channels.whatsapp import WhatsAppCloudChannel

    assert not any(isinstance(i, WhatsAppCloudChannel) for i in w.c._instances.values())  # noqa: SLF001
    assert_no_live_channel(s, w.c)


def test_credentials_in_the_environment_never_reach_the_lab(make_lab, monkeypatch):
    for k, v in SECRET_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FRIDAY_PILOT_ALLOWED_NUMBERS", "+919876543210")
    lab = make_lab()
    s = lab.world.settings
    assert s.anthropic_api_key is None and s.openai_api_key is None
    assert s.whatsapp_access_token is None and s.sarvam_api_key is None
    assert s.pilot_allowed_numbers == []
    assert s.resolve_llm() == "fake"
    assert_no_live_channel(s, lab.world.c)


def test_no_webhook_or_simulator_or_voice_routes(lab):
    paths = {getattr(r, "path", "") for r in lab.client.app.routes}
    assert not any(
        p.startswith(("/webhooks", "/sim", "/voice", "/admin", "/google")) for p in paths
    )
    assert all(p.startswith("/lab/") or p == "" for p in paths if p)


def test_only_invented_numbers_are_accepted(lab):
    assert is_fake_number("+919800000001") and is_fake_number("+919000000010")
    assert not is_fake_number("+919876543210") and not is_fake_number("+14155550123")
    r = lab.post("/send", phone="+919876543210", text="hi")
    assert r.status_code == 422
    r = lab.post("/contact", phone="+919800000001", name="Real Person", number="+919876543210")
    assert r.status_code == 422
    assert lab.world.other_out == []


def test_lab_settings_ignore_the_environment_for_providers(monkeypatch):
    monkeypatch.setenv("FRIDAY_WHATSAPP_PROVIDER", "cloud")
    monkeypatch.setenv("FRIDAY_SMS_PROVIDER", "msg91")
    monkeypatch.setenv("FRIDAY_DATABASE_URL", "postgresql+asyncpg://prod/prod")
    monkeypatch.setenv("FRIDAY_REDIS_URL", "redis://prod:6379/0")
    s = lab_settings()
    assert s.resolve_whatsapp() == "simulator" and s.resolve_sms() == "fake"
    assert s.database_url.startswith("sqlite+aiosqlite:///:memory:")
    assert s.redis_url is None and s.resolve_queue() == "memory"


def test_ignored_files_hold_the_notes_file():
    from pathlib import Path

    assert "var/" in Path(".gitignore").read_text().splitlines()
