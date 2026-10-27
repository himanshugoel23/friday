"""The conversation around a document: read it, ask "is this right?", take the answer.

Nothing is kept as a confirmed fact until the user taps "Haan, sahi hai". "Galat hai" opens a fix
turn ("name: value"); "Rehne do" deletes the pending document. The service never calls a task, a
call or the brain: a document cannot make Friday do anything.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from friday.core.clock import Clock, ist_date
from friday.core.logging import get_logger
from friday.core.models import ReplyButton
from friday.docunderstand import copy
from friday.docunderstand.models import DocField, DocStatus, DocType, Document
from friday.docunderstand.pipeline import DocumentPipeline
from friday.docunderstand.reply import buttons as reply_buttons
from friday.docunderstand.reply import summary_text
from friday.docunderstand.safety import has_gov_id_number, looks_like_injection, scrub_gov_ids
from friday.docunderstand.schemas import SHOW, SPECS, normalise_value
from friday.docunderstand.validators import validate

log = get_logger(__name__)
_FIX = re.compile(r"^\s*([^:=\n]{2,40}?)\s*[:=]\s*(.{1,300}?)\s*$", re.DOTALL)
_DROP_WORDS = {"rehne do", "rahne do", "skip", "cancel", "रहने दो", "छोड़ो", "chhodo", "chhod do"}
BillSink = Callable[[str, dict[str, str]], Awaitable[bool]]


class DocStore(Protocol):
    async def save(self, doc: Document) -> None: ...
    async def get(self, user_id: str, doc_id: str) -> Document | None: ...
    async def latest_open(self, user_id: str) -> Document | None: ...
    async def delete(self, user_id: str, doc_id: str) -> bool: ...


@dataclass
class DocReply:
    text: str
    buttons: list[ReplyButton] = field(default_factory=list)


def _aliases(doc_type: DocType) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in SPECS[doc_type]:
        for alias in {key, key.replace("_", " "), *(copy.label(key, lg) for lg in copy.LANGS)}:
            out[alias.strip().lower()] = key
    return out


class DocumentService:
    def __init__(
        self,
        pipeline: DocumentPipeline,
        store: DocStore,
        clock: Clock,
        *,
        retention_days: int = 180,
        bill_sink: BillSink | None = None,
    ) -> None:
        self.pipeline, self.store, self.clock = pipeline, store, clock
        self.retention_days, self.bill_sink = retention_days, bill_sink

    # ------------------------------------------------------------------ a file arrives
    async def handle_media(self, user_id: str, language: str, data: bytes, mime: str) -> DocReply:
        out = await self.pipeline.process(user_id, data, mime, language=copy.lang_of(language))
        if out.kind != "extracted" or out.document is None:
            return DocReply(copy.t(f"refuse.{out.kind}", language))
        doc = out.document
        await self.store.save(doc)
        return DocReply(summary_text(doc, out.issues, language), reply_buttons(doc, language))

    # ------------------------------------------------------------------ the three buttons
    async def handle_button(self, user_id: str, language: str, button_id: str) -> DocReply | None:
        parsed = copy.parse_button_id(button_id)
        if parsed is None:
            return None
        action, doc_id = parsed
        doc = await self.store.get(user_id, doc_id)
        if doc is None:
            return DocReply(copy.t("gone", language))
        if doc.status == DocStatus.CONFIRMED:
            return DocReply(copy.t("already", language))
        if action == "drop":
            await self.store.delete(user_id, doc_id)
            return DocReply(copy.t("dropped", language))
        if action == "fix":
            doc.status = DocStatus.AWAITING_FIX
            await self.store.save(doc)
            first = next((n for n in SHOW[doc.doc_type] if n in doc.fields), None)
            example = f"{copy.label(first, language)}: ..." if first else "name: value"
            text = copy.t("fix.ask", language, example=example)
            if doc.doc_type == DocType.PASSPORT:
                text += "\n" + copy.t("fix.passport_hint", language)
            return DocReply(text)
        return await self._confirm(doc, language)

    async def _confirm(self, doc: Document, language: str) -> DocReply:
        now = self.clock.now()
        for f in doc.fields.values():
            f.confirmed, f.needs_confirm = True, False
        doc.status, doc.confirmed_at = DocStatus.CONFIRMED, now
        doc.expires_at = now + timedelta(days=self.retention_days)
        await self.store.save(doc)
        key = "saved"
        if doc.doc_type == DocType.BILL and self.bill_sink is not None:
            try:
                if await self.bill_sink(doc.user_id, doc.values()):
                    key = "saved.bill"
            except Exception as e:  # noqa: BLE001 - the confirmed fields are already kept
                log.info("bill sink failed: %s", type(e).__name__)
        return DocReply(copy.t(key, language))

    # ------------------------------------------------------------------ a typed correction
    async def handle_text(self, user_id: str, language: str, text: str) -> DocReply | None:
        """A reply while a fix is open. Returns None for anything that is not a correction, so
        normal chat is never swallowed."""
        doc = await self.store.latest_open(user_id)
        if doc is None or doc.status != DocStatus.AWAITING_FIX:
            return None
        if text.strip().lower() in _DROP_WORDS:
            await self.store.delete(user_id, doc.id)
            return DocReply(copy.t("dropped", language))
        m = _FIX.match(text or "")
        if m is None:
            return None
        key = _aliases(doc.doc_type).get(m.group(1).strip().lower())
        if key is None:
            return None
        raw = m.group(2)
        label = copy.label(key, language)
        if has_gov_id_number(raw) or scrub_gov_ids(raw) != raw:
            return DocReply(copy.t("fix.refused", language))
        value = (
            None
            if looks_like_injection(raw)
            else normalise_value(SPECS[doc.doc_type][key], raw, from_user=True)
        )
        if value is None:
            return DocReply(copy.t("fix.bad_value", language, label=label))
        doc.fields[key] = DocField(
            value=value, confidence=1.0, source="user", masked=key == "number_masked"
        )
        issues = validate(doc.doc_type, doc.values(), ist_date(self.clock.now()))
        flagged = {f for i in issues for f in i.fields}
        low = self.pipeline.limits.confirm_below
        for k, f in doc.fields.items():
            f.needs_confirm = k in flagged or (
                f.source == "doc" and (f.confidence < low or doc.injection_flag)
            )
        doc.status = DocStatus.PENDING
        await self.store.save(doc)
        return DocReply(summary_text(doc, issues, language), reply_buttons(doc, language))
