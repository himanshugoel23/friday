"""FRIDAY_PROFILE=beta (live requirements, optional features) and the `friday pause` kill switch."""

from __future__ import annotations

import pytest

from friday.cli import main
from friday.core.config import Settings
from friday.core.container import Container
from friday.pause import (
    BLOCKED_JOB_KINDS,
    PausedError,
    install_pause_guard,
    is_paused,
    set_paused,
)

OWN = "+919812345678"


def beta(**kw) -> Settings:
    base = dict(
        _env_file=None, mode="live", profile="beta", llm_provider="auto",
        anthropic_api_key="a", public_base_url="https://friday.example.in",
        database_url="postgresql+asyncpg://u:p@db/friday",
        sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
        sarvam_caller_ids=["+918065354620"], sarvam_api_key="k",
        google_places_api_key="g",
        whatsapp_access_token="t", whatsapp_phone_number_id="1", whatsapp_app_secret="s",
        whatsapp_verify_token="a-random-verify-token",
        secret_key="s" * 32, pin_pepper="p", field_key="f", index_key="i",
        admin_token="adm",
        terms_url="https://friday.example.in/terms", privacy_url="https://friday.example.in/privacy",
        grievance_email="grievance@friday.example.in",
    )
    base.update(kw)
    return Settings(**base)


def test_beta_complete_config_is_ok_without_optional_features():
    s = beta()
    assert s.live_problems() == []
    assert s.resolve_hotels() == "off" and s.resolve_sms() == "off"  # disabled, never simulated
    assert s.resolve_whatsapp() == "cloud" and s.resolve_directory() == "google_places"
    assert s.call_record is False  # no object store -> recordings off
    notes = " ".join(s.optional_feature_notes())
    assert "hotel live rates: OFF" in notes and "SMS: OFF" in notes and "recordings" in notes


def test_beta_names_exactly_what_is_missing():
    p = beta(
        anthropic_api_key=None, sarvam_api_key=None, google_places_api_key=None,
        whatsapp_access_token=None, whatsapp_phone_number_id=None, whatsapp_app_secret=None,
        sarvam_telephony_auth_token=None, sarvam_caller_ids=[], admin_token=None,
        pin_pepper=None, index_key=None, field_key=None,
        whatsapp_verify_token="friday-dev-verify", public_base_url="http://localhost:8000",
        database_url="sqlite+aiosqlite:///./x.db",
        terms_url=None, privacy_url=None, grievance_email=None,
    ).live_problems()
    text = "\n".join(p)
    for needle in (
        "ANTHROPIC_API_KEY", "SARVAM_API_KEY", "SARVAM_TELEPHONY_AUTH_TOKEN", "FRIDAY_NUMBERS",
        "GOOGLE_PLACES_API_KEY", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "FRIDAY_ADMIN_TOKEN", "FRIDAY_PIN_PEPPER",
        "FRIDAY_INDEX_KEY", "FRIDAY_FIELD_KEY", "https", "PostgreSQL",
        "FRIDAY_TERMS_URL", "FRIDAY_PRIVACY_URL", "FRIDAY_GRIEVANCE_EMAIL",
    ):
        assert needle in text, needle
    for optional in ("EXPEDIA", "MSG91", "DLT_ENTITY_ID", "OBJECT_STORE"):
        assert optional not in text


def test_beta_optional_features_switch_on_when_configured():
    s = beta(
        expedia_rapid_api_key="k", expedia_rapid_shared_secret="s",
        msg91_auth_key="m", dlt_entity_id="e", object_store_url="s3://b/p",
    )
    assert s.resolve_hotels() == "expedia_rapid" and s.resolve_sms() == "msg91"
    assert s.call_record is True and s.live_problems() == []
    assert s.optional_feature_notes() == []


def test_beta_stays_strict_where_it_matters():
    assert "FRIDAY_INVITE_ONLY" in " ".join(beta(invite_only=False).live_problems())
    assert any("DEBUG" in x for x in beta(log_level="DEBUG").live_problems())
    weak = beta(secret_key="dev-insecure-change-me").live_problems()
    assert any("FRIDAY_SECRET_KEY" in x for x in weak)
    assert any("simulator" in x for x in beta(whatsapp_provider="simulator").live_problems())


def test_default_and_pilot_profiles_unchanged():
    assert Settings(_env_file=None).profile == "default"
    p = " ".join(beta(profile="default").live_problems())
    for needle in ("EXPEDIA_RAPID_API_KEY", "MSG91_AUTH_KEY", "FRIDAY_OBJECT_STORE_URL"):
        assert needle in p
    assert "ADMIN_TOKEN" not in p
    pilot = beta(profile="pilot", pilot_allowed_numbers=[OWN])
    assert pilot.resolve_whatsapp() == "simulator" and pilot.call_record is False


# ------------------------------------------------------------------ kill switch
def sim(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None, mode="simulator", env="test",
        database_url="sqlite+aiosqlite:///:memory:", pause_file=str(tmp_path / "PAUSED"), **kw,
    )


def test_pause_flag_file_and_env(tmp_path):
    s = sim(tmp_path)
    assert not is_paused(s)
    set_paused(s, True)
    assert is_paused(s)
    set_paused(s, False)
    assert not is_paused(s)
    assert is_paused(sim(tmp_path, paused=True))


def test_pause_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FRIDAY_PAUSE_FILE", str(tmp_path / "PAUSED"))
    assert main(["pause", "--status"]) == 0
    assert main(["pause"]) == 0
    assert (tmp_path / "PAUSED").exists()
    assert main(["pause", "--status"]) == 3
    assert "PAUSED" in capsys.readouterr().out
    assert main(["pause", "--resume"]) == 0
    assert not (tmp_path / "PAUSED").exists()


@pytest.mark.asyncio
async def test_guard_blocks_calls_and_nudges_but_not_replies(tmp_path):
    s = sim(tmp_path)
    c = Container(s)
    await c.startup()
    guarded = install_pause_guard(c)
    assert "telephony.place_call" in guarded and "job_queue.claim" in guarded

    queue = c.get("job_queue")
    from friday.core.scale import Job

    for kind in (*BLOCKED_JOB_KINDS, "inbound.message"):
        await queue.enqueue(Job(kind=kind, payload={}, dedupe_key=f"k:{kind}"))
    kinds = [*BLOCKED_JOB_KINDS, "inbound.message"]

    set_paused(s, True)
    claimed = await queue.claim("w", kinds=kinds, limit=10)
    assert [j.kind for j in claimed] == ["inbound.message"]  # replies keep flowing
    with pytest.raises(PausedError):
        await c.get("telephony").place_call(object())
    proactive = c.get("proactive")
    assert await proactive.tick() == []

    set_paused(s, False)
    claimed = await queue.claim("w", kinds=kinds, limit=10)
    assert {j.kind for j in claimed} == set(BLOCKED_JOB_KINDS)  # they wait, then run
    await c.aclose()


@pytest.mark.asyncio
async def test_guard_cancels_new_tasks_with_a_polite_notice(tmp_path):
    from friday.core.models import OnboardingStep, TaskSpec, TaskType, User, UserStatus
    from friday.pause import NOTICE

    s = sim(tmp_path, invite_only=False)
    c = Container(s)
    await c.startup()
    install_pause_guard(c)
    user = await c.repos.users.add(
        User(phone="+919700000001", status=UserStatus.ACTIVE, onboarding_step=OnboardingStep.DONE)
    )
    set_paused(s, True)
    engine = c.get("task_engine")
    task = await engine.create_task(user.id, TaskSpec(type=TaskType.ENQUIRY, goal="ask the time"))
    saved = await c.repos.tasks.get(task.id)
    assert saved.status.is_terminal  # cancelled, never dialled
    assert not await c.repos.tasks.list_calls(task.id)
    texts = [m.text for m in c.messaging.outbox if m.to_phone == "+919700000001"]
    assert NOTICE in texts
    await c.aclose()
