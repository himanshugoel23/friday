"""A voice note arrives: download, speech-to-text, then the SAME path as typed text.

``VoiceInbound.transcribe`` replaces the pipeline's built-in transcription while
``FRIDAY_VOICE_NOTE_REPLIES`` is on (the download still goes through the channel's ``fetch_media``
with its size and type caps; the speech-to-text is the existing STT provider behind the
``Transcriber`` interface, which has a fake for tests). ``on_inbound`` then:

* remembers that this turn was spoken (so the reply can be a voice note) and in which script;
* asks "maine suna: ... sahi hai?" with two buttons ONLY when the transcript is not confident;
  a tap on "Haan, sahi" sends the transcript on as if it had been typed;
* answers a preference command ("text mein reply karo") without bothering the brain.

The transcript is never written to the shared cache: a pending confirmation lives in this process
for ten minutes (same rule as the router's pending call question).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from friday.chatbot_media import copy
from friday.chatbot_media.prefs import TurnState, VoiceState, parse_pref_command
from friday.core.interfaces import STTProvider
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MediaBlob, MessageKind, ReplyButton, User
from friday.lang_dev.normalise import mirror_script
from friday.voice.voicenote import prepare_voice_note, transcribe_voice_note

log = get_logger(__name__)

PENDING_TTL = timedelta(minutes=10)
Reply = Callable[[User, str, Sequence[ReplyButton]], Awaitable[None]]


@dataclass
class VoiceTranscript:
    text: str
    language: str | None = None
    confidence: float | None = None
    duration_s: float | None = None


class VoiceTooLong(Exception):
    """The note is longer than the speech-to-text limit (US-14.1: 3 minutes)."""


class Transcriber(Protocol):
    async def transcribe(self, blob: MediaBlob) -> VoiceTranscript: ...


class SttTranscriber:
    """The existing STT provider (Sarvam in production) behind the interface."""

    def __init__(self, stt: STTProvider) -> None:
        self.stt = stt

    async def transcribe(self, blob: MediaBlob) -> VoiceTranscript:
        note = prepare_voice_note(blob)
        if note.too_long:
            raise VoiceTooLong
        t = await transcribe_voice_note(self.stt, blob)
        return VoiceTranscript(
            text=(t.text or "").strip(),
            language=t.language.value if t.language else None,
            confidence=t.confidence,
            duration_s=note.duration_s,
        )


class FakeTranscriber:
    """Tests: the 'audio' is the transcript (UTF-8), unless ``text`` pins one."""

    def __init__(
        self,
        *,
        confidence: float | None = 0.95,
        text: str | None = None,
        language: str | None = "hinglish",
        fail: bool = False,
        too_long: bool = False,
    ) -> None:
        self.confidence, self.text, self.language = confidence, text, language
        self.fail, self.too_long = fail, too_long
        self.calls: list[MediaBlob] = []

    async def transcribe(self, blob: MediaBlob) -> VoiceTranscript:
        self.calls.append(blob)
        if self.too_long:
            raise VoiceTooLong
        if self.fail:
            raise RuntimeError("fake STT failure")
        text = self.text if self.text is not None else blob.data.decode("utf-8", "replace")
        return VoiceTranscript(text, self.language, self.confidence)


class VoiceInbound:
    def __init__(
        self,
        *,
        state: VoiceState,
        transcriber: Callable[[], Transcriber | None],
        fetch_media: Callable[[str], Awaitable[MediaBlob]] | None,
        reply: Reply,
        now: Callable[[], datetime],
        confirm_below: float = 0.6,
        voice_enabled: bool = True,
    ) -> None:
        self.voice_enabled = voice_enabled  # False: only the user's script is remembered
        self.state, self._transcriber, self._fetch = state, transcriber, fetch_media
        self.reply, self.now, self.confirm_below = reply, now, confirm_below
        self._pending: dict[str, tuple[datetime, str, str | None]] = {}

    # ------------------------------------------------------------------ transcription
    async def transcribe(self, msg: InboundMessage) -> str | None:
        """Download + STT; fills ``msg.raw["voice"]`` (confidence, language, error). No raise."""
        info: dict[str, Any] = {}
        msg.raw["voice"] = info
        transcriber = self._transcriber()
        if not msg.media_url or self._fetch is None or transcriber is None:
            info["error"] = "unavailable"
            return None
        try:
            blob = await self._fetch(msg.media_url)
        except Exception as e:  # noqa: BLE001
            log.info("voice note download failed: %s", type(e).__name__)
            info["error"] = "download"
            return None
        try:
            t = await transcriber.transcribe(blob)
        except VoiceTooLong:
            info["error"] = "too_long"
            return None
        except Exception as e:  # noqa: BLE001
            log.info("voice note STT failed: %s", type(e).__name__)
            info["error"] = "stt"
            return None
        info.update(confidence=t.confidence, language=t.language)
        return t.text or None

    # ------------------------------------------------------------------ the message
    async def on_inbound(self, user: User, msg: InboundMessage) -> InboundMessage | None:
        """The message to carry on with, or None when this module has answered it."""
        if (
            self.voice_enabled
            and msg.kind == MessageKind.BUTTON_REPLY
            and (msg.button_id or "") in copy.BUTTON_IDS.values()
        ):
            return await self._confirmation(user, msg)
        now = self.now()
        if msg.kind == MessageKind.VOICE_NOTE and self.voice_enabled:
            return await self._voice(user, msg, now)
        if msg.kind in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            script = mirror_script(msg.text or "")
            if not self.voice_enabled:
                await self.state.set_turn(user.id, TurnState(False, script, None, now))
                return msg
            if (mode := parse_pref_command(msg.text or "")) is not None:
                await self.state.set_mode(user.id, mode)
                await self.reply(user, copy.line(f"pref_{mode}", script), [])
                return None
            await self.state.set_turn(user.id, TurnState(False, script, None, now))
        elif msg.kind == MessageKind.BUTTON_REPLY:
            await self.state.set_turn(user.id, TurnState(False, "roman", None, now))
        return msg

    async def _voice(
        self, user: User, msg: InboundMessage, now: datetime
    ) -> InboundMessage | None:
        info: dict[str, Any] = msg.raw.get("voice") or {}
        text = (msg.text or "").strip()
        script = mirror_script(text)
        await self.state.set_turn(
            user.id, TurnState(True, script, info.get("language"), now)
        )
        if info.get("error") == "too_long":
            await self.reply(user, copy.line("too_long", script), [])
            return None
        if not text:
            await self.reply(user, copy.line("not_understood", script), [])
            return None
        conf = info.get("confidence")
        if conf is not None and conf < self.confirm_below:
            self._pending[user.id] = (now + PENDING_TTL, text, info.get("language"))
            await self.reply(
                user,
                copy.line("heard", script, text=text[:300]),
                [
                    ReplyButton(id=copy.BUTTON_IDS["yes"], title=copy.line("heard_yes", script)),
                    ReplyButton(id=copy.BUTTON_IDS["no"], title=copy.line("heard_no", script)),
                ],
            )
            return None
        if (mode := parse_pref_command(text)) is not None:  # "text mein reply karo", spoken
            await self.state.set_mode(user.id, mode)
            await self.reply(user, copy.line(f"pref_{mode}", script), [])
            return None
        msg.raw["from_voice"] = True
        return msg

    async def _confirmation(self, user: User, msg: InboundMessage) -> InboundMessage | None:
        entry = self._pending.pop(user.id, None)
        if entry is None or entry[0] <= self.now():
            await self.reply(user, copy.line("heard_expired"), [])
            return None
        _, text, language = entry
        if msg.button_id == copy.BUTTON_IDS["no"]:
            await self.reply(user, copy.line("heard_retry", mirror_script(text)), [])
            return None
        raw = {**msg.raw, "from_voice": True, "voice": {"language": language, "confirmed": True}}
        await self.state.set_turn(
            user.id, TurnState(True, mirror_script(text), language, self.now())
        )
        return msg.model_copy(
            update={"kind": MessageKind.VOICE_NOTE, "text": text, "button_id": None, "raw": raw}
        )
