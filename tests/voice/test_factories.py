"""Every FACTORIES entry under friday.voice resolves and builds."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from friday.core.config import Settings
from friday.core.container import FACTORIES, Container, _load
from friday.core.interfaces import (
    AudioClassifier,
    CallSessionRunner,
    STTProvider,
    TelephonyProvider,
    TTSProvider,
)

VOICE_PATHS = [
    (component, provider, path)
    for component, options in FACTORIES.items()
    for provider, path in options.items()
    if path.startswith("friday.voice.")
]


@pytest.mark.parametrize(("component", "provider", "path"), VOICE_PATHS)
def test_factory_importable(component, provider, path):
    assert callable(_load(path))


def _keyed() -> Settings:
    return Settings(
        _env_file=None,
        sarvam_api_key=SecretStr("k"),
        deepgram_api_key=SecretStr("k"),
        elevenlabs_api_key=SecretStr("k"),
        twilio_account_sid="ACx",
        twilio_auth_token=SecretStr("t"),
        twilio_from_number="+918069110001",
        exotel_sid="friday1",
        exotel_api_key="k",
        exotel_api_token=SecretStr("t"),
        exotel_caller_id="+918047110001",
    )


@pytest.mark.parametrize(("component", "provider", "path"), VOICE_PATHS)
async def test_factory_builds(component, provider, path, monkeypatch):
    monkeypatch.setenv("EXOTEL_VOICEBOT_APP_ID", "1")
    c = Container(_keyed())
    c.override("stt", _load("friday.voice.stt.fake:build_fake_stt")(c))
    c.override("tts", _load("friday.voice.tts.fake:build_fake_tts")(c))
    obj = _load(path)(c)
    expected = {
        "telephony": TelephonyProvider,
        "stt": STTProvider,
        "tts": TTSProvider,
        "audio_classifier": AudioClassifier,
        "call_runner": CallSessionRunner,
    }.get(component)
    if expected is not None:
        assert isinstance(obj, expected)
    if component == "voice_router":
        from fastapi import APIRouter

        assert isinstance(obj, APIRouter)
    closer = getattr(obj, "aclose", None)
    if closer:
        await closer()


def test_simulator_mode_container_resolution(vsettings):
    c = Container(vsettings)
    assert c.telephony.name == "simulator"
    assert c.stt.name == "fake" and c.tts.name == "fake"
    assert isinstance(c.call_runner, CallSessionRunner)
