# ruff: noqa: E501
"""The widget's press-to-talk, family side (T09): the ``VoiceIntake`` port of the device API (friday/robindevice/ports.py).

    POST /robin/device/voice (audio bytes, consent ``voice_messages`` checked by the device service)
      -> STT in the container (language hint = the parent's language) -> the bytes are dropped (never written to disk or the database,
         never logged) -> ``RobinHub.widget_voice`` (= ``parent_said(via="widget")``: stop / start / help / threat / 'I am fine' / care
         protocol) -> a reply in the PARENT'S language, plus (optional) the same words spoken by Robin's own TTS.

A spoken "madad karo" / "help" raises an SOS (EMERGENCY): it works while Robin is paused and before setup is finished, and ignores the time of
day. The reply never claims the child was told unless the alert engine accepted it. Logs carry member ids and outcome words, never speech.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import AudioClip, Language, MediaBlob
from friday.robin import answers as ans
from friday.robindevice.ports import VoiceResult

log = get_logger(__name__)
TTS_TIMEOUT_S = 6.0  # a slow voice must never delay or lose the text reply (small server)


def _language(lang: str | None) -> Language:
    return {"en": Language.EN, "hi": Language.HI}.get((lang or "").lower(), Language.HINGLISH)


class DeviceVoiceIntake:
    def __init__(self, hub: Any, *, stt: Callable[[], Any], tts: Callable[[], Any]) -> None:
        self.hub, self._stt, self._tts = hub, stt, tts

    @staticmethod
    def _get(getter: Callable[[], Any]) -> Any:
        try:
            return getter()
        except Exception:  # noqa: BLE001 - component not configured
            return None

    async def handle(self, parent_id: str, audio: bytes, mime: str, duration_s: int) -> VoiceResult:  # noqa: ARG002 - duration is the device's claim; unused
        c = self.hub.ctx
        member = await c.store.get_member(parent_id)
        fam = await c.store.get_family(member.family_id) if member is not None else None
        if member is None or fam is None:
            del audio
            return VoiceResult(False, None)
        lang = member.language if member.language in ("en", "hinglish", "hi") else "hinglish"
        try:
            text = await self._listen(audio, mime, lang)
        finally:
            del audio  # the recording is forgotten here; nothing wrote it anywhere
        slots = await c.slots(fam)
        if not text:
            log.info("robin: widget voice not understood (member %s)", member.id)
            return await self._speak(c.say("widget.unclear", lang, **slots), lang)
        reply = await self.hub.widget_voice(parent_id, text)
        if reply is not None and reply.action == "sos":
            say = c.say("widget.sos", lang, **slots)  # the widget is not a phone call: no 'stay on the line'
        elif reply is not None:
            say = reply.text
        elif ans.is_help(text) or ans.is_threat(text):
            log.warning("robin: widget help was heard but no alert was accepted (member %s)", member.id)
            say = c.say("widget.sos_failed", lang, **slots)  # honest: the child is NOT said to be told
        else:
            say = c.say("inbound.hello", lang, **slots)
        log.info("robin: widget voice handled (member %s, action %s)", member.id, reply.action if reply is not None else "none")
        return await self._speak(say, lang)

    async def _listen(self, audio: bytes, mime: str, lang: str) -> str | None:
        stt = self._get(self._stt)
        if stt is None:
            log.info("robin: widget voice: no speech-to-text configured")
            return None
        try:
            if mime == "audio/ogg":
                from friday.voice.voicenote import transcribe_voice_note

                tr = await transcribe_voice_note(stt, MediaBlob(data=audio, mime=mime), language_hint=_language(lang))
            else:
                tr = await stt.transcribe(AudioClip(data=audio, mime=mime), language_hint=_language(lang))
            return (tr.text or "").strip() or None
        except Exception as e:  # noqa: BLE001 - never raises into a safety path
            log.info("robin: widget voice could not be read (%s)", type(e).__name__)
            return None

    async def _speak(self, text: str, lang: str) -> VoiceResult:
        """The reply text, plus Robin's own spoken version when a TTS voice is available in time (else text only)."""
        tts = self._get(self._tts)
        if tts is None:
            return VoiceResult(True, text)
        try:
            clip = await asyncio.wait_for(tts.synthesize(text, _language(lang)), TTS_TIMEOUT_S)
            return VoiceResult(True, text, clip.data, clip.mime)
        except Exception as e:  # noqa: BLE001
            log.info("robin: widget reply voice unavailable (%s)", type(e).__name__)
            return VoiceResult(True, text)
