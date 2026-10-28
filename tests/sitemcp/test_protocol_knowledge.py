# ruff: noqa: E501
"""MCP JSON-RPC surface (in-process and stdio) and the knowledge files."""

from __future__ import annotations

import io
import json

from friday.core.config import Settings
from friday.sitemcp.fakes.dom import selector_supported
from friday.sitemcp.knowledge import SEED_DIR, all_selectors, load_knowledge, validate
from friday.sitemcp.protocol import McpServer, serve_stdio, validate_args
from friday.sitemcp.tools import TOOL_SPECS
from tests.sitemcp.harness import make_world


async def _echo(user, args):
    return {"status": "ok", "user": user, "args": args}


def _server():
    return McpServer("t", "1", {"search_products": TOOL_SPECS["search_products"]}, {"search_products": _echo})


async def test_initialize_list_call_ping_and_notification():
    s = _server()
    r = await s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    assert r["result"]["protocolVersion"] == "2024-11-05" and "tools" in r["result"]["capabilities"]
    assert (await s.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"}))["result"] == {}
    assert await s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    lst = await s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert [t["name"] for t in lst["result"]["tools"]] == ["search_products"]
    ok = await s.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_products", "arguments": {"query": "atta"}, "_meta": {"user_id": "u"}}})
    assert ok["result"]["isError"] is False and json.loads(ok["result"]["content"][0]["text"])["user"] == "u"


async def test_errors():
    s = _server()
    assert (await s.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"}))["error"]["code"] == -32601
    assert (await s.handle({"id": 1}))["error"]["code"] == -32600
    assert (await s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pay", "arguments": {}}}))["error"]["code"] == -32602
    bad = await s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_products", "arguments": {"query": ""}, "_meta": {"user_id": "u"}}})
    assert bad["result"]["isError"] is True
    nouser = await s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_products", "arguments": {"query": "a"}}})
    assert nouser["result"]["isError"] is True


async def test_stdio_transport_round_trip():
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), "not json",
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_products", "arguments": {"query": "x"}, "_meta": {"user_id": "u"}}})]
    out = io.StringIO()
    await serve_stdio(_server(), stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
    got = [json.loads(x) for x in out.getvalue().splitlines()]
    assert got[0]["id"] == 1 and got[1]["error"]["code"] == -32700 and got[2]["result"]["structuredContent"]["status"] == "ok"


async def test_in_process_and_stdio_see_the_same_tools():
    w = make_world()
    try:
        out = io.StringIO()
        await serve_stdio(w.hub._mcp["zepto"], stdin=io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"), stdout=out)
        names = [t["name"] for t in json.loads(out.getvalue())["result"]["tools"]]
        assert names == [t["name"] for t in await w.hub.list_tools("zepto")]
    finally:
        w.stop()


def test_validate_args():
    sch = TOOL_SPECS["add_to_cart"]["inputSchema"]
    assert validate_args(sch, {"id": "/p/x", "qty": 2}) == ""
    assert validate_args(sch, {"id": "/p/x", "qty": 99})
    assert validate_args(sch, {"id": "/p/x", "qty": True})
    assert validate_args(sch, {"qty": 1})
    assert validate_args(sch, {"id": "/p/x", "extra": 1})
    assert validate_args(TOOL_SPECS["set_location"]["inputSchema"], {"pincode": "0123456"})


# ------------------------------------------------------------------ knowledge
def test_real_knowledge_files_load_validate_and_are_unverified():
    kbs = load_knowledge()
    assert set(kbs) == {"zepto", "blinkit", "instamart"}
    for kb in kbs.values():
        assert kb["status"] == "unverified" and "GUESS" in kb["status_note"].upper()
        assert validate(kb) == []
        assert kb["checkout"]["proceed_verified"] is False  # never clicked until a live run says it is safe
        assert kb["safety"]["never_pay"] and kb["safety"]["no_captcha_solving"]
        assert all(selector_supported(s) for s in all_selectors(kb))
        assert kb["rate"]["min_interval_s"] >= 3


def test_every_knowledge_file_has_a_matching_shopping_site_and_domains():
    from friday.shopping.sites import load_knowledge as shop

    s = shop()
    for site, kb in load_knowledge().items():  # noqa: B007
        assert site in s and set(kb["domains"]) & set(s[site]["domains"])


def test_files_are_versioned_data():
    assert sorted(p.name for p in SEED_DIR.glob("*.json")) == ["blinkit.v1.json", "instamart.v1.json", "zepto.v1.json"]


def test_switches_default_off(monkeypatch):
    for k in ("FRIDAY_SITE_MCP_ENABLED", "FRIDAY_SITE_MCP_PROBE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.site_mcp_enabled is False and s.site_mcp_probe_enabled is False
    assert s.site_mcp_max_sessions == 2
