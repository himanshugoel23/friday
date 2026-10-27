"""In-memory evidence store (tests, simulator). Same surface as ``db.repositories.evidence``."""

from __future__ import annotations

from datetime import datetime

from friday.evidence.models import DoneClaim, EvidenceItem


class MemoryEvidenceStore:
    def __init__(self) -> None:
        self.items: list[EvidenceItem] = []
        self.claims: dict[str, DoneClaim] = {}

    async def add_items(self, items: list[EvidenceItem]) -> None:
        self.items.extend(items)

    async def list_for_task(self, user_id: str, task_id: str) -> list[EvidenceItem]:
        return [i for i in self.items if i.user_id == user_id and i.task_id == task_id]

    async def save_claim(self, claim: DoneClaim) -> None:
        self.claims[claim.task_id] = claim

    async def get_claim(self, user_id: str, task_id: str) -> DoneClaim | None:
        c = self.claims.get(task_id)
        return c if c and c.user_id == user_id else None

    async def expire(self, now: datetime) -> tuple[int, list[str]]:
        gone = [i for i in self.items if i.expires_at and i.expires_at < now]
        self.items = [i for i in self.items if i not in gone]
        return len(gone), [i.object_key for i in gone if i.object_key]

    async def object_keys(self, user_id: str) -> list[str]:
        return [i.object_key for i in self.items if i.user_id == user_id and i.object_key]
