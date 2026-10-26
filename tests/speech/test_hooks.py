"""Where the layer plugs in: voice notes (not business messages) and the caller's call turns."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from friday.api.inbound import InboundPipeline
from friday.core.models import InboundMessage, MessageKind
from friday.speech.schema import UnderstoodUtterance


class StubUnderstander:
    def __init__(self, corrected, apply=True, boom=False):
        self.corrected, self.apply, self.boom, self.channels = corrected, apply, boom, []

    def wants(self, channel):
        return channel in {"voice_note", "call"}

    async def understand(self, text, ctx=None, *, channel="voice_note", **_):
        self.channels.append(channel)
        if self.boom:
            raise RuntimeError("x")
        return UnderstoodUtterance(
            original_text=text, corrected_text=self.corrected, source="llm",
            apply=self.apply, channel=channel,
        )


def pipeline(und):
    async def context(_user):
        return None

    return SimpleNamespace(_speech_und=lambda: und, context=context)


def msg(kind, text="umm kal salon jana hai"):
    return InboundMessage(channel="whatsapp", from_phone="+919999900001", kind=kind, text=text)


def go(und, m):
    return asyncio.run(InboundPipeline._speech_understand(pipeline(und), SimpleNamespace(id=1), m))


def test_voice_note_is_cleaned_and_original_kept():
    out = go(StubUnderstander("kal salon jana hai"), msg(MessageKind.VOICE_NOTE))
    assert out.text == "kal salon jana hai"
    assert out.raw["original_text"] == "umm kal salon jana hai"
    assert "speech" in out.raw


def test_shadow_or_error_changes_nothing():
    m = msg(MessageKind.VOICE_NOTE)
    assert go(StubUnderstander("x y z", apply=False), m).text == m.text
    assert go(StubUnderstander("x", boom=True), m).text == m.text


def test_typed_text_is_off_by_default_channel_rule():
    und = StubUnderstander("changed")
    m = msg(MessageKind.TEXT)
    assert go(und, m).text == m.text and und.channels == []
