# ruff: noqa: E501
"""Minimal MCP (Model Context Protocol) JSON-RPC 2.0 surface: initialize, ping, tools/list, tools/call.

The official Python MCP SDK is NOT a dependency of this repo (checked pyproject.toml and uv.lock), so this is a small
hand-written server behind a clean interface: ``McpServer.handle(message) -> response | None`` is transport free.
Transports: in-process (``hub.py``, the default; no subprocess) and stdio (``serve_stdio`` below, newline delimited
JSON as in the MCP stdio spec). HTTP is NOT implemented (a 5 line adapter around ``handle`` when needed).
The calling user is passed in ``params._meta.user_id`` (never in tool arguments).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
Handler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]  # (user_id, arguments) -> result


class McpServer:
    def __init__(self, name: str, version: str, tools: dict[str, dict[str, Any]], handlers: dict[str, Handler]) -> None:
        self.name, self.version, self.tools, self.handlers = name, version, tools, handlers

    def _err(self, id_: Any, code: int, msg: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}

    async def handle(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return self._err(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        id_, method = msg.get("id"), msg["method"]
        params = msg.get("params") or {}
        if "id" not in msg:  # notification: never answered
            return None
        if method == "initialize":
            asked = params.get("protocolVersion")
            ver = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}
        if method == "tools/list":
            tools = [{"name": n, "description": s["description"], "inputSchema": s["inputSchema"]} for n, s in self.tools.items()]
            return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}
        if method == "tools/call":
            return await self._call(id_, params)
        return self._err(id_, -32601, f"method not found: {method}")

    async def _call(self, id_: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in self.handlers:
            return self._err(id_, -32602, f"unknown tool: {name}")
        if not isinstance(args, dict):
            return self._err(id_, -32602, "arguments must be an object")
        problem = validate_args(self.tools[name]["inputSchema"], args)
        user = str((params.get("_meta") or {}).get("user_id") or "")
        if problem or not user:
            res = {"status": "error", "error": problem or "missing _meta.user_id"}
            return self._wrap(id_, res, True)
        try:
            res = await self.handlers[name](user, args)
        except Exception as e:  # noqa: BLE001 - a tool never crashes the server; type name only, no page content
            res = {"status": "error", "error": type(e).__name__}
            return self._wrap(id_, res, True)
        return self._wrap(id_, res, False)

    @staticmethod
    def _wrap(id_: Any, res: dict[str, Any], is_error: bool) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
            "structuredContent": res, "isError": is_error}}


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> str:
    """Tiny JSON-schema subset check (type, required, pattern, min/max, additionalProperties). '' when fine."""
    import re

    props = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in args:
            return f"missing argument: {k}"
    for k, v in args.items():
        if k not in props:
            return f"unknown argument: {k}"
        s = props[k]
        t = s.get("type")
        if (t == "string" and not isinstance(v, str)) or (t == "integer" and (not isinstance(v, int) or isinstance(v, bool))):
            return f"bad type for {k}"
        if isinstance(v, str):
            if len(v) < s.get("minLength", 0) or len(v) > s.get("maxLength", 10_000):
                return f"bad length for {k}"
            if "pattern" in s and not re.match(s["pattern"], v):
                return f"bad format for {k}"
        if isinstance(v, int) and not (s.get("minimum", v) <= v <= s.get("maximum", v)):
            return f"out of range: {k}"
    return ""


async def serve_stdio(server: McpServer, *, stdin: Any = None, stdout: Any = None) -> None:
    """Newline delimited JSON-RPC over stdio (stdout carries protocol messages only)."""
    import asyncio

    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, stdin.readline)
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out: dict[str, Any] | None = server._err(None, -32700, "parse error")
        else:
            out = await server.handle(msg)
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()
