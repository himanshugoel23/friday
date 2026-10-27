"""Evidence on a refund case, in the proof module's vocabulary (``friday.evidence.models``).

Honesty rules (same spirit as ``friday/evidence/collector.py``):
* ``observed`` only for facts our own code saw: it comes ONLY from ``from_proof_item`` (a proof row
  of a follow-up task Friday ran). A user can never produce an observed or vendor_stated item.
* ``vendor_stated`` likewise only through ``from_proof_item`` (the callee said it on a call).
* What the user forwards (a refund SMS, a receipt, a bank line) is ``user_supplied``. The text is
  scrubbed and cut; a receipt keeps only its sha-256 and the amount; no bytes, no file.
* An amount counts as stated only when its digits really occur in the text the user forwarded.
* Friday cannot see the bank: proof of receipt is a user-supplied (or better) item that states the
  amount, or the user's own confirmation.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from friday.calls.privacy import scrub
from friday.evidence.models import EvidenceItem, EvidenceKind, EvidenceLevel
from friday.refunds.models import Basis, RefundCase, RefundEvidence

MAX_SUMMARY = 200
PROOF_OF_AMOUNT_KINDS = frozenset(
    {
        EvidenceKind.RECEIPT_FILE,
        EvidenceKind.CONFIRMATION_TEXT,
        EvidenceKind.VENDOR_MESSAGE,
        EvidenceKind.SCREENSHOT,
        EvidenceKind.TRANSCRIPT_EXCERPT,
    }
)
_DIGITS = re.compile(r"[^0-9.]")


def amount_in_text(text: str, paise: int | None) -> bool:
    """True when the rupee figure occurs in ``text`` (commas and 'Rs'/'INR' ignored)."""
    if not paise or paise <= 0:
        return False
    rupees, rem = divmod(paise, 100)
    flat = re.sub(r"(?<=\d),(?=\d)", "", text or "")
    want = str(rupees) if rem == 0 else f"{rupees}.{rem:02d}"
    return re.search(rf"(?<![\d.]){re.escape(want)}(?![\d])", flat) is not None


def from_user_text(
    case: RefundCase, text: str, *, now: datetime, amount_paise: int | None = None
) -> RefundEvidence:
    """A refund SMS / email / bank line the user forwarded: user_supplied."""
    stated = amount_paise if amount_in_text(text, amount_paise) else None
    return RefundEvidence(
        user_id=case.user_id,
        case_id=case.id,
        kind=EvidenceKind.CONFIRMATION_TEXT,
        level=EvidenceLevel.USER_SUPPLIED,
        summary=scrub(text)[:MAX_SUMMARY],
        amount_paise=stated,
        captured_at=now,
    )


def from_receipt(
    case: RefundCase, data: bytes, *, now: datetime, amount_paise: int | None = None
) -> RefundEvidence:
    """A receipt / screenshot the user sent: ONLY its sha-256 and the amount are kept."""
    return RefundEvidence(
        user_id=case.user_id,
        case_id=case.id,
        kind=EvidenceKind.RECEIPT_FILE,
        level=EvidenceLevel.USER_SUPPLIED,
        sha256=hashlib.sha256(data).hexdigest(),
        amount_paise=amount_paise,
        captured_at=now,
    )


def from_user_confirmation(case: RefundCase, *, now: datetime, amount_paise: int) -> RefundEvidence:
    return RefundEvidence(
        user_id=case.user_id,
        case_id=case.id,
        kind=EvidenceKind.USER_CONFIRMED,
        level=EvidenceLevel.USER_SUPPLIED,
        summary="user said the refund arrived",
        amount_paise=amount_paise,
        captured_at=now,
    )


def from_vendor_promise(case: RefundCase, *, now: datetime, amount_paise: int) -> RefundEvidence:
    """The user relayed the vendor's promise. It is the USER's word about what the vendor said, so
    it is user_supplied, never vendor_stated."""
    return RefundEvidence(
        user_id=case.user_id,
        case_id=case.id,
        kind=EvidenceKind.VENDOR_MESSAGE,
        level=EvidenceLevel.USER_SUPPLIED,
        summary="vendor promise, relayed by the user",
        amount_paise=amount_paise,
        captured_at=now,
    )


def from_proof_item(
    case: RefundCase, item: EvidenceItem, *, now: datetime
) -> RefundEvidence | None:
    """Link an evidence item of a Friday follow-up task (``friday.evidence``) to the case, keeping
    its level. Another user's item, or an item that expired, is refused."""
    if item.user_id != case.user_id:
        return None
    if item.expires_at is not None and item.expires_at < now:
        return None
    return RefundEvidence(
        user_id=case.user_id,
        case_id=case.id,
        kind=item.kind,
        level=item.level,
        summary=(item.summary or "")[:MAX_SUMMARY],
        payload=dict(item.payload),
        sha256=item.sha256,
        proof_item_id=item.id,
        captured_at=item.captured_at,
    )


def basis_for_received(
    evidence: list[RefundEvidence], received_total_paise: int, tolerance_paise: int
) -> Basis:
    """PROOF when the attached items that can state an amount (a forwarded refund message, a
    receipt) together state at least what was received; otherwise the user's own word (USER)."""
    stated = sum(
        e.amount_paise
        for e in evidence
        if e.kind in PROOF_OF_AMOUNT_KINDS and e.amount_paise is not None and e.amount_paise > 0
    )
    return (
        Basis.PROOF if stated and stated >= received_total_paise - tolerance_paise else Basis.USER
    )
