"""Pilot profile, init-env, livecall (simulator only, offline)."""

from __future__ import annotations

import asyncio

import pytest

from friday.core.config import Settings
from friday.pilot import (
    DEFAULT_GOAL,
    HARD_MAX_SECONDS,
    estimate_cost_inr,
    init_env,
    preflight,
    run_livecall,
    single_call_lock,
)

OWN = "+919812345678"


def pilot(**kw) -> Settings:
    base = dict(
        _env_file=None, mode="live", profile="pilot", llm_provider="fake",
        public_base_url="https://abc-def.trycloudflare.com",
        sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
        sarvam_caller_ids=["+918065354620"], sarvam_api_key="k",
        secret_key="s" * 32, pin_pepper="p", field_key="f", index_key="i",
        pilot_allowed_numbers=[OWN],
    )
    base.update(kw)
    return Settings(**base)


def test_pilot_needs_only_voice_basics():
    assert pilot().live_problems() == []
    s = pilot()
    assert s.resolve_whatsapp() == "simulator" and s.resolve_sms() == "fake"
    assert s.resolve_hotels() == "simulator" and s.resolve_directory() == "simulator"
    assert s.call_record is False


def test_pilot_still_requires_keys_url_and_llm():
    p = pilot(sarvam_api_key=None, pin_pepper=None, public_base_url="http://localhost:8000",
              llm_provider="auto").live_problems()
    text = " ".join(p)
    for needle in ("SARVAM_API_KEY", "FRIDAY_PIN_PEPPER", "ANTHROPIC_API_KEY", "https"):
        assert needle in text
    assert any("localhost" in x or "https" in x for x in p)
    assert any("https" in x for x in pilot(public_base_url="http://x.example.com").live_problems())


def test_default_profile_stays_strict():
    p = " ".join(pilot(profile="default").live_problems())
    for needle in ("WHATSAPP_ACCESS_TOKEN", "MSG91_AUTH_KEY", "GOOGLE_PLACES_API_KEY",
                   "EXPEDIA_RAPID_API_KEY", "FRIDAY_OBJECT_STORE_URL"):
        assert needle in p
    assert Settings(_env_file=None).profile == "default"


def test_init_env_creates_and_never_overwrites(tmp_path, capsys):
    (tmp_path / ".env.example").write_text(
        "FRIDAY_MODE=simulator\nFRIDAY_SECRET_KEY=dev-insecure-change-me\nFRIDAY_PIN_PEPPER=\n"
        "SARVAM_API_KEY=\n", encoding="utf-8")
    assert init_env(tmp_path) == 0
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    shown = capsys.readouterr().out
    assert "FRIDAY_MODE=live" in text and "FRIDAY_PROFILE=pilot" in text
    assert "FRIDAY_TELEPHONY_PROVIDER=sarvam" in text
    keys = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    for k in ("FRIDAY_SECRET_KEY", "FRIDAY_PIN_PEPPER", "FRIDAY_FIELD_KEY", "FRIDAY_INDEX_KEY"):
        assert len(keys[k]) >= 40
        assert keys[k] not in shown
    assert "SARVAM_API_KEY" in shown
    (tmp_path / ".env").write_text("MINE=1\n", encoding="utf-8")
    init_env(tmp_path)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "MINE=1\n"


def test_preflight_allowlist_and_caps():
    assert preflight(pilot(), OWN, 120, False) == []
    assert any("allowed" in r for r in preflight(pilot(pilot_allowed_numbers=[]), OWN, 120, False))
    assert any("+919000000000" in r for r in preflight(pilot(), "+919000000000", 120, False))
    assert preflight(pilot(), OWN, HARD_MAX_SECONDS + 1, False)
    assert preflight(pilot(pilot_max_spend_inr=1.0), OWN, 180, False)
    assert preflight(pilot(profile="pilot", llm_provider="auto"), OWN, 120, False)
    assert preflight(Settings(_env_file=None), OWN, 120, True) == []  # simulate: no allowlist
    assert estimate_cost_inr(60) > 0


def test_single_call_lock(tmp_path):
    with single_call_lock(tmp_path, 600), pytest.raises(RuntimeError), single_call_lock(
        tmp_path, 600
    ):
        pass
    with single_call_lock(tmp_path, 600):
        pass


def test_livecall_refuses_unlisted_number(tmp_path):
    out: list[str] = []
    rc = asyncio.run(run_livecall(pilot(pilot_allowed_numbers=[]), OWN, yes=True,
                                  out=out.append, state_dir=tmp_path))
    assert rc == 2 and "FRIDAY_PILOT_ALLOWED_NUMBERS" in " ".join(out)


def test_livecall_simulate_end_to_end(tmp_path):
    out: list[str] = []
    s = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
                 media_dir=str(tmp_path / "m"))
    rc = asyncio.run(run_livecall(s, "+919000000000", yes=True, simulate=True,
                                  out=out.append, state_dir=tmp_path))
    text = "\n".join(out)
    assert rc == 0 and "CALL SUMMARY" in text and "Outcome" in text
    files = list(tmp_path.glob("livecall-*.txt"))
    assert files and "FRIDAY" in files[0].read_text(encoding="utf-8")
    assert not (tmp_path / "livecall.lock").exists()


def test_livecall_needs_typed_confirmation(tmp_path):
    out: list[str] = []
    s = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db")
    rc = asyncio.run(run_livecall(s, OWN, simulate=True, out=out.append,
                                  ask=lambda _p: "no", state_dir=tmp_path))
    assert rc == 1 and "No call was placed" in "\n".join(out)
    assert "test call quality" in DEFAULT_GOAL
