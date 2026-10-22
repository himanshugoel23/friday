"""ToolRegistry: schema check, kill switch, default-OFF, per-user scope, approval for irreversible calls,
audit for every outcome. Handlers never see the audit or the policy; they only do the work."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from friday.mcp.audit import AuditLog
from friday.mcp.schema import Level, ToolDef, validate

Handler = Callable[["CallContext", dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolError(Exception):
    """Refused or failed. ``code`` is one of: unknown_tool, disabled, killed, invalid, forbidden,
    needs_approval, error. The message never carries argument values."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class ApprovalChecker(Protocol):
    def is_approved(self, user_id: str, task_id: str, tool: str, args: dict[str, Any]) -> bool: ...


@dataclass(frozen=True)
class CallContext:
    user_id: str
    task_id: str
    approval_id: str | None = None  # set by the approval flow, never by the model


class DenyAllApprovals:
    def is_approved(self, user_id: str, task_id: str, tool: str, args: dict[str, Any]) -> bool:
        return False


class ToolRegistry:
    def __init__(self, audit: AuditLog | None = None, approvals: ApprovalChecker | None = None,
                 enabled_users: set[str] | None = None) -> None:
        self.audit = audit or AuditLog()
        self.approvals: ApprovalChecker = approvals or DenyAllApprovals()
        self.enabled_users: set[str] = set(enabled_users or ())  # default OFF: nobody
        self._tools: dict[str, tuple[ToolDef, Handler]] = {}
        self._killed: set[str] = set()
        self._kill_all = False

    # -- setup
    def register(self, tool: ToolDef, handler: Handler) -> None:
        self._tools[tool.name] = (tool, handler)

    def enable_user(self, user_id: str) -> None:
        self.enabled_users.add(user_id)

    def disable_user(self, user_id: str) -> None:
        self.enabled_users.discard(user_id)

    def kill(self, name: str | None = None) -> None:
        if name is None:
            self._kill_all = True
        else:
            self._killed.add(name)

    def revive(self, name: str | None = None) -> None:
        if name is None:
            self._kill_all = False
        else:
            self._killed.discard(name)

    # -- discovery
    def catalogue(self, user_id: str) -> list[dict[str, Any]]:
        """What an agent may see: nothing for users that are not enabled, nothing when killed."""
        if self._kill_all or user_id not in self.enabled_users:
            return []
        return [t.to_mcp() for n, (t, _) in self._tools.items() if n not in self._killed]

    # -- call
    async def call(self, ctx: CallContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            self._log(ctx, name, "?", "deny", "unknown tool", args, "not_run")
            raise ToolError("unknown_tool")
        tool, handler = entry
        lvl = tool.level.value

        def refuse(code: str, decision: str, why: str) -> ToolError:
            self._log(ctx, tool.versioned, lvl, decision, why, args, "not_run")
            return ToolError(code, why)

        if self._kill_all or name in self._killed:
            raise refuse("killed", "killed", "kill switch is on")
        if ctx.user_id not in self.enabled_users:
            raise refuse("disabled", "deny", "private browser is off for this user")
        problems = validate(args, tool.input)
        if problems:
            raise refuse("invalid", "invalid", "; ".join(problems[:3]))
        if tool.level is Level.irreversible and not self.approvals.is_approved(
                ctx.user_id, ctx.task_id, name, args):
            raise refuse("needs_approval", "ask", "irreversible step needs the user's approval")
        try:
            result = await handler(ctx, args)
        except ToolError:
            self._log(ctx, tool.versioned, lvl, "allow", "handler refused", args, "error")
            raise
        except Exception as e:  # noqa: BLE001 - never leak page text or values in the error
            self._log(ctx, tool.versioned, lvl, "allow", type(e).__name__, args, "error")
            raise ToolError("error", type(e).__name__) from None
        out_problems = validate(result, tool.output)
        if out_problems:
            self._log(ctx, tool.versioned, lvl, "allow", "bad output shape", args, "error")
            raise ToolError("error", "bad output shape")
        self._log(ctx, tool.versioned, lvl, "allow", "ok", args, "ok")
        return result

    def _log(self, ctx: CallContext, tool: str, level: str, decision: str, reason: str,
             args: dict[str, Any], status: str) -> None:
        self.audit.record(user_id=ctx.user_id, task_id=ctx.task_id, tool=tool, level=level,
                          decision=decision, reason=reason, args=args, result_status=status)
