"""``DocumentExtractor`` (B15): menus / price lists / quote photos / PDFs ->
``ExtractedDocument`` via LLM vision. With the fake LLM it is deterministic from
the text content (text files) or the filename/metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from friday.core.interfaces import LLMClient, LLMMessage, ProviderError
from friday.core.logging import get_logger
from friday.core.models import ExtractedDocument, ExtractionKind, MediaBlob, PriceItem, Quote

from .heuristics import media
from .prompts import render_input, system_prompt
from .schemas import ExtractOut, strict_schema

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)
_VISION = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}


def _payload(media_blob: MediaBlob, kind: ExtractionKind, hint: str) -> dict:
    mime = (media_blob.mime or "").split(";")[0].lower()
    text = None
    if mime.startswith("text/") or mime in ("application/json", "text/csv"):
        text = media_blob.data.decode("utf-8", errors="replace")[:20000]
    return {"filename": media_blob.filename or "", "mime": mime, "size": len(media_blob.data),
            "hint": hint, "kind": kind.value, "text": text}


def to_document(out: ExtractOut) -> ExtractedDocument:
    quote = None
    if out.kind == ExtractionKind.QUOTE and (out.quote_amount_inr or out.quote_text):
        quote = Quote(business_name=out.business_name or "Unknown",
                      amount_inr=out.quote_amount_inr,
                      price_text=out.quote_text or f"₹{out.quote_amount_inr}",
                      inclusions=out.inclusions)
    return ExtractedDocument(
        kind=out.kind, text=out.text,
        items=[PriceItem(name=i.name, amount_inr=i.amount_inr, price_text=i.price_text,
                         unit=i.unit) for i in out.items],
        quote=quote, business_name=out.business_name,
        confidence=min(max(out.confidence, 0.0), 1.0))


class LLMDocumentExtractor:
    def __init__(self, llm: LLMClient, model: str | None = None) -> None:
        self.llm = llm
        self.model = model

    async def extract(self, media_blob: MediaBlob, *, kind: ExtractionKind =
                      ExtractionKind.GENERIC, hint: str = "") -> ExtractedDocument:
        payload = _payload(media_blob, kind, hint)
        attachments = [media_blob] if payload["mime"] in _VISION else []
        try:
            resp = await self.llm.complete(
                system=system_prompt("extract"),
                messages=[LLMMessage(role="user", content=render_input(
                    payload, "Extract the attached document."))],
                purpose="extract", model=self.model, max_tokens=4000,
                json_schema=strict_schema(ExtractOut), attachments=attachments)
            out = ExtractOut.model_validate_json(resp.text)
        except (ProviderError, ValidationError, ValueError) as e:
            log.warning("extract: LLM unusable (%s); metadata fallback", type(e).__name__)
            out = media.extract(payload)
        return to_document(out)


def build_document_extractor(c: Container) -> LLMDocumentExtractor:
    return LLMDocumentExtractor(c.llm)
