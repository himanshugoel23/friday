"""What makes the lab unable to message real people.

Three layers, all tested (tests/lab/test_safety.py):

1. ``lab_settings`` builds a Settings object that pins EVERY provider to its simulator/fake and
   blanks every provider credential, whatever the environment says. It never reads ``.env``.
2. ``LabWorld`` overrides the messaging, sms and telephony components with the in-memory channel,
   fake SMS and persona telephony, then ``assert_no_live_channel`` checks them again.
3. Every phone number the lab accepts is an invented one from a fixed range
   (``is_fake_number``).
"""

from __future__ import annotations

import re
from typing import Any

from friday.core.config import Settings

# Invented ranges used by the tests and demos in this repo. The lab accepts nothing else.
_USER_RE = re.compile(r"^\+919800\d{6}$")
_CALLEE_RE = re.compile(r"^\+919000\d{6}$")


class LabRefused(RuntimeError):
    """The lab will not start (live mode in the environment without the explicit flag)."""


def is_fake_user_number(phone: str) -> bool:
    return bool(_USER_RE.match(phone or ""))


def is_fake_callee_number(phone: str) -> bool:
    return bool(_CALLEE_RE.match(phone or ""))


def is_fake_number(phone: str) -> bool:
    return is_fake_user_number(phone) or is_fake_callee_number(phone)


def environment_settings() -> Settings:
    """The environment's own settings (``FRIDAY_*`` variables), never the ``.env`` file."""
    return Settings(_env_file=None)


def check_may_start(env: Settings, *, allow_live_env: bool) -> None:
    """Refuse when the environment says live mode, unless the separate process flag is given.

    Even with the flag the lab stays on the simulator channel (``lab_settings`` pins the mode).
    """
    if env.is_live and not allow_live_env:
        raise LabRefused(
            "FRIDAY_MODE=live is set in this environment. The Chat Lab refuses to start. "
            "Unset FRIDAY_MODE, or pass --allow-live-env if you are sure; the lab still uses "
            "only the in-memory channel and fake numbers."
        )


def lab_settings(**overrides: Any) -> Settings:
    """Settings for the lab: simulator everywhere, no credentials, in-memory everything."""
    values: dict[str, Any] = dict(
        mode="simulator",
        env="dev",
        profile="default",
        database_url="sqlite+aiosqlite:///:memory:",
        queue_backend="memory",
        lock_backend="memory",
        cache_backend="memory",
        rate_limit_backend="memory",
        redis_url=None,
        object_store_url=None,
        field_key_id=None,
        llm_provider="fake",
        stt_provider="fake",
        tts_provider="fake",
        telephony_provider="simulator",
        whatsapp_provider="simulator",
        sms_provider="fake",
        directory_provider="simulator",
        geocoder_provider="simulator",
        hotel_provider="simulator",
        # credentials: blank, so nothing can authenticate to a provider
        anthropic_api_key=None,
        openai_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
        whatsapp_access_token=None,
        whatsapp_phone_number_id=None,
        whatsapp_app_secret=None,
        msg91_auth_key=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
        expedia_rapid_api_key=None,
        expedia_rapid_shared_secret=None,
        admin_token=None,
        pilot_allowed_numbers=[],
        admin_phones=[],
        invite_only=False,
        # the four consumer switches: on in the lab (session toggles flip them live)
        consumer_calls_enabled=True,
        savings_enabled=True,
        lifestate_enabled=True,
        google_enabled=False,  # needs a Google Cloud project: not part of the lab
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def assert_no_live_channel(settings: Settings, container: Any) -> None:
    """Raise AssertionError if anything in the lab could reach a real person."""
    from friday.channels.simulator import SimulatorChannel
    from friday.channels.sms import FakeSMS
    from friday.integration.sim import PersonaTelephony

    assert not settings.is_live, "lab settings are live"
    assert settings.resolve_whatsapp() == "simulator", "whatsapp provider is not the simulator"
    assert settings.resolve_sms() == "fake", "sms provider is not fake"
    assert settings.resolve_telephony() == "simulator", "telephony provider is not the simulator"
    for name in ("whatsapp_access_token", "whatsapp_app_secret", "msg91_auth_key"):
        assert getattr(settings, name) is None, f"{name} is set"
    assert isinstance(container.messaging, SimulatorChannel), "messaging is not the simulator"
    assert isinstance(container.sms, FakeSMS), "sms is not the fake"
    router = container.get("consumer")
    if router is not None and router.calls is not None:
        engine = router.calls.orchestrator.engine
        assert isinstance(engine.factory, PersonaTelephony), "calls do not use persona telephony"
