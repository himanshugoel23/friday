"""Audio -> WhatsApp-compatible Ogg/Opus (mono, 16 kHz, voice bitrate) with ffmpeg.

``FfmpegConverter`` runs the ``ffmpeg`` binary as a subprocess (no shell, arguments as a list, the
audio goes in and out through pipes, a timeout kills it). When the binary is missing
``available`` is False and ``convert`` returns None: the caller logs it once and sends text.
``FakeConverter`` is the pure-fake path for tests: no process, deterministic bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from typing import Protocol

from friday.core.logging import get_logger
from friday.core.models import AudioClip

log = get_logger(__name__)

OGG_OPUS_MIME = "audio/ogg; codecs=opus"
FFMPEG_TIMEOUT_S = 20.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024


class AudioConverter(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def to_ogg_opus(self, clip: AudioClip) -> bytes | None:
        """Ogg/Opus bytes for ``clip``, or None when it cannot be converted."""
        ...


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffmpeg_args(binary: str) -> list[str]:
    return [
        binary, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", "pipe:0",
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "24k", "-application", "voip",
        "-f", "ogg", "pipe:1",
    ]  # fmt: skip


class FfmpegConverter:
    name = "ffmpeg"

    def __init__(self, binary: str | None = None, timeout_s: float = FFMPEG_TIMEOUT_S) -> None:
        self._binary = binary if binary is not None else ffmpeg_path()
        self.timeout_s = timeout_s
        self._warned = False

    @property
    def available(self) -> bool:
        return self._binary is not None

    async def to_ogg_opus(self, clip: AudioClip) -> bytes | None:
        if clip.mime.split(";")[0].strip().lower() == "audio/ogg" and clip.data[:4] == b"OggS":
            return clip.data  # already Ogg (Opus assumed: the TTS asked for it)
        if self._binary is None:
            if not self._warned:
                log.warning("ffmpeg not found: voice-note replies fall back to text")
                self._warned = True
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_args(self._binary),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            log.warning("ffmpeg could not start (%s)", type(e).__name__)
            return None
        try:
            out, err = await asyncio.wait_for(proc.communicate(clip.data), self.timeout_s)
        except TimeoutError:
            log.warning("ffmpeg timed out converting a voice reply")
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return None
        if proc.returncode != 0 or not out or len(out) > MAX_OUTPUT_BYTES:
            log.warning("ffmpeg conversion failed (%s)", err[:120].decode(errors="replace"))
            return None
        return out


class FakeConverter:
    """Offline stand-in: ``b"OggS" + the TTS bytes``. ``fail=True`` simulates a conversion error,
    ``present=False`` a server without ffmpeg."""

    name = "fake"

    def __init__(self, *, present: bool = True, fail: bool = False) -> None:
        self.present = present
        self.fail = fail
        self.calls: list[AudioClip] = []

    @property
    def available(self) -> bool:
        return self.present

    async def to_ogg_opus(self, clip: AudioClip) -> bytes | None:
        self.calls.append(clip)
        if not self.present or self.fail:
            return None
        return b"OggS" + clip.data
