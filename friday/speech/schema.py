"""What the Speech Understander returns, and the strict JSON schema the model must follow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RepairKind = Literal["filler", "self_correction", "mishearing", "number", "other"]
Source = Literal["llm", "rules", "raw"]
REPAIR_KINDS: tuple[str, ...] = ("filler", "self_correction", "mishearing", "number", "other")


class Repair(BaseModel):
    old: str
    new: str
    kind: RepairKind = "other"


class UnderstoodUtterance(BaseModel):
    """``text`` is what the rest of the system should read; ``original_text`` is kept for the logs."""

    original_text: str
    corrected_text: str
    source: Source = "raw"
    repairs: list[Repair] = Field(default_factory=list)
    reason: str | None = None  # why the model's answer was NOT used (grounding, timeout, secret...)
    apply: bool = True  # False in shadow mode: computed and logged, nothing changes
    channel: str = "voice_note"
    latency_ms: float = 0.0

    @property
    def changed(self) -> bool:
        return self.corrected_text.strip() != self.original_text.strip()

    @property
    def text(self) -> str:
        return self.corrected_text if self.apply else self.original_text

    def audit(self) -> dict[str, Any]:
        """Counts only (no words): safe for logs and for ``InboundMessage.raw``."""
        return {
            "source": self.source,
            "changed": self.changed,
            "repairs": len(self.repairs),
            "kinds": sorted({r.kind for r in self.repairs}),
            "reason": self.reason,
            "applied": self.apply,
            "ms": round(self.latency_ms),
        }


def wire_schema() -> dict[str, Any]:
    """Strict schema sent to the model (all fields required, closed enum)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["corrected_text", "repairs", "unintelligible"],
        "properties": {
            "corrected_text": {"type": "string"},
            "unintelligible": {"type": "boolean"},
            "repairs": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["old", "new", "kind"],
                    "properties": {
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                        "kind": {"type": "string", "enum": list(REPAIR_KINDS)},
                    },
                },
            },
        },
    }
