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


def test_live_requires_separate_keys():  # SECURITY-30
    s = make(mode="live")
    problems = " ".join(s.live_problems())
    assert "FRIDAY_PIN_PEPPER" in problems and "FRIDAY_INDEX_KEY" in problems
    assert "FRIDAY_FIELD_KEY" in problems
    ok = make(mode="live", pin_pepper="p" * 32, field_key_id="kms-key-1", index_key="i" * 32)
    assert not any("PEPPER" in p or "INDEX_KEY" in p for p in ok.live_problems())
    dev = make()
    assert dev.key_material("pin_pepper") != dev.key_material("index_key")
    assert len(dev.key_material("field_key")) == 32


def test_live_telephony_is_routed_and_csv_lists(monkeypatch):
    monkeypatch.setenv("FRIDAY_TELEPHONY_ROUTE", "exotel,twilio")
    monkeypatch.setenv("FRIDAY_NUMBERS", "+918000000001, +912200000002")
    monkeypatch.setenv("FRIDAY_ROLES", '["api","voice"]')
    s = Settings(_env_file=None, mode="live")
    assert s.resolve_telephony() == "routed"
    assert s.telephony_route == ["exotel", "twilio"]
    assert s.friday_numbers == ["+918000000001", "+912200000002"]
    assert s.roles == ["api", "voice"] and s.has_role("voice") and not s.has_role("batch")
    assert any("FRIDAY_TELEPHONY_ROUTE" in p for p in s.live_problems())
    configured = s.model_copy(
        update={"twilio_account_sid": "AC1", "twilio_auth_token": "t", "twilio_from_number": "+1"}
    )
    assert not any("TELEPHONY_ROUTE" in p for p in configured.live_problems())


def test_model_routing_never_opus_by_default():
    s = make()
    assert s.model_for("call_turn") == "claude-sonnet-5-5"
    assert s.model_for("interpret") == "claude-haiku-5-5"
    assert s.model_for("something_new") == "claude-haiku-5-5"
    assert s.model_for("interpret", escalate=True) == "claude-opus-5-5"
    assert "opus" not in " ".join(s.llm_models.values())


def test_scale_backends_resolution():
    s = make()
    assert (s.resolve_queue(), s.resolve_lock(), s.resolve_cache()) == ("memory",) * 3
    pg = make(database_url="postgresql+asyncpg://u:p@h/db", redis_url="redis://r:6379/0")
    assert (pg.resolve_queue(), pg.resolve_lock(), pg.resolve_cache()) == (
        "postgres",
        "postgres",
        "redis",
    )
    assert pg.resolve_rate_limiter() == "redis"


def test_live_rejects_debug_logging():  # SECURITY-26
    assert any("DEBUG" in p for p in make(mode="live", log_level="DEBUG").live_problems())
