# ruff: noqa: E501
"""The hub: all site servers behind one in-process transport (no subprocess). Calls go through the real MCP JSON-RPC
``tools/call`` path, so the in-process and stdio transports behave identically."""

from __future__ import annotations

import itertools
from typing import Any

from friday.sitemcp.protocol import McpServer
from friday.sitemcp.runtime import SessionPool
from friday.sitemcp.site import SiteServer


class SiteMcpHub:
    def __init__(self, servers: dict[str, SiteServer], pool: SessionPool) -> None:
        self.servers, self.pool = servers, pool
        self._mcp: dict[str, McpServer] = {s: v.mcp() for s, v in servers.items()}
        self._ids = itertools.count(1)

    def sites(self) -> list[str]:
        return sorted(self.servers)

    async def list_tools(self, site: str) -> list[dict[str, Any]]:
        r = await self._mcp[site].handle({"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/list"})
        return r["result"]["tools"]  # type: ignore[index]

    async def call(self, site: str, tool: str, args: dict[str, Any] | None = None, *, user_id: str) -> dict[str, Any]:
        """-> the tool's structured result dict (always has ``status``). Never raises for site trouble."""
        if site not in self._mcp:
            return {"status": "unavailable", "reason": "unknown_site"}
        r = await self._mcp[site].handle({"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                                          "params": {"name": tool, "arguments": args or {}, "_meta": {"user_id": user_id}}})
        if r is None or "error" in r:
            return {"status": "error", "error": (r or {}).get("error", {}).get("message", "no response")}
        return r["result"]["structuredContent"]

    async def forget_user(self, user_id: str) -> int:
        """'Forget my logins' for every site."""
        return await self.pool.forget_user(user_id)

    async def aclose(self) -> None:
        await self.pool.aclose()
