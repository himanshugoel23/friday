# ruff: noqa: E501
"""A2A interface: round trip, task states, card, depth, budget, audit masking, HTTP transport. Fakes only."""

from __future__ import annotations

import httpx
import pytest

from friday.a2a import (
    A2AAudit,
    A2AClient,
    A2AClientError,
    A2AServer,
    AgentCard,
    AgentReply,
    BudgetExceeded,
    HttpTransport,
    IncomingCall,
    InProcessTransport,
    Skill,
    TaskBudget,
    TaskState,
)
from friday.a2a.audit import mask_text
from friday.a2a.http import build_router
from friday.a2a.types import rpc_request


class Echo:
    async def handle(self, call: IncomingCall) -> AgentReply:
        if call.text == "boom":
            raise RuntimeError("secret internals")
        if call.text == "need":
            return AgentReply(TaskState.INPUT_REQUIRED, "which area?")
        if len(call.history) > 1 and call.text == "sonipat":
            return AgentReply(TaskState.COMPLETED, "ok", {"area": "sonipat"}, cost_inr=0.5)
        return AgentReply(TaskState.COMPLETED, f"echo {call.text}", {"n": 1}, cost_inr=1.0)


def card(name="echo") -> AgentCard:
    return AgentCard(name=name, description="d", url=f"inproc://{name}", skills=[Skill(id="echo", name="Echo", description="e")])


def world(name="echo"):
    srv = A2AServer(card(name), Echo())
    tr = InProcessTransport({name: srv})
    return srv, tr, A2AClient(tr, name="pm", audit=A2AAudit())


async def test_card_published_with_camel_case_and_skills():
    srv, tr, cl = world()
    wire = srv.agent_card()
    assert wire["protocolVersion"] and wire["skills"][0]["id"] == "echo" and "defaultInputModes" in wire
    assert wire["capabilities"]["streaming"] is False
    assert (await cl.card("echo")).has_skill("echo")
    assert await cl.agents_with_skill("echo") == ["echo"]


async def test_message_send_round_trip_and_states():
    srv, tr, cl = world()
    b = TaskBudget()
    t = await cl.send("echo", text="hi", budget=b, root_task_id="r1")
    assert t.state == TaskState.COMPLETED and t.status_text() == "echo hi" and t.result_data() == {"n": 1}
    assert [m.role for m in t.history] == ["user", "agent"]
    assert b.steps == 1 and b.cost_inr == 1.0
    got = await cl.get("echo", t.id)  # tasks/get
    assert got.id == t.id and got.state == TaskState.COMPLETED


async def test_input_required_then_continue_same_task_id():
    _, _, cl = world()
    t = await cl.send("echo", text="need")
    assert t.state == TaskState.INPUT_REQUIRED and t.status_text() == "which area?"
    t2 = await cl.send("echo", text="sonipat", task_id=t.id)
    assert t2.id == t.id and t2.state == TaskState.COMPLETED and t2.result_data() == {"area": "sonipat"}
    with pytest.raises(A2AClientError):  # a finished task cannot be continued
        await cl.send("echo", text="again", task_id=t.id)


async def test_handler_exception_is_a_failed_task_without_internals():
    _, _, cl = world()
    t = await cl.send("echo", text="boom")
    assert t.state == TaskState.FAILED and "secret" not in t.status_text()


async def test_cancel_and_errors():
    srv, tr, cl = world()
    t = await cl.send("echo", text="need")
    c = await cl.cancel("echo", t.id)
    assert c.state == TaskState.CANCELED
    with pytest.raises(A2AClientError):
        await cl.cancel("echo", t.id)
    r = await srv.handle_jsonrpc(rpc_request("nope", {}))
    assert r["error"]["code"] == -32601
    r = await srv.handle_jsonrpc({"hello": 1})
    assert r["error"]["code"] == -32600
    r = await srv.handle_jsonrpc(rpc_request("tasks/get", {"id": "missing"}))
    assert r["error"]["code"] == -32001
    with pytest.raises(A2AClientError):
        await cl.send("ghost", text="x")


async def test_depth_limit_rejects_third_level():
    srv, tr, _ = world()
    deep = A2AClient(tr, name="x", depth=2)  # would send depth 3
    with pytest.raises(A2AClientError) as e:
        await deep.send("echo", text="hi")
    assert e.value.code == -32010


async def test_budget_steps_blocks_before_sending():
    srv, tr, cl = world()
    b = TaskBudget(max_steps=1)
    await cl.send("echo", text="a", budget=b)
    with pytest.raises(BudgetExceeded) as e:
        await cl.send("echo", text="b", budget=b)
    assert e.value.reason == "steps" and len(cl.audit.records) == 2  # the blocked one was never sent


async def test_budget_cost_and_seconds():
    _, _, cl = world()
    b = TaskBudget(max_cost_inr=1.0)
    await cl.send("echo", text="a", budget=b)  # costs 1.0 -> used up
    with pytest.raises(BudgetExceeded) as e:
        await cl.send("echo", text="b", budget=b)
    assert e.value.reason == "cost"
    t = [0.0]
    b2 = TaskBudget(max_seconds=5, clock=lambda: t[0])
    t[0] = 6.0
    with pytest.raises(BudgetExceeded) as e2:
        b2.charge_step()
    assert e2.value.reason == "seconds"


async def test_audit_masks_phones_and_secrets_and_links_tasks():
    _, _, cl = world()
    await cl.send("echo", text="call +91 98765 43210 and my OTP is 482913", root_task_id="root1", parent_task_id="p1")
    recs = cl.audit.for_root("root1")
    assert len(recs) == 2 and {r["dir"] for r in recs} == {"request", "response"}
    blob = str(recs)
    assert "98765" not in blob and "482913" not in blob and "10" in blob
    assert mask_text("mail me a@b.com").endswith("[email]")


async def test_http_transport_round_trip_and_auth():
    from fastapi import FastAPI

    srv = A2AServer(card(), Echo())
    app = FastAPI()
    app.include_router(build_router({"echo": srv}, token="tok"))
    asgi = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=asgi, base_url="http://t") as http:
        tr = HttpTransport({"echo": "http://t/a2a/echo"}, token="tok", client=http)
        cl = A2AClient(tr, name="pm")
        assert (await cl.card("echo")).has_skill("echo")
        t = await cl.send("echo", text="over http")
        assert t.state == TaskState.COMPLETED and t.status_text() == "echo over http"
        bad = A2AClient(HttpTransport({"echo": "http://t/a2a/echo"}, token="wrong", client=http), name="pm")
        t2 = await bad.delegate("echo", text="x")
        assert t2.state == TaskState.FAILED  # 403 -> unreachable -> failed task, no crash
    app2 = FastAPI()
    app2.include_router(build_router({"echo": srv}, token=None))  # no token configured -> closed
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as http2:
        assert (await http2.get("/a2a/echo/.well-known/agent.json")).status_code == 403
