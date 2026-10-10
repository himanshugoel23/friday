"""Pre-rendered / cached TTS (founder cost rule 4: no runtime TTS for fixed lines).

``CachedTTS`` wraps any ``TTSProvider``. Audio is keyed by (provider, voice, language,
rate, text) and kept in an in-memory LRU plus an optional on-disk store, so the fixed
lines (disclosure, hold lines, call-back / safe-exit line, inbound message) are
synthesised once per language+voice(+user name) and then replayed for free.

``prerender(texts, language)`` warms the cache; the runner calls it for the call's fixed
lines while the phone is still ringing, so they never cost latency or a vendor call
mid-conversation. Real call legs use ``synthesize_cached`` to learn whether a line was
a cache hit (billed TTS characters are reported per call).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections import OrderedDict
from pathlib import Path

from friday.core.logging import get_logger
from friday.core.models import AudioClip, Language, VoiceProfile
from friday.core.scale import Cache
from friday.voice.text import strip_fillers

log = get_logger(__name__)


class CachedTTS:
    def __init__(
        self,
        inner,
        *,
        cache_dir: str | None = None,
        max_items: int = 512,
        cache: Cache | None = None,
        ttl_s: int = 30 * 86400,
    ) -> None:
        self.inner = inner
        self.shared = cache  # S-10: shared Cache (Redis in prod) so every voice worker hits
        self.ttl_s = ttl_s
        self.name = inner.name
        self.supported_languages = inner.supported_languages
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_items = max_items
        self._mem: OrderedDict[str, AudioClip] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self.hits = 0
        self.misses = 0
        self.billed_chars = 0

    def voice_for(self, language: Language) -> VoiceProfile:
        return self.inner.voice_for(language)

    def _key(self, text: str, language: Language, voice: VoiceProfile) -> str:
        ver = getattr(self.inner, "dict_version", "") or ""
        raw = f"{self.name}|{voice.voice_id}|{language.value}|{voice.speaking_rate}|{text}"
        if ver:  # a changed pronunciation dictionary must not replay audio made with the old one
            raw += f"|dict:{ver}"
        temp = getattr(self.inner, "temperature", None)
        if temp is not None:  # audio made at another temperature must not be replayed
            raw += f"|temp:{temp}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _disk(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.audio" if self.cache_dir else None

    async def _read(self, key: str) -> AudioClip | None:
        """Memory, then shared Cache, then disk. Counts a hit when found."""
        if key in self._mem:
            self._mem.move_to_end(key)
            self.hits += 1
            return self._mem[key]
        if self.shared is not None:
            blob = await self.shared.get(f"tts:{key}")
            if isinstance(blob, (bytes, bytearray)) and b"\n" in blob:
                mime, _, data = bytes(blob).partition(b"\n")
                clip = AudioClip(data=data, mime=mime.decode() or "audio/wav")
                self._store(key, clip)
                self.hits += 1
                return clip
        path = self._disk(key)
        if path is not None and path.is_file():
            mime, _, data = path.read_bytes().partition(b"\n")
            clip = AudioClip(data=data, mime=mime.decode() or "audio/wav")
            self._store(key, clip)
            self.hits += 1
            return clip
        return None

    async def _write(self, key: str, clip: AudioClip) -> None:
        self._store(key, clip)
        if self.shared is not None:
            with contextlib.suppress(Exception):
                await self.shared.set(
                    f"tts:{key}", clip.mime.encode() + b"\n" + clip.data, ttl_s=self.ttl_s
                )
        path = self._disk(key)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(clip.mime.encode() + b"\n" + clip.data)
            except OSError:
                log.debug("tts cache not writable")

    async def synthesize_cached(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> tuple[AudioClip, bool]:
        clean = strip_fillers(text)
        voice = voice or self.voice_for(language)
        key = self._key(clean, language, voice)
        if key in self._mem:
            self._mem.move_to_end(key)
            self.hits += 1
            return self._mem[key], True
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:  # concurrent prerender + speak of the same line -> one vendor call
            clip = await self._read(key)
            if clip is not None:
                return clip, True
            clip = await self.inner.synthesize(clean, language, voice=voice)
            self.misses += 1
            self.billed_chars += len(clean)
            await self._write(key, clip)
            return clip, False

    # -- streaming (the inner provider yields PCM while it is still being made) ----------
    def can_stream(self) -> bool:
        return bool(getattr(self.inner, "streaming", False)) and hasattr(
            self.inner, "synthesize_stream"
        )

    def synthesize_stream(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ):
        return self.inner.synthesize_stream(text, language, voice=voice or self.voice_for(language))

    async def lookup(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip | None:
        """The cached clip for a line, or None (never calls the vendor)."""
        voice = voice or self.voice_for(language)
        return await self._read(self._key(strip_fillers(text), language, voice))

    async def remember(
        self, text: str, language: Language, clip: AudioClip, *, voice: VoiceProfile | None = None
    ) -> None:
        """Store a line that was streamed in full (same key as ``synthesize_cached``)."""
        clean = strip_fillers(text)
        voice = voice or self.voice_for(language)
        self.misses += 1
        self.billed_chars += len(clean)
        await self._write(self._key(clean, language, voice), clip)

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        clip, _ = await self.synthesize_cached(text, language, voice=voice)
        return clip

    async def prerender(self, texts: list[str], language: Language) -> int:
        """Warm the cache; returns how many lines needed a vendor call."""
        before = self.misses
        for t in texts:
            try:
                await self.synthesize_cached(t, language)
            except Exception as e:  # noqa: BLE001 - warming is best effort
                log.warning("tts prerender failed: %r", e)
        return self.misses - before

    def _store(self, key: str, clip: AudioClip) -> None:
        self._mem[key] = clip
        self._mem.move_to_end(key)
        while len(self._mem) > self.max_items:
            self._mem.popitem(last=False)

    async def aclose(self) -> None:
        closer = getattr(self.inner, "aclose", None)
        if closer:
            await closer()


def cached(tts, media_dir: str | None, cache: Cache | None = None) -> CachedTTS:
    if isinstance(tts, CachedTTS):
        return tts
    folder = str(Path(media_dir) / "tts_cache") if media_dir else None
    return CachedTTS(tts, cache_dir=folder, cache=cache)


def cached_tts(c) -> CachedTTS:  # c: Container
    """The container's TTS wrapped with the pre-render cache (+ shared Cache if wired).
    The disk copy is dev-only; in live the shared Cache is the store."""
    try:
        shared = c.get("cache")
    except Exception:  # noqa: BLE001 - not wired in this process role
        shared = None
    media = None if (c.settings.is_live and shared is not None) else c.settings.media_dir
    return cached(c.tts, media, shared)
