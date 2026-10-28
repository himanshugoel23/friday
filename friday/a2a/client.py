# ruff: noqa: E501
"""A2A client: how a project manager delegates. Every request is budget-checked, audited (request and
response, masked) and time-boxed. A failed transport or a JSON-RPC error never raises into the caller as
a stack trace: it comes back as ``A2AClientError`` (code + short text) or, for the convenience method
``delegate``, as a synthetic ``failed`` task, so a PM can carry on with partial results.
"""

from __future__ import annotations

import asyncio
from typing import Any

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import BudgetExceeded, TaskBudget
from friday.a2a.server import META_KEY
from friday.a2a.transport import Transport, UnknownAgent
from friday.a2a.types import (
    AgentCard,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    new_id,
    rpc_request,
)
from friday.core.logging import get_logger

log = get_logger(__name__)


class A2AClientError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class A2AClient:
    def __init__(self, transport: Transport, *, name: str, depth: int = 0, audit: A2AAudit | None = None,
                 per_call_timeout_s: float = 30.0) -> None:
        self.transport, self.name, self.depth = transport, name, depth
        self.audit = audit or A2AAudit()
        self.per_call_timeout_s = per_call_timeout_s
        self._cards: dict[str, AgentCard] = {}

    # ------------------------------------------------------------------ discovery
    async def card(self, agent: str) -> AgentCard:
        if agent not in self._cards:
            self._cards[agent] = AgentCard.model_validate(await self.transport.fetch_card(agent))
        return self._cards[agent]

    async def agents_with_skill(self, skill_id: str) -> list[str]:
        out = []
        for name in self.transport.agents():
            try:
                if (await self.card(name)).has_skill(skill_id):
                    out.append(name)
            except Exception:  # noqa: BLE001 - an unreachable peer is simply not listed
                continue
        return out

    # ------------------------------------------------------------------ message/send
    async def send(self, agent: str, *, text: str = "", data: dict[str, Any] | None = None,
                   task_id: str | None = None, context_id: str | None = None, root_task_id: str | None = None,
                   parent_task_id: str | None = None, budget: TaskBudget | None = None) -> Task:
        parts = ([Part.of_text(text)] if text else []) + ([Part.of_data(data)] if data else [])
        meta = {"depth": self.depth + 1, "sender": self.name, "root_task_id": root_task_id,
                "parent_task_id": parent_task_id}
        msg = Message(role="user", parts=parts, task_id=task_id, context_id=context_id,
                      metadata={META_KEY: {k: v for k, v in meta.items() if v is not None}})
        if budget is not None:
            budget.charge_step()  # raises BudgetExceeded before anything is sent
        rid = new_id()
        self.audit.record(direction="request", sender=self.name, receiver=agent, method="message/send",
                          task_id=task_id, root_task_id=root_task_id, parent_task_id=parent_task_id,
                          depth=self.depth + 1, text=text or str(data or ""))
        timeout = self.per_call_timeout_s if budget is None else max(0.05, min(self.per_call_timeout_s, budget.remaining_s()))
        try:
            resp = await asyncio.wait_for(
                self.transport.call(agent, rpc_request("message/send", {"message": msg.wire()}, rid)), timeout
            )
        except UnknownAgent as e:
            self._fail_audit(agent, root_task_id, parent_task_id, "unknown agent")
            raise A2AClientError(-32601, "unknown agent") from e
        except TimeoutError as e:
            self._fail_audit(agent, root_task_id, parent_task_id, "timeout")
            raise A2AClientError(-32000, "agent timed out") from e
        except Exception as e:  # noqa: BLE001 - transport trouble (HTTP down, bad JSON)
            self._fail_audit(agent, root_task_id, parent_task_id, type(e).__name__)
            raise A2AClientError(-32000, "agent unreachable") from e
        if "error" in resp:
            err = resp["error"] or {}
            self._fail_audit(agent, root_task_id, parent_task_id, str(err.get("message", ""))[:80])
            raise A2AClientError(int(err.get("code", -32603)), str(err.get("message", "error"))[:120])
        task = Task.model_validate(resp.get("result") or {})
        self.audit.record(direction="response", sender=agent, receiver=self.name, method="message/send",
                          task_id=task.id, root_task_id=root_task_id, parent_task_id=parent_task_id,
                          state=task.state.value, depth=self.depth + 1,
                          text=task.status_text() or str(task.result_data() or ""))
        if budget is not None:
            budget.add_cost((task.metadata or {}).get("cost_inr", 0.0))
        return task

    def _fail_audit(self, agent: str, root: str | None, parent: str | None, why: str) -> None:
        self.audit.record(direction="response", sender=agent, receiver=self.name, method="message/send",
                          root_task_id=root, parent_task_id=parent, state="failed", depth=self.depth + 1, error=why)

    async def delegate(self, agent: str, **kw: Any) -> Task:
        """Like ``send`` but never raises on agent trouble: a failed task comes back instead.
        BudgetExceeded still propagates (the PM must stop dispatching)."""
        try:
            return await self.send(agent, **kw)
        except BudgetExceeded:
            raise
        except A2AClientError as e:
            return Task(status=TaskStatus(state=TaskState.FAILED), metadata={"error": e.message, "code": e.code})

    async def get(self, agent: str, task_id: str) -> Task:
        resp = await self.transport.call(agent, rpc_request("tasks/get", {"id": task_id}))
        if "error" in resp:
            raise A2AClientError(int(resp["error"].get("code", -32603)), str(resp["error"].get("message", "")))
        return Task.model_validate(resp["result"])

    async def cancel(self, agent: str, task_id: str) -> Task:
        resp = await self.transport.call(agent, rpc_request("tasks/cancel", {"id": task_id}))
        if "error" in resp:
            raise A2AClientError(int(resp["error"].get("code", -32603)), str(resp["error"].get("message", "")))
        return Task.model_validate(resp["result"])
