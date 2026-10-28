# ruff: noqa: E501
"""A2A (Google Agent2Agent) wire types: Agent Card, Message, Task, JSON-RPC 2.0.

Field names follow the public A2A specification as remembered by the builder (camelCase on the wire,
task states submitted / working / input-required / completed / canceled / failed ...). The spec text
was NOT re-fetched while building (see docs/AGENT_TEAM_DESIGN.md, honest limits): a conformance check
against the current spec version is a to-do before talking to any third-party A2A agent.
Streaming (message/stream) and push notifications are NOT implemented (``capabilities`` says so).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = "0.3.0"


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class A2AModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    AUTH_REQUIRED = "auth-required"
    UNKNOWN = "unknown"


TERMINAL = frozenset({TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED, TaskState.REJECTED})


class Part(A2AModel):
    kind: Literal["text", "data"] = "text"
    text: str | None = None
    data: dict[str, Any] | None = None

    @classmethod
    def of_text(cls, text: str) -> Part:
        return cls(kind="text", text=text)

    @classmethod
    def of_data(cls, data: dict[str, Any]) -> Part:
        return cls(kind="data", data=data)


class Message(A2AModel):
    kind: Literal["message"] = "message"
    role: Literal["user", "agent"] = "user"
    parts: list[Part] = Field(default_factory=list)
    message_id: str = Field(default_factory=new_id)
    task_id: str | None = None
    context_id: str | None = None
    metadata: dict[str, Any] | None = None

    def text(self) -> str:
        return " ".join(p.text for p in self.parts if p.kind == "text" and p.text).strip()

    def data(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.parts:
            if p.kind == "data" and p.data:
                out.update(p.data)
        return out


class TaskStatus(A2AModel):
    state: TaskState
    message: Message | None = None
    timestamp: str = Field(default_factory=now_iso)


class Artifact(A2AModel):
    artifact_id: str = Field(default_factory=new_id)
    name: str | None = None
    parts: list[Part] = Field(default_factory=list)

    def data(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.parts:
            if p.kind == "data" and p.data:
                out.update(p.data)
        return out


class Task(A2AModel):
    kind: Literal["task"] = "task"
    id: str = Field(default_factory=new_id)
    context_id: str = Field(default_factory=new_id)
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @property
    def state(self) -> TaskState:
        return self.status.state

    def status_text(self) -> str:
        return self.status.message.text() if self.status.message else ""

    def result_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for a in self.artifacts:
            out.update(a.data())
        return out


class Skill(A2AModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class Capabilities(A2AModel):
    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False


class AgentCard(A2AModel):
    """What an agent publishes at ``/.well-known/agent.json`` (or ``agent-card.json``)."""

    name: str
    description: str
    url: str
    version: str = "1"
    protocol_version: str = PROTOCOL_VERSION
    capabilities: Capabilities = Field(default_factory=Capabilities)
    default_input_modes: list[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    skills: list[Skill] = Field(default_factory=list)

    def has_skill(self, skill_id: str) -> bool:
        return any(s.id == skill_id for s in self.skills)


# ---------------------------------------------------------------- JSON-RPC 2.0
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
TASK_NOT_FOUND, TASK_NOT_CANCELABLE, UNSUPPORTED_OPERATION = -32001, -32002, -32004
# Friday-specific, in the implementation-defined range
DEPTH_EXCEEDED, BUDGET_EXCEEDED = -32010, -32011


class A2AError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def rpc_request(method: str, params: dict[str, Any], rid: str | int | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid if rid is not None else new_id(), "method": method, "params": params}


def rpc_result(rid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_error(rid: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}
