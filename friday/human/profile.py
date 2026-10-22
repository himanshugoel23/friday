"""The ``internal-test`` voice profile and the ON/OFF report of every voice switch.

``FRIDAY_VOICE_PROFILE=internal-test`` is for founder test calls to the allow-listed number only.
It switches ON every switch in ``INTERNAL_TEST_ON`` that the environment did not set explicitly.
Production / pilot keep the audible ones OFF until the founder approves the audio.
``FRIDAY_VOICE_STREAM_STT`` stays OFF in every profile: docs/LATENCY.md says keep it false until
the REST and streaming recognisers are compared on real recorded audio (not done yet).
"""

from __future__ import annotations

from typing import Any

SILENT = (  # no new sound or word: latency / turn-taking / measurement
    "intent_classifier", "voice_speculative_understanding", "llm_stream_to_tts",
    "voice_semantic_eot", "human_resume", "human_metrics", "human_noise_adapt",
)
AUDIBLE = (  # new sound, pace, wording or silence: founder must hear them first
    "human_backchannels", "human_prosody", "human_numbers", "human_variants", "human_mirror",
    "human_mood", "human_match_listener", "human_pauses",
)
INTERNAL_TEST_ON = SILENT + AUDIBLE

ENV = {
    "intent_classifier": "FRIDAY_INTENT_CLASSIFIER",
    "voice_speculative_understanding": "FRIDAY_VOICE_SPECULATIVE_UNDERSTANDING",
    "llm_stream_to_tts": "FRIDAY_LLM_STREAM_TO_TTS",
    "voice_semantic_eot": "FRIDAY_VOICE_SEMANTIC_EOT",
    "voice_vad_backend": "FRIDAY_VOICE_VAD_BACKEND",
    "voice_stream_stt": "FRIDAY_VOICE_STREAM_STT",
    "human_resume": "FRIDAY_HUMAN_RESUME",
    "human_metrics": "FRIDAY_HUMAN_METRICS",
    "human_noise_adapt": "FRIDAY_HUMAN_NOISE_ADAPT",
    "human_backchannels": "FRIDAY_HUMAN_BACKCHANNELS",
    "human_prosody": "FRIDAY_HUMAN_PROSODY",
    "human_numbers": "FRIDAY_HUMAN_NUMBERS",
    "human_variants": "FRIDAY_HUMAN_VARIANTS",
    "human_mirror": "FRIDAY_HUMAN_MIRROR",
    "human_mood": "FRIDAY_HUMAN_MOOD",
    "human_match_listener": "FRIDAY_HUMAN_MATCH_LISTENER",
    "human_pauses": "FRIDAY_HUMAN_PAUSES",
}


def vad_effective(settings: Any) -> str:
    """'silero', 'energy (silero requested, extra not installed: automatic fallback)' or 'energy'."""
    want = getattr(settings, "voice_vad_backend", "energy")
    if want != "silero":
        return "energy"
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return "energy (silero requested, 'vad' extra missing: automatic fallback)"
    return "silero"


def switch_report(settings: Any) -> list[tuple[str, str, bool, str]]:
    """[(env name, kind, on, note)] for every voice switch. Never contains a secret."""
    rows: list[tuple[str, str, bool, str]] = []
    for field, env in ENV.items():
        if field == "voice_vad_backend":
            eff = vad_effective(settings)
            rows.append((env, "silent", eff == "silero", f"requested {settings.voice_vad_backend}; effective {eff}"))
            continue
        on = bool(getattr(settings, field, False))
        kind = "audible" if field in AUDIBLE else "silent"
        note = ""
        if field == "voice_stream_stt":
            note = "kept OFF on purpose: not yet compared on real audio (docs/LATENCY.md)"
        rows.append((env, kind, on, note))
    return rows


def format_report(settings: Any) -> str:
    lines = [f"voice profile: {getattr(settings, 'voice_profile', 'production')}"]
    for env, kind, on, note in switch_report(settings):
        lines.append(f"  {env:<42} {'ON ' if on else 'OFF'}  ({kind}){'  ' + note if note else ''}")
    return "\n".join(lines)
