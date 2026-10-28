# ruff: noqa: E501
"""Optional HTTP face of the in-process agents (``FRIDAY_A2A_HTTP_ENABLED``, default OFF).

    GET  /a2a/<agent>/.well-known/agent.json   the Agent Card
    POST /a2a/<agent>                          JSON-RPC 2.0 (message/send, tasks/get, tasks/cancel)

Needs the bearer token ``FRIDAY_A2A_HTTP_TOKEN`` (compared in constant time); with no token configured the
routes answer 403, so switching HTTP on by mistake exposes nothing. Same server objects as in-process.
"""


import hmac
from typing import Any

from friday.a2a.server import A2AServer
from friday.a2a.types import INVALID_REQUEST, PARSE_ERROR, rpc_error


def build_router(servers: dict[str, A2AServer], token: str | None) -> Any:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import JSONResponse

    router = APIRouter(prefix="/a2a", tags=["a2a"])

    def _auth(request: Request) -> None:
        got = request.headers.get("authorization", "")
        want = f"Bearer {token}" if token else None
        if not want or not hmac.compare_digest(got.encode(), want.encode()):
            raise HTTPException(status_code=403, detail="forbidden")

    def _server(name: str) -> A2AServer:
        if name not in servers:
            raise HTTPException(status_code=404, detail="unknown agent")
        return servers[name]

    @router.get("/{agent}/.well-known/agent.json")
    async def card(agent: str, request: Request) -> Any:
        _auth(request)
        return JSONResponse(_server(agent).agent_card())

    @router.post("/{agent}")
    async def rpc(agent: str, request: Request) -> Any:
        _auth(request)
        srv = _server(agent)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(rpc_error(None, PARSE_ERROR, "parse error"))
        if not isinstance(body, dict):
            return JSONResponse(rpc_error(None, INVALID_REQUEST, "invalid request"))
        return JSONResponse(await srv.handle_jsonrpc(body))

    return router
