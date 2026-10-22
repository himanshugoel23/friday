"""The reply leaves: maybe in the user's script, maybe also as a voice note.

``OutboundHooks.before_send(msg)`` is called by the notifier for a free-form message to a user
that is INSIDE the 24-hour window (templates and out-of-window messages never reach it). It

1. mirrors the user's script (Devanagari variants of fixed lines, else unchanged) when
   ``FRIDAY_DEVANAGARI_INPUT`` is on;
2. when ``FRIDAY_VOICE_NOTE_REPLIES`` is on, asks ``policy.decide`` whether to speak; if so it
   synthesises the SAME text (hold cache first), converts it to Ogg/Opus, uploads it to the media
   endpoint, and sends the audio message by media id, BEFORE the text;
3. returns whether the text should still go out.

Every failure (no ffmpeg, TTS error, upload error, daily cap reached, channel without media
upload) is logged without the text and degrades to the plain text message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from friday.chatbot_media.ledger import VoiceLedger
from friday.chatbot_media.policy import Decision, decide
from friday.chatbot_media.prefs import VoiceState
from friday.chatbot_media.speech import VoiceSynthesizer
from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import OutboundMessage, SendReceipt
from friday.lang_dev.reply import to_script

log = get_logger(__name__)
VOICE_TURN_MAX_AGE_S = 10 * 60


@dataclass
class HookOutcome:
    msg: OutboundMessage
    suppress_text: bool = False  # the voice note carried it all
    receipt: SendReceipt | None = None  # the audio's receipt when text is suppressed
    reason: str = ""
    spoke: bool = False


class OutboundHooks:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Clock,
        state: VoiceState,
        ledger: VoiceLedger | None,
        synth: VoiceSynthesizer | None,
        channel: Any,
    ) -> None:
        self.settings, self.clock, self.state = settings, clock, state
        self.ledger, self.synth, self.channel = ledger, synth, channel

    async def before_send(self, msg: OutboundMessage, *, in_window: bool = True) -> HookOutcome:
        out = HookOutcome(msg)
        if not self._is_plain_user_text(msg):
            return out
        assert msg.user_id is not None
        try:
            turn = await self.state.turn(msg.user_id)
            fresh = turn is not None and (
                (self.clock.now() - turn.at).total_seconds() <= VOICE_TURN_MAX_AGE_S
            )
            if self.settings.devanagari_input and fresh and turn is not None:
                shown = to_script(msg.text or "", turn.script)
                if shown != msg.text:
                    out.msg = msg = msg.model_copy(update={"text": shown})
            if self.settings.voice_note_replies and in_window:
                spoke = bool(turn and fresh and turn.voice)
                await self._maybe_speak(out, spoke)
        except Exception as e:  # noqa: BLE001 - a hook failure must never lose the message
            log.warning("outbound hook failed (%s); sending text", type(e).__name__)
            out.suppress_text, out.receipt, out.reason = False, None, "hook_error"
        return out

    @staticmethod
    def _is_plain_user_text(msg: OutboundMessage) -> bool:
        return bool(
            msg.user_id
            and msg.text
            and msg.template is None
            and msg.media_url is None
            and msg.person_id is None
            and msg.business_id is None
        )

    async def _maybe_speak(self, out: HookOutcome, user_spoke: bool) -> None:
        msg = out.msg
        assert msg.user_id is not None
        mode = await self.state.mode(msg.user_id)
        decision: Decision = decide(
            msg.text,
            msg.buttons,
            mode=mode,
            user_spoke=user_spoke,
            max_chars=self.settings.voice_note_max_chars,
        )
        out.reason = decision.reason
        if not decision.speak:
            return
        if self.synth is None or self.ledger is None or not self._can_send_audio():
            out.reason = "voice_unavailable"
            log.info("voice reply skipped: no TTS or media upload on this channel")
            return
        if not await self.ledger.allow(msg.user_id):
            out.reason = "daily_cap"
            log.info("voice reply skipped: daily cap reached")
            return
        spoken = await self.synth.speak(msg.text or "")
        if spoken is None:
            out.reason = "synthesis_failed"
            return
        now = self.clock.now()
        media_id = self.synth.cache.media_id(spoken.key, now)
        try:
            if media_id is None:
                media_id = await self.channel.upload_media(
                    spoken.ogg, "audio/ogg; codecs=opus", "voice.ogg"
                )
                self.synth.cache.put_media_id(spoken.key, media_id, now)
            receipt: SendReceipt = await self.channel.send_audio(
                msg.to_phone, media_id, user_id=msg.user_id
            )
        except Exception as e:  # noqa: BLE001
            log.warning("voice reply upload/send failed (%s); sending text", type(e).__name__)
            out.reason = "upload_failed"
            return
        if not receipt.ok:
            log.warning("voice reply rejected (%s); sending text", receipt.error)
            out.reason = "send_rejected"
            return
        await self.ledger.record(msg.user_id, spoken.chars, cached=spoken.cached)
        out.spoke = True
        if not decision.send_text:
            out.suppress_text, out.receipt = True, receipt

    def _can_send_audio(self) -> bool:
        return callable(getattr(self.channel, "upload_media", None)) and callable(
            getattr(self.channel, "send_audio", None)
        )
