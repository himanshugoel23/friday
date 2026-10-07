from friday.core.config import Settings


def make(**kw) -> Settings:
    base = dict(
        _env_file=None,
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
    )
    base.update(kw)
    return Settings(**base)


def test_defaults_are_simulator_and_fakes():
    s = make()
    assert s.mode == "simulator"
    assert s.resolve_llm() == "fake"
    assert s.resolve_stt() == "fake"
    assert s.resolve_tts() == "fake"
    assert s.resolve_telephony() == "simulator"
    assert s.resolve_whatsapp() == "simulator"
    assert s.resolve_sms() == "fake"
    assert s.resolve_directory() == "simulator"
    assert s.resolve_geocoder() == "simulator"
    assert s.resolve_hotels() == "simulator"
    assert s.live_problems() == []


def test_keys_enable_pure_compute_providers_but_never_side_effects_in_simulator():
    s = make(anthropic_api_key="sk-test", sarvam_api_key="x", telephony_provider="twilio")
    assert s.resolve_llm() == "anthropic"
    assert s.resolve_stt() == "sarvam"
    assert s.resolve_tts() == "sarvam"
    assert s.resolve_telephony() == "simulator"  # never real calls in simulator mode
    assert s.resolve_hotels() == "simulator"


def test_live_mode_reports_missing_credentials():
    s = make(mode="live")
    problems = s.live_problems()
    assert "missing ANTHROPIC_API_KEY" in problems
    assert "missing TWILIO_AUTH_TOKEN" in problems
    assert "missing WHATSAPP_ACCESS_TOKEN" in problems
    assert any("FRIDAY_SECRET_KEY" in p for p in problems)


def test_env_vars_and_vendor_aliases(monkeypatch):
    monkeypatch.setenv("FRIDAY_MODE", "live")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("FRIDAY_PROACTIVE_DAILY_CAP", "5")
    monkeypatch.setenv("FRIDAY_ADMIN_PHONES", '["+919800000000"]')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # blank == unset
    s = Settings(_env_file=None)
    assert s.mode == "live"
    assert s.twilio_account_sid == "AC123"
    assert s.proactive_daily_cap == 5
    assert s.admin_phones == ["+919800000000"]
    assert s.anthropic_api_key is None
