# ruff: noqa: E501
"""DoneGate: the one place that decides what a completion message may say.

``compose`` is pure (items in, message out). The model's summary is used verbatim only when the claim
is PROVEN, or when the claim is soft (information tasks). In strict mode a PARTIAL or UNPROVEN claim
never says "done": the model's sentence is dropped and replaced by the fixed wording in copy.py.
Evidence text from vendors is data: only structured fields (reference, who, when, duration) are
interpolated; a transcript line is never shown.

No new ``TaskStatus``: the task stays COMPLETED; the proof level lives on the stored ``DoneClaim``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from friday.core.clock import format_ist
from friday.core.models import Task, TaskResult
from friday.evidence import copy, policy
from friday.evidence.collector import mask_ref
from friday.evidence.models import (
    REFERENCE_KINDS,
    ClaimType,
    DoneClaim,
    DoneMessage,
    EvidenceItem,
    EvidenceKind,
    EvidenceLevel,
    ProofStatus,
)


@dataclass(frozen=True)
class ProofConfig:
    enabled: bool = False
    strict: bool = True
    strict_claims: tuple[str, ...] = tuple(str(c) for c in policy.DEFAULT_STRICT_CLAIMS)
    retention_days: int = 90
    lang: str = copy.DEFAULT_LANGUAGE

    @classmethod
    def from_settings(cls, s: Any) -> ProofConfig:
        return cls(
            enabled=bool(s.proof_enabled),
            strict=bool(s.proof_strict),
            strict_claims=tuple(str(c).strip() for c in s.proof_strict_claims if str(c).strip()),
            retention_days=int(s.proof_retention_days),
        )


def _duration(seconds: str) -> str:
    n = int(seconds or 0)
    if n <= 0:
        return "under a minute"
    return f"{n // 60} min" if n >= 60 else f"{n} sec"


@dataclass
class DoneGate:
    config: ProofConfig = field(default_factory=ProofConfig)

    # ------------------------------------------------------------------ pure part
    def judge(self, task: Task, items: Iterable[EvidenceItem]) -> tuple[DoneClaim, bool]:
        """(claim, strict). The claim is not stored here."""
        items = list(items)
        claim_type = policy.claim_type_for(task.type, task.spec.goal or "")
        strict = policy.is_strict(
            claim_type, strict=self.config.strict, strict_claims=self.config.strict_claims
        )
        status, missing = policy.evaluate(claim_type, items)
        claim = DoneClaim(
            user_id=task.requester_user_id,
            task_id=task.id,
            claim_type=claim_type,
            required_level=policy.required_level(claim_type, strict=strict),
            status=status,
            evidence_ids=[i.id for i in items],
            missing=missing,
        )
        return claim, strict

    def compose(
        self, task: Task, summary: TaskResult, items: Iterable[EvidenceItem]
    ) -> DoneMessage:
        items = list(items)
        claim, strict = self.judge(task, items)
        lang = self.config.lang
        base = [summary.summary]
        base += [f"{k}: {v}" for k, v in summary.details.items() if k != "booking_child_id"]
        base += summary.next_steps
        proof = self._proof_lines(claim, items, lang)
        missing = [copy.t(f"missing.{m}", lang) for m in claim.missing]
        if claim.status == ProofStatus.PROVEN:
            lines, says_done = base + proof, True
        elif not strict:  # soft claim: keep the message, say plainly what is thin
            note = copy.t("soft.note", lang) if claim.status == ProofStatus.UNPROVEN else None
            lines, says_done = base + proof + ([note] if note else missing), True
        elif claim.status == ProofStatus.PARTIAL:
            details = [x for x in base[1:] if x]
            lines = [copy.t("partial.head", lang), *details, *proof, *missing]
            says_done = False
        else:
            lines = [copy.t("unproven.head", lang), copy.t("unproven.offer", lang)]
            says_done = False
        return DoneMessage(
            text="\n".join(x for x in lines if x),
            status=claim.status,
            says_done=says_done,
            claim=claim,
        )

    def _proof_lines(self, claim: DoneClaim, items: list[EvidenceItem], lang: str) -> list[str]:
        out: list[str] = []
        refs = [i for i in items if i.kind in REFERENCE_KINDS and i.payload.get("ref")]
        for r in refs[:1]:  # one reference line is enough
            out.append(copy.t("proof.ref", lang, ref=mask_ref(r.payload["ref"])))
        for i in items:
            if i.kind == EvidenceKind.CALL_SUMMARY and i.level == EvidenceLevel.OBSERVED:
                out.append(
                    copy.t(
                        "proof.call",
                        lang,
                        who=i.payload.get("who") or "them",
                        when=format_ist(i.captured_at),
                        duration=_duration(i.payload.get("seconds", "0")),
                    )
                )
                break
        if any(i.kind == EvidenceKind.SCREENSHOT for i in items):
            out.append(copy.t("proof.screen", lang))
        if (
            not refs
            and claim.status == ProofStatus.PROVEN
            and claim.claim_type in (ClaimType.CANCELLED, ClaimType.RESCHEDULED)
        ):
            out.append(copy.t("proof.no_ref_exists", lang))
        return out

    # ------------------------------------------------------------------ with storage
    async def finalize(
        self, store: Any, task: Task, summary: TaskResult, items: Iterable[EvidenceItem]
    ) -> DoneMessage:
        """Store the items and the claim, return the message. A store failure must not block the
        completion message, so the caller wraps this (the engine uses ``call_opt``-style safety)."""
        items = list(items)
        msg = self.compose(task, summary, items)
        if items:
            await store.add_items(items)
        await store.save_claim(msg.claim)
        return msg
