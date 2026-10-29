# ruff: noqa: E501
"""The service gateways call: ``respond(user, ReplyInput, legacy=...)``.

* FRIDAY_REPLY_WRITER_ENABLED off: the reply is the gateway's own text (``legacy``), byte for byte. Nothing changes.
* on: ``write_reply`` (LlmWriter, fact-checked, TemplateWriter fallback) decides the messages. Intents without typed
  facts (passthrough, proof, confirm) always keep the gateway's own text.
* FRIDAY_REPLY_LOG_ENABLED: every call is recorded (see log.py), whichever writer produced the text, so approved
  examples pile up even while the writer switch is off.

``respond`` never raises: any failure returns the legacy text.
"""

from __future__ import annotations

import re
from typing import Any

from friday.core.logging import get_logger
from friday.replywriter.log import ReplyLog
from friday.replywriter.schema import WRITABLE, Button, Facts, ReplyInput, ReplyOutput
from friday.replywriter.writer import write_reply

log = get_logger(__name__)
_DEV = re.compile(r"[ऀ-ॿ]")
_STRESS = re.compile(r"\b(urgent|emergency|pareshan|jaldi|asap|help me|bahut zaroori|tension|ghabra)\b", re.I)
_POLITE = re.compile(r"\b(please|kindly|aap|ji\b|kripya|sir|madam)\b", re.I)
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


def context_from(text: str | None, lang: str | None) -> dict[str, Any]:
    """lang / script / formality / mood / style flags from the user's own message (no text is kept)."""
    t = text or ""
    return {
        "lang": lang if lang in ("en", "hinglish", "hi") else "hinglish",
        "script": "devanagari" if _DEV.search(t) else "roman",
        "formality": "polite" if _POLITE.search(t) else "casual",
        "mood": "stressed" if _STRESS.search(t) else "normal",
        "style": ["emoji_ok"] if _EMOJI.search(t) else [],
    }


def legacy_output(messages: list[str], buttons: list[Button] | None = None) -> ReplyOutput:
    """The gateway's own text as an output (not validated: owned templates may be longer than a writer's budget)."""
    msgs = [m for m in messages if m and m.strip()] or [""]
    return ReplyOutput.model_construct(
        messages=msgs, question=None, buttons=buttons or [], proofs=[], writer="legacy", fact_check="skipped"
    )


class ReplyService:
    def __init__(self, *, writer_enabled: bool = False, replylog: ReplyLog | None = None, llm: Any = None, timeout_s: float = 6.0) -> None:
        self.writer_enabled, self.log, self.llm, self.timeout_s = writer_enabled, replylog, llm, timeout_s

    @classmethod
    def from_pipeline(cls, pipeline: Any) -> ReplyService | None:
        s = pipeline.settings
        writer, logging = bool(getattr(s, "reply_writer_enabled", False)), bool(getattr(s, "reply_log_enabled", False))
        if not (writer or logging):
            return None
        cipher = None
        if logging:
            try:
                from friday.core.crypto import get_field_cipher

                cipher = get_field_cipher()
            except Exception:  # noqa: BLE001 - no cipher: the log falls back to a 0600 plain file
                log.info("replylog: no field cipher; plain 0600 file")
        llm = None
        if writer:
            try:
                llm = pipeline.c.get("llm")
            except Exception:  # noqa: BLE001 - no LLM: the TemplateWriter alone is a valid writer
                log.info("reply writer: no LLM client; template writer only")
        return cls(
            writer_enabled=writer, llm=llm, timeout_s=float(getattr(s, "reply_writer_timeout_s", 6.0)),
            replylog=ReplyLog.from_settings(s, cipher=cipher, now=getattr(getattr(pipeline, "clock", None), "now", None)) if logging else None,
        )

    async def first_name(self, pipeline: Any, user: Any) -> str | None:
        try:
            name = (await pipeline.repos.profiles.get_or_default(user.id)).name
            return name.split()[0] if name else None
        except Exception:  # noqa: BLE001
            return None

    async def respond(self, user_id: str, inp: ReplyInput, legacy: list[str] | None = None) -> ReplyOutput:
        legacy_msgs = list(legacy if legacy is not None else inp.draft)
        try:
            if self.writer_enabled and (inp.intent in WRITABLE or not legacy_msgs):
                out = await write_reply(inp, llm=self.llm, use_llm=True, timeout_s=self.timeout_s)
            else:
                out = legacy_output(legacy_msgs, inp.buttons)
        except Exception:  # noqa: BLE001 - the reply writer must never lose a reply
            log.exception("reply writer failed; using the gateway text")
            out = legacy_output(legacy_msgs, inp.buttons)
        if self.log is not None:
            try:
                self.log.record(user_id, inp, out)
            except Exception:  # noqa: BLE001
                log.exception("replylog write failed")
        return out

    def react(self, text: str, kind: str, note: str = "") -> bool:
        if self.log is None:
            return False
        try:
            return self.log.react_by_text(text, kind, note)
        except Exception:  # noqa: BLE001
            return False

    def erase_user(self, user_id: str) -> int:
        if self.log is None:
            return 0
        try:
            return self.log.erase_user(user_id)
        except Exception:  # noqa: BLE001
            return 0


__all__ = ["Facts", "ReplyService", "context_from", "legacy_output"]
