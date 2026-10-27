"""Build the hooks from the container. Only called while a switch is on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from friday.chatbot_media import copy as _copy  # noqa: F401  (registers the Devanagari variants)
from friday.chatbot_media.convert import FfmpegConverter
from friday.chatbot_media.inbound import SttTranscriber, VoiceInbound
from friday.chatbot_media.ledger import VoiceLedger
from friday.chatbot_media.outbound import OutboundHooks
from friday.chatbot_media.prefs import VoiceState
from friday.chatbot_media.speech import VoiceSynthesizer
from friday.core.container import ComponentNotAvailable
from friday.core.logging import get_logger
from friday.core.scale import Cache, MemoryCache

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)


def _opt(c: Container, name: str) -> Any:
    try:
        return c.get(name)
    except ComponentNotAvailable:
        return None
    except Exception as e:  # noqa: BLE001 - a missing key must not stop the chatbot
        log.warning("chatbot_media: %s could not be built (%s)", name, type(e).__name__)
        return None


def shared_state(c: Container) -> VoiceState:
    """One VoiceState per container (the notifier and the inbound pipeline share the cache)."""
    state = getattr(c, "_voice_state", None)
    if state is None:
        cache: Cache = _opt(c, "cache") or MemoryCache(c.clock)
        state = VoiceState(cache)
        c._voice_state = state  # type: ignore[attr-defined]
    return state


def attach_outbound(c: Container, notifier: Any) -> OutboundHooks:
    s = c.settings
    state = shared_state(c)
    synth = ledger = None
    if s.voice_note_replies:
        converter = FfmpegConverter()
        if not converter.available:
            log.warning("FRIDAY_VOICE_NOTE_REPLIES is on but ffmpeg is missing: replies stay text")
        tts = _opt(c, "tts")
        if tts is not None:
            synth = VoiceSynthesizer(tts, converter)
        ledger = VoiceLedger(
            state.cache,
            c.clock,
            daily_cap=s.voice_note_daily_cap,
            cost_per_1k_chars_inr=s.voice_note_cost_per_1k_chars_inr,
        )
    hooks = OutboundHooks(
        settings=s, clock=c.clock, state=state, ledger=ledger, synth=synth,
        channel=notifier.messaging,
    )  # fmt: skip
    notifier.outbound_hook = hooks
    return hooks


def build_inbound(c: Container, pipeline: Any) -> VoiceInbound:
    """The voice-note side of the inbound pipeline (only built while the voice switch is on)."""
    s = c.settings

    def transcriber() -> SttTranscriber | None:
        stt = _opt(c, "stt")
        return SttTranscriber(stt) if stt is not None else None

    messaging = _opt(c, "messaging")
    return VoiceInbound(
        state=shared_state(c),
        transcriber=transcriber,
        fetch_media=messaging.fetch_media if messaging is not None else None,
        reply=lambda user, text, buttons: pipeline.reply(user, text, buttons),
        now=c.clock.now,
        confirm_below=s.voice_note_confirm_below,
        voice_enabled=s.voice_note_replies,
    )
