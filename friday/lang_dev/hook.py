"""The one function the inbound pipeline calls (behind ``FRIDAY_DEVANAGARI_INPUT``).

The returned message carries the Roman text the parsers read; the user's own words stay in
``raw['original_text']`` (``raw`` is never serialised or logged by the models), so logs and the
display keep what the user wrote.
"""

from __future__ import annotations

from friday.core.models import InboundMessage, MessageKind
from friday.lang_dev.normalise import normalise_text

TEXT_KINDS = (MessageKind.TEXT, MessageKind.VOICE_NOTE)


def normalise_inbound(msg: InboundMessage) -> InboundMessage:
    """``msg`` with Devanagari text turned into Roman Hinglish; unchanged when there is none."""
    if msg.kind not in TEXT_KINDS or not msg.text:
        return msg
    n = normalise_text(msg.text)
    if not n.changed:
        return msg
    raw = {**msg.raw, "original_text": n.original, "script": n.script}
    return msg.model_copy(update={"text": n.text, "raw": raw})
