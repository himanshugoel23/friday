"""bytes -> limits -> VisionPort -> classify -> normalise -> scrub -> validate -> Document.

The file's bytes live only inside ``DocumentPipeline.process``: they go to the VisionPort and are
not stored, cached or logged; the Document carries a sha-256 and the kept fields, nothing else.
The pipeline can reach no task, call, message or brain: the worst a hostile document can do is
produce odd field values, which are length-capped, injection-checked and shown to the user.
No field value or document text is ever logged (only type, counts and codes).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta

from friday.core.clock import Clock, ist_date
from friday.core.logging import get_logger
from friday.core.scale import Cache
from friday.docunderstand.classify import classify
from friday.docunderstand.models import DocField, DocType, Document
from friday.docunderstand.ports import (
    ALLOWED_MIMES,
    VisionInput,
    VisionPort,
    VisionResult,
    VisionUnavailable,
    count_pdf_pages,
    sniff_mime,
)
from friday.docunderstand.safety import (
    is_gov_id_document,
    looks_like_injection,
    mask_passport_number,
    mentions_gov_id,
    scrub_gov_ids,
)
from friday.docunderstand.schemas import MIN_FIELDS, SPECS, normalise_fields, normalise_value
from friday.docunderstand.validators import Issue, validate
from friday.savings.bills import _KIND_LABEL, parse_bill_text  # noqa: PLC2701

log = get_logger(__name__)
COUNTER_TTL_S = 2 * 86400


@dataclass(frozen=True)
class DocLimits:
    max_bytes: int = 8 * 1024 * 1024
    max_pages: int = 5
    daily_cap: int = 10
    confirm_below: float = 0.75
    pending_days: int = 7


@dataclass
class Outcome:
    """``kind``: extracted | gov_id | bad_type | too_big | too_many_pages | limit | unreadable |
    unavailable | sensitive | failed."""

    kind: str
    document: Document | None = None
    issues: list[Issue] = field(default_factory=list)


class DocumentPipeline:
    def __init__(
        self,
        vision: VisionPort,
        clock: Clock,
        cache: Cache,
        limits: DocLimits = DocLimits(),  # noqa: B008
    ) -> None:
        self.vision, self.clock, self.cache, self.limits = vision, clock, cache, limits

    # ------------------------------------------------------------------ daily cap
    def _key(self, user_id: str) -> str:
        return f"doc:cnt:{user_id}:{ist_date(self.clock.now()).isoformat()}"

    async def used_today(self, user_id: str) -> int:
        return int(await self.cache.get(self._key(user_id)) or 0)

    # ------------------------------------------------------------------ main
    async def process(
        self, user_id: str, data: bytes, mime: str, *, language: str = "hinglish"
    ) -> Outcome:
        lim = self.limits
        mime = (mime or "").split(";")[0].strip().lower().replace("image/jpg", "image/jpeg")
        if len(data) > lim.max_bytes:
            return Outcome("too_big")
        sniffed = sniff_mime(data)
        if mime not in ALLOWED_MIMES or sniffed != mime:
            return Outcome("bad_type")
        pages = count_pdf_pages(data) if mime == "application/pdf" else 1
        if pages > lim.max_pages:
            return Outcome("too_many_pages")
        if await self.used_today(user_id) >= lim.daily_cap:
            return Outcome("limit")
        await self.cache.set(
            self._key(user_id), await self.used_today(user_id) + 1, ttl_s=COUNTER_TTL_S
        )
        digest = hashlib.sha256(data).hexdigest()
        size = len(data)
        try:
            res = await self.vision.read(VisionInput(data=data, mime=mime, pages=pages))
        except VisionUnavailable:
            return Outcome("unavailable")
        except Exception as e:  # noqa: BLE001 - a provider failure must not break the chat
            log.info("document read failed: %s", type(e).__name__)
            return Outcome("failed")
        finally:
            del data  # the bytes are not kept past this call
        return self._build(user_id, res, mime=mime, size=size, digest=digest, language=language)

    # ------------------------------------------------------------------ build
    def _build(
        self, user_id: str, res: VisionResult, *, mime: str, size: int, digest: str, language: str
    ) -> Outcome:
        text = res.text or ""
        if is_gov_id_document(res.doc_type, text):
            log.info("document refused: government id")
            return Outcome("gov_id")  # nothing is kept, not even a row
        doc_type = classify(text, res.doc_type)
        today = ist_date(self.clock.now())
        gov_words = mentions_gov_id(text)
        injection = looks_like_injection(text)
        overall = max(0.0, min(1.0, float(res.overall)))
        fields: dict[str, tuple[str, float, bool]] = {}  # name -> (value, conf, masked)

        raw_number = str(res.fields.get("number") or res.fields.get("number_masked") or "")
        extracted, _dropped = normalise_fields(doc_type, res.fields, res.confidences, overall)
        if doc_type == DocType.BILL:
            parse = parse_bill_text(text, today) if text.strip() else None
            if parse is not None and parse.sensitive:
                return Outcome("sensitive")
            if parse is not None:
                found: dict[str, object] = {"kind": parse.kind.value}
                if parse.biller != _KIND_LABEL.get(parse.kind) or "biller" not in extracted:
                    found["biller"] = parse.biller  # a known biller name; else keep the model's
                if parse.amount_paise is not None:
                    found["amount_paise"] = parse.amount_paise
                if parse.min_due_paise is not None:
                    found["min_due_paise"] = parse.min_due_paise
                if parse.due_date is not None:
                    found["due_date"] = parse.due_date.isoformat()
                for k, v in found.items():  # the deterministic parser wins over the model
                    nv = normalise_value(SPECS[DocType.BILL][k], v)
                    if nv is not None:
                        extracted[k] = (nv, 0.9)
        for name, (value, conf) in extracted.items():
            value = scrub_gov_ids(value, doc_mentions_gov_id=gov_words)
            if raw_number and doc_type != DocType.PASSPORT:
                value = value.replace(raw_number, "[removed]") if len(raw_number) > 5 else value
            if looks_like_injection(value):
                injection = True  # the value is dropped, never used
                continue
            if "[removed]" in value and name not in ("summary", "title", "address"):
                continue
            masked = name == "number_masked"
            fields[name] = (
                mask_passport_number(value) if masked and "*" not in value else value,
                conf,
                masked,
            )
        if doc_type == DocType.PASSPORT and raw_number:
            # an unmasked number may never survive, wherever the model put it
            full = "".join(ch for ch in raw_number if ch.isalnum())
            for k, (v, c, m) in list(fields.items()):
                if len(full) > 5 and full in v.replace(" ", "").upper():
                    fields[k] = (v.replace(full, mask_passport_number(full)), c, m)

        if len(fields) < MIN_FIELDS[doc_type] or overall < 0.3:
            return Outcome("unreadable")

        issues = validate(doc_type, {k: v[0] for k, v in fields.items()}, today)
        flagged = {f for i in issues for f in i.fields}
        doc_fields = {
            k: DocField(
                value=v,
                confidence=c,
                needs_confirm=injection or c < self.limits.confirm_below or k in flagged,
                masked=m,
            )
            for k, (v, c, m) in fields.items()
        }
        doc = Document(
            user_id=user_id,
            doc_type=doc_type,
            mime=mime,
            size_bytes=size,
            sha256=digest,
            language=language,
            confidence=overall,
            injection_flag=injection,
            fields=doc_fields,
            created_at=self.clock.now(),
            expires_at=self.clock.now() + timedelta(days=self.limits.pending_days),
        )
        log.info(
            "document read type=%s fields=%d issues=%s injection=%s",
            doc_type.value,
            len(doc_fields),
            [i.code for i in issues],
            injection,
        )
        return Outcome("extracted", doc, issues)
