# ruff: noqa: E501
"""Plan persistence (restart-safe). The state holds NO code, password or card number: only the plan, progress and short
non-secret context (area, products read off a public page). "Delete everything" calls ``delete_user``."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from friday.steps.types import TERMINAL, PlanState

SAFE_ID = re.compile(r"^[a-f0-9]{8,32}$")


def new_plan_id() -> str:
    return uuid.uuid4().hex[:16]


class MemoryPlanStore:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def save(self, st: PlanState) -> None:
        self._d[st.id] = st.model_dump_json()

    def load(self, plan_id: str) -> PlanState | None:
        raw = self._d.get(plan_id)
        return PlanState.model_validate_json(raw) if raw else None

    def _all(self) -> list[PlanState]:
        return [PlanState.model_validate_json(v) for v in self._d.values()]

    def active_for(self, user_id: str) -> PlanState | None:
        mine = [s for s in self._all() if s.user_id == user_id and s.status not in TERMINAL]
        return max(mine, key=lambda s: s.updated_at) if mine else None

    def list_open(self) -> list[PlanState]:
        return [s for s in self._all() if s.status not in TERMINAL]

    def delete_user(self, user_id: str) -> int:
        gone = [k for k, v in self._d.items() if PlanState.model_validate_json(v).user_id == user_id]
        for k in gone:
            del self._d[k]
        return len(gone)


class JsonPlanStore(MemoryPlanStore):
    """One JSON file per plan, written atomically."""

    def __init__(self, root: Path | str) -> None:
        super().__init__()
        self.dir = Path(root) / "plans"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, plan_id: str) -> Path:
        if not SAFE_ID.match(plan_id):
            raise ValueError("bad plan id")
        return self.dir / f"{plan_id}.json"

    def save(self, st: PlanState) -> None:
        data = st.model_dump_json()
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.replace(tmp, self._path(st.id))
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    def load(self, plan_id: str) -> PlanState | None:
        try:
            return PlanState.model_validate_json(self._path(plan_id).read_text())
        except (OSError, ValueError):
            return None

    def _all(self) -> list[PlanState]:
        out: list[PlanState] = []
        for p in self.dir.glob("*.json"):
            with contextlib.suppress(OSError, ValueError):
                out.append(PlanState.model_validate_json(p.read_text()))
        return out

    def delete_user(self, user_id: str) -> int:
        n = 0
        for s in self._all():
            if s.user_id == user_id:
                with contextlib.suppress(OSError, ValueError):
                    self._path(s.id).unlink()
                    n += 1
        return n

    def purge_finished(self, now: datetime, keep_days: int = 14) -> int:
        n = 0
        for s in self._all():
            if s.status in TERMINAL and s.updated_at and datetime.fromisoformat(s.updated_at) < now - timedelta(days=keep_days):
                with contextlib.suppress(OSError, ValueError):
                    self._path(s.id).unlink()
                    n += 1
        return n
