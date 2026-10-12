"""The task record: everything the PM knows, JSON-serialisable so a restart can resume it."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Status(StrEnum):
    NEW = "new"
    AWAITING_USER = "awaiting_user"   # a question is out; see ``pending``
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"               # polite stop (see decision log for the reason)
    CANCELLED = "cancelled"           # the user cancelled
    HANDOFF = "handoff"               # bucket the PM does not run (human in the loop)


TERMINAL = {Status.DONE, Status.STOPPED, Status.CANCELLED, Status.HANDOFF}


class StepState(BaseModel):
    name: str
    status: str = "pending"   # pending | running | done | failed | skipped
    attempts: int = 0
    reason: str | None = None


class Pending(BaseModel):
    """What the PM is waiting for from the user."""

    kind: str                  # category | bucket | slot | consent | widen | over_budget | step_question
    prompt: str
    slot: str | None = None
    step: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    unclear: int = 0


class Decision(BaseModel):
    ts: str
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    id: str
    user_id: str
    status: Status = Status.NEW
    language: str = "en"
    bucket: str | None = None
    category: str | None = None
    confidence: float = 0.0
    archetype: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    assumed: dict[str, Any] = Field(default_factory=dict)
    rounds_used: int = 0
    radius_km: float | None = None
    plan: list[StepState] = Field(default_factory=list)
    pending: Pending | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    inbox: list[str] = Field(default_factory=list)       # user messages, oldest first
    outbox: list[str] = Field(default_factory=list)      # PM messages to the user
    log: list[Decision] = Field(default_factory=list)
    updates_on: bool = False   # per-request opt-in for progress messages (default off)
    acked: bool = False
    stop_reason: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)  # saved places etc. from the caller


class TaskStore(Protocol):
    def save(self, task: TaskRecord) -> None: ...
    def load(self, task_id: str) -> TaskRecord | None: ...


class MemoryTaskStore:
    """Stores a JSON round-trip (so tests prove the record is really serialisable)."""

    def __init__(self) -> None:
        self._rows: dict[str, str] = {}

    def save(self, task: TaskRecord) -> None:
        self._rows[task.id] = task.model_dump_json()

    def load(self, task_id: str) -> TaskRecord | None:
        raw = self._rows.get(task_id)
        return TaskRecord.model_validate_json(raw) if raw else None


class JsonFileTaskStore:
    """One JSON file per task (adapter for a real DB table can implement ``TaskStore`` too)."""

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        safe = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")
        return self.dir / f"{safe}.json"

    def save(self, task: TaskRecord) -> None:
        tmp = self._path(task.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=1))
        tmp.replace(self._path(task.id))

    def load(self, task_id: str) -> TaskRecord | None:
        p = self._path(task_id)
        return TaskRecord.model_validate_json(p.read_text()) if p.exists() else None


def utcnow() -> datetime:
    return datetime.now(UTC)
