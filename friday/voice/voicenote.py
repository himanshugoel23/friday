"""V-6: WhatsApp voice note (Ogg/Opus) -> STT input.

Backend usage (inbound pipeline)::

    media = await channel.fetch_media(msg.media_url)
    note = prepare_voice_note(media)              # duration check (US-14.1: <= 3 min)
    if note.too_long: ...
    t = await transcribe_voice_note(c.stt, media)  # Transcription with detected language

Real STT vendors get 16 kHz mono WAV decoded with ffmpeg when available (Sarvam does
not take Ogg/Opus reliably); otherwise the original Ogg is sent (Deepgram decodes
Ogg/Opus natively). The fake STT reads the transcript from the Ogg comment header
(or plain text bytes from the simulator channel), so this runs offline.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field

from friday.core.interfaces import STTProvider
from friday.core.logging import get_logger
from friday.core.models import AudioClip, Language, MediaBlob, Transcription
from friday.voice.audio import is_ogg, parse_opus_ogg

log = get_logger(__name__)

MAX_VOICE_NOTE_S = 180  # US-14.1


@dataclass
class PreparedVoiceNote:
    clip: AudioClip  # what to hand to STT
    original_mime: str
    duration_s: float | None = None
    tags: dict[str, str] = field(default_factory=dict)
    decoded: bool = False  # True if transcoded to WAV

    @property
    def too_long(self) -> bool:
        return self.duration_s is not None and self.duration_s > MAX_VOICE_NOTE_S


def prepare_voice_note(media: MediaBlob) -> PreparedVoiceNote:
    """Inspect the container; no transcoding (sync, cheap)."""
    mime = (media.mime or "audio/ogg").split(";")[0].strip()
    if is_ogg(media.data):
        try:
            info = parse_opus_ogg(media.data)
        except ValueError:
            info = None
        return PreparedVoiceNote(
            clip=AudioClip(data=media.data, mime="audio/ogg", sample_rate=48000),
            original_mime=mime,
            duration_s=info.duration_s if info else None,
            tags=info.tags if info else {},
        )
    return PreparedVoiceNote(
        clip=AudioClip(data=media.data, mime=mime or "application/octet-stream"),
        original_mime=mime,
    )


async def ogg_to_wav(data: bytes, sample_rate: int = 16000) -> bytes | None:
    """Decode Ogg/Opus to mono PCM16 WAV with ffmpeg (None if unavailable/failed)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(data)
    if proc.returncode != 0 or not out:
        log.warning("ffmpeg could not decode voice note (%s)", err[:120].decode(errors="replace"))
        return None
    return out


async def transcribe_voice_note(
    stt: STTProvider, media: MediaBlob, *, language_hint: Language | None = None
) -> Transcription:
    note = prepare_voice_note(media)
    clip = note.clip
    if getattr(stt, "name", "") not in ("fake",) and is_ogg(media.data):
        wav = await ogg_to_wav(media.data)
        if wav:
            clip = AudioClip(data=wav, mime="audio/wav", sample_rate=16000)
    return await stt.transcribe(clip, language_hint=language_hint)
