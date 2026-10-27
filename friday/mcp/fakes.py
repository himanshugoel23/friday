"""Deterministic in-memory backend for the browser tools (tests and simulation).

Rules it enforces like the real one must: a task belongs to one user; domain allow-list; secret-looking
values are refused in ``fill``; page text is returned as untrusted facts; login/approval return links and
ids only. ``fail_next`` injects a failure for the next call.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from friday.mcp.registry import CallContext, Handler, ToolError

_SECRETISH_TARGET = re.compile(r"(?i)otp|pass(word|code)?|pin|cvv|card|secret")


@dataclass
class _Task:
    user_id: str
    site: str
    url: str
    state: str = "open"
    steps: list[str] = field(default_factory=list)


class FakeBrowserBackend:
    def __init__(self, allowed_sites: set[str], pages: dict[str, list[str]] | None = None) -> None:
        self.allowed_sites = allowed_sites
        self.pages = pages or {}
        self.tasks: dict[str, _Task] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.committed: list[tuple[str, str]] = []  # (task, target): proof of what really happened
        self.fail_next = False
        self._n = itertools.count(1)

    def handlers(self) -> dict[str, Handler]:
        return {
            "browser.open_task": self.open_task, "browser.read_page": self.read_page,
            "browser.act": self.act, "browser.request_user_login": self.request_user_login,
            "browser.request_approval": self.request_approval, "browser.get_summary": self.get_summary,
        }

    def _task(self, ctx: CallContext, a: dict[str, Any]) -> _Task:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected")
        t = self.tasks.get(a["browser_task_id"])
        if t is None or t.user_id != ctx.user_id:  # same answer for "missing" and "someone else's"
            raise ToolError("forbidden", "no such task")
        return t

    async def open_task(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        if a["site"] not in self.allowed_sites:
            raise ToolError("forbidden", "site not allowed")
        tid = f"bt-{next(self._n)}"
        self.tasks[tid] = _Task(ctx.user_id, a["site"], f"https://{a['site']}/")
        return {"browser_task_id": tid, "status": "open"}

    async def read_page(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        t = self._task(ctx, a)
        facts = self.pages.get(t.url, [])[: a.get("max_items", 50)]
        return {"url": t.url, "facts": [{"text": f} for f in facts], "untrusted": True}

    async def act(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        t = self._task(ctx, a)
        if a["action"] == "goto":
            host = urlparse(a["target"]).hostname or ""
            if host != t.site and not host.endswith("." + t.site):
                raise ToolError("forbidden", "domain not allowed")
            t.url = a["target"]
        if a["action"] in ("fill", "select") and _SECRETISH_TARGET.search(a["target"]):
            raise ToolError("forbidden", "secret fields are filled by the user, not by Friday")
        t.steps.append(f"{a['action']}:{a['intent']}")
        if a["intent"] == "commit":
            self.committed.append((a["browser_task_id"], a["target"]))
        return {"ok": True, "url": t.url}

    async def request_user_login(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        t = self._task(ctx, a)
        t.state = "needs_login"
        return {"login_url": f"https://friday.invalid/login/{a['browser_task_id']}?t=one-time",
                "expires_in_s": 600}

    async def request_approval(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        t = self._task(ctx, a)
        aid = f"ap-{next(self._n)}"
        self.approvals[aid] = {"user_id": ctx.user_id, "task": a["browser_task_id"],
                               "max": a["max_total_paise"], "approved": False}
        t.state = "waiting_approval"
        return {"approval_id": aid, "status": "pending"}

    async def get_summary(self, ctx: CallContext, a: dict[str, Any]) -> dict[str, Any]:
        t = self._task(ctx, a)
        return {"summary": f"{len(t.steps)} step(s) on {t.site}", "state": t.state}

    # approval answer comes from the user's button, simulated here (never from a tool call)
    def user_approves(self, approval_id: str) -> None:
        self.approvals[approval_id]["approved"] = True


class FakeApprovals:
    """ApprovalChecker: true only for a task whose approval the (simulated) user pressed."""

    def __init__(self, backend: FakeBrowserBackend) -> None:
        self.b = backend

    def is_approved(self, user_id: str, task_id: str, tool: str, args: dict[str, Any]) -> bool:
        return any(a["approved"] and a["user_id"] == user_id and a["task"] == args.get("browser_task_id")
                   for a in self.b.approvals.values())
