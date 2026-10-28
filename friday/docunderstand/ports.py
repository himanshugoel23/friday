"""VisionPort: the one place a model reads a document. Provider choice is the founder's.

The port gets ONE document (bytes in memory) and returns text plus candidate fields as JSON data.
Adapters must send our fixed instruction (``prompts.EXTRACTION_INSTRUCTION``) as the system text
and the document only as data; nothing the document says is ever added to the instruction.
``FakeVision`` serves tests; ``build_vision`` returns a stub for the real providers until the
founder picks one (setting ``FRIDAY_DOCS_VISION_PROVIDER``, default ``none``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF-", "application/pdf"),
)
ALLOWED_MIMES = ("image/jpeg", "image/png", "image/webp", "application/pdf")


def sniff_mime(data: bytes) -> str | None:
    """The type the BYTES say (the declared type is not trusted)."""
    for magic, mime in MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def count_pdf_pages(data: bytes) -> int:
    """Cheap page count without a PDF library: page objects, at least 1."""
    return max(1, len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data)))


class VisionUnavailable(Exception):
    """No provider is configured (or it is down). The user is told we cannot read files now."""


@dataclass
class VisionInput:
    data: bytes
    mime: str
    pages: int = 1


@dataclass
class VisionResult:
    doc_type: str | None = None  # the model's guess; the pipeline classifies on `text` first
    text: str = ""  # text read from the file (untrusted; never stored)
    fields: dict[str, Any] = field(default_factory=dict)
    confidences: dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    language: str | None = None


class VisionPort(Protocol):
    async def read(self, doc: VisionInput) -> VisionResult: ...


class FakeVision:
    """Tests: the 'file' carries its own canned JSON after the magic bytes (see ``fakes.sample``).
    ``calls`` records every document so a test can prove what was (not) sent."""

    def __init__(self, *, fail: bool = False, unavailable: bool = False) -> None:
        self.fail, self.unavailable = fail, unavailable
        self.calls: list[VisionInput] = []

    async def read(self, doc: VisionInput) -> VisionResult:
        self.calls.append(doc)
        if self.unavailable:
            raise VisionUnavailable
        if self.fail:
            raise RuntimeError("fake vision failure")
        start = doc.data.find(b"{")
        end = doc.data.rfind(b"}")
        try:
            payload = json.loads(doc.data[start : end + 1].decode("utf-8")) if start >= 0 else {}
        except ValueError:
            payload = {}
        return VisionResult(
            doc_type=payload.get("doc_type"),
            text=str(payload.get("text") or ""),
            fields=dict(payload.get("fields") or {}),
            confidences={k: float(v) for k, v in (payload.get("confidences") or {}).items()},
            overall=float(payload.get("overall", 0.9)),
            language=payload.get("language"),
        )


class UnavailableVision:
    """Default (provider ``none``): every document is answered with "cannot read files now"."""

    async def read(self, doc: VisionInput) -> VisionResult:
        raise VisionUnavailable


class ProviderStub:
    """Placeholder for a real provider (founder decision pending). Fails closed, loudly in logs.
    A real adapter implements ``read``: fixed instruction + the file as data, JSON out."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    async def read(self, doc: VisionInput) -> VisionResult:
        raise VisionUnavailable(f"vision provider {self.provider!r} is not implemented yet")


def build_vision(provider: str, settings: Any | None = None) -> VisionPort:
    """``openai`` reuses the brain's OPENAI_API_KEY; other named providers stay stubs."""
    name = (provider or "none").strip().lower()
    if name in ("", "none", "off"):
        return UnavailableVision()
    if name == "openai":
        from friday.docunderstand.openai_vision import DEFAULT_MODEL, OpenAIVision

        key = getattr(settings, "openai_api_key", None)
        return OpenAIVision(
            api_key=key.get_secret_value() if key else None,
            model=getattr(settings, "docs_vision_model", None) or DEFAULT_MODEL,
            timeout_s=getattr(settings, "docs_vision_timeout_s", 45.0),
            max_bytes=getattr(settings, "docs_max_bytes", 8 * 1024 * 1024),
        )
    return ProviderStub(name)
