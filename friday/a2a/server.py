# ruff: noqa: E501
"""A2A server adapter: wraps ONE agent handler so it speaks JSON-RPC 2.0 (message/send, tasks/get,
tasks/cancel) and publishes an Agent Card. Transport-agnostic: ``handle_jsonrpc`` takes and returns plain
dicts, so the in-process transport and the HTTP route use the very same code (and the in-process path
still goes through full serialisation, i.e. it is real A2A, only without a socket).

Task lifecycle: submitted -> working -> completed | failed | input-required (the same task id continues when
the caller sends a follow-up message with ``taskId``). Handler exceptions become a ``failed`` task with a
generic text (no internals, no page text, no secrets).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from friday.a2a.types import (
    DEPTH_EXCEEDED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    TERMINAL,
    AgentCard,
    Artifact,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    rpc_error,
    rpc_result,
)
from friday.core.logging import get_logger

log = get_logger(__name__)
META_KEY = "friday"  # message.metadata["friday"] = {"depth", "root_task_id", "parent_task_id", "sender"}
MAX_TASKS = 500


@dataclass
class IncomingCall:
    message: Message
    task_id: str
    context_id: str
    history: list[Message]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.message.text()

    @property
    def data(self) -> dict[str, Any]:
        return self.message.data()

    @property
    def depth(self) -> int:
        return int(self.meta.get("depth", 0) or 0)


@dataclass
class AgentReply:
    state: TaskState = TaskState.COMPLETED
    text: str = ""
    data: dict[str, Any] | None = None
    cost_inr: float = 0.0  # reported to the caller, who charges its budget


class AgentHandler(Protocol):
    async def handle(self, call: IncomingCall) -> AgentReply: ...


class A2AServer:
    def __init__(self, card: AgentCard, handler: AgentHandler, *, max_depth: int = 2, handler_timeout_s: float = 60.0) -> None:
        self.card, self.handler = card, handler
        self.max_depth, self.handler_timeout_s = max_depth, handler_timeout_s
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._cancelled: set[str] = set()

    @property
    def name(self) -> str:
        return self.card.name

    def agent_card(self) -> dict[str, Any]:
        return self.card.wire()

    # ------------------------------------------------------------------ JSON-RPC
    async def handle_jsonrpc(self, req: Any) -> dict[str, Any]:
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            return rpc_error(req.get("id") if isinstance(req, dict) else None, INVALID_REQUEST, "invalid request")
        rid, method, params = req.get("id"), req["method"], req.get("params") or {}
        if not isinstance(params, dict):
            return rpc_error(rid, INVALID_PARAMS, "params must be an object")
        try:
            if method == "message/send":
                return rpc_result(rid, (await self._send(params)).wire())
            if method == "tasks/get":
                return rpc_result(rid, self._get(params).wire())
            if method == "tasks/cancel":
                return rpc_result(rid, self._cancel(params).wire())
            return rpc_error(rid, METHOD_NOT_FOUND, f"method not found: {method[:40]}")
        except _RpcFail as e:
            return rpc_error(rid, e.code, e.message)
        except Exception:  # noqa: BLE001 - never leak internals over the wire
            log.exception("a2a server %s: internal error", self.name)
            return rpc_error(rid, INTERNAL_ERROR, "internal error")

    # ------------------------------------------------------------------ methods
    async def _send(self, params: dict[str, Any]) -> Task:
        try:
            msg = Message.model_validate(params.get("message") or {})
        except ValidationError as e:
            raise _RpcFail(INVALID_PARAMS, "invalid message") from e
        if not msg.parts:
            raise _RpcFail(INVALID_PARAMS, "message has no parts")
        meta = dict((msg.metadata or {}).get(META_KEY) or {})
        if int(meta.get("depth", 0) or 0) > self.max_depth:
            raise _RpcFail(DEPTH_EXCEEDED, f"agent hierarchy deeper than {self.max_depth}")
        msg = msg.model_copy(update={"role": "user"})

        task = self._tasks.get(msg.task_id) if msg.task_id else None
        if msg.task_id and task is None:
            raise _RpcFail(TASK_NOT_FOUND, "task not found")
        if task is not None and task.state in TERMINAL:
            raise _RpcFail(INVALID_PARAMS, "task is already finished")
        if task is None:
            task = Task(context_id=msg.context_id or "", status=TaskStatus(state=TaskState.SUBMITTED),
                        metadata={META_KEY: meta} if meta else None)
            if not task.context_id:
                task.context_id = Task(status=TaskStatus(state=TaskState.SUBMITTED)).context_id
            self._remember(task)
        task.history.append(msg.model_copy(update={"task_id": task.id, "context_id": task.context_id}))
        task.status = TaskStatus(state=TaskState.WORKING)
        call = IncomingCall(message=msg, task_id=task.id, context_id=task.context_id,
                            history=list(task.history), meta=meta)
        try:
            reply = await asyncio.wait_for(self.handler.handle(call), self.handler_timeout_s)
        except TimeoutError:
            reply = AgentReply(TaskState.FAILED, "the agent took too long")
        except Exception:  # noqa: BLE001
            log.exception("a2a agent %s failed", self.name)
            reply = AgentReply(TaskState.FAILED, "the agent could not finish")
        if task.id in self._cancelled:
            return task  # cancelled while working: keep the canceled state
        out = Message(role="agent", parts=[Part.of_text(reply.text)] if reply.text else [],
                      task_id=task.id, context_id=task.context_id)
        task.status = TaskStatus(state=reply.state, message=out if out.parts else None)
        if out.parts:
            task.history.append(out)
        if reply.data is not None:
            task.artifacts = [Artifact(name="result", parts=[Part.of_data(reply.data)])]
        if reply.cost_inr:
            task.metadata = {**(task.metadata or {}), "cost_inr": round(float(reply.cost_inr), 4)}
        return task

    def _get(self, params: dict[str, Any]) -> Task:
        task = self._tasks.get(str(params.get("id", "")))
        if task is None:
            raise _RpcFail(TASK_NOT_FOUND, "task not found")
        return task

    def _cancel(self, params: dict[str, Any]) -> Task:
        task = self._get(params)
        if task.state in TERMINAL:
            raise _RpcFail(TASK_NOT_CANCELABLE, "task is already finished")
        self._cancelled.add(task.id)
        task.status = TaskStatus(state=TaskState.CANCELED)
        return task

    def _remember(self, task: Task) -> None:
        self._tasks[task.id] = task
        while len(self._tasks) > MAX_TASKS:
            old, _ = self._tasks.popitem(last=False)
            self._cancelled.discard(old)


class _RpcFail(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message
