# ruff: noqa: E501
"""Transports for the A2A client. In-process is the DEFAULT (no sockets, no extra process, no extra RAM);
HTTP is an option behind ``FRIDAY_A2A_HTTP_ENABLED`` for agents that live in another process or host.

Both carry the same JSON-RPC dicts, so an agent cannot tell them apart.
"""

from __future__ import annotations

from typing import Any, Protocol

from friday.a2a.server import A2AServer


class Transport(Protocol):
    def agents(self) -> list[str]: ...
    async def call(self, agent: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def fetch_card(self, agent: str) -> dict[str, Any]: ...


class UnknownAgent(Exception):
    pass


class InProcessTransport:
    def __init__(self, servers: dict[str, A2AServer] | None = None) -> None:
        self.servers: dict[str, A2AServer] = dict(servers or {})

    def register(self, name: str, server: A2AServer) -> None:
        self.servers[name] = server

    def agents(self) -> list[str]:
        return sorted(self.servers)

    def _server(self, agent: str) -> A2AServer:
        if agent not in self.servers:
            raise UnknownAgent(agent)
        return self.servers[agent]

    async def call(self, agent: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._server(agent).handle_jsonrpc(payload)

    async def fetch_card(self, agent: str) -> dict[str, Any]:
        return self._server(agent).agent_card()

    def view(self, names: list[str]) -> InProcessTransport:
        """A restricted view: an agent that gets this transport can reach ONLY these peers."""
        return InProcessTransport({n: self.servers[n] for n in names if n in self.servers})


class HttpTransport:
    """JSON-RPC over HTTP POST to ``<base>/<agent>``; card at ``<base>/<agent>/.well-known/agent.json``.
    ``client`` is an ``httpx.AsyncClient`` (tests pass one built on ``httpx.MockTransport``)."""

    def __init__(self, base_urls: dict[str, str], *, token: str | None = None, client: Any | None = None,
                 timeout_s: float = 20.0) -> None:
        self.base_urls = {k: v.rstrip("/") for k, v in base_urls.items()}
        self.token, self.timeout_s = token, timeout_s
        if client is None:
            import httpx

            client = httpx.AsyncClient(timeout=timeout_s)
        self.client = client

    def agents(self) -> list[str]:
        return sorted(self.base_urls)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _url(self, agent: str) -> str:
        if agent not in self.base_urls:
            raise UnknownAgent(agent)
        return self.base_urls[agent]

    async def call(self, agent: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self.client.post(self._url(agent), json=payload, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def fetch_card(self, agent: str) -> dict[str, Any]:
        r = await self.client.get(self._url(agent) + "/.well-known/agent.json", headers=self._headers())
        r.raise_for_status()
        return r.json()
