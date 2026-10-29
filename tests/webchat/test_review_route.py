# ruff: noqa: E501
"""The founder's reply review page: GET /web/admin/<token>/review (+ its JSON api). 404 without the right admin token or when
no admin token is set. Approve / Edit / Reject write review events; a thumbs-down in the web chat becomes a reaction."""

from __future__ import annotations

from friday.replywriter import ReplyLog, ReplyService, TemplateWriter
from tests.replywriter.helpers import compare_input
from tests.webchat.conftest import ADMIN_TOKEN

API = f"/web/admin/{ADMIN_TOKEN}/api"


def seed(web, n: int = 2) -> tuple[ReplyLog, list[str]]:  # noqa: ANN001
    web.c.settings.reply_log_dir = str(web.tmp / "replylog")
    rl = ReplyLog.open(web.c.settings)
    inp = compare_input()
    return rl, [rl.record("tester-1", inp, TemplateWriter().write(inp)) for _ in range(n)]


def test_review_page_and_api_need_the_admin_token(web):
    ok = web.client.get(f"/web/admin/{ADMIN_TOKEN}/review")
    assert ok.status_code == 200 and "Reply review" in ok.text and f"/web/admin/{ADMIN_TOKEN}/api" in ok.text
    assert "default-src" in ok.headers["content-security-policy"] and "innerHTML" not in ok.text  # same hardening as the admin page
    for path in ("/web/admin/wrong-token-0123456789/review", "/web/admin/wrong-token-0123456789/api/review", f"/web/{web.token}/review"):
        assert web.client.get(path).status_code == 404
    assert web.client.post("/web/admin/wrong-token-0123456789/api/review/abc", json={"action": "approve"}).status_code == 404


def test_review_is_off_when_no_admin_token_is_set(web):
    web.cfg.admin_token = None
    assert web.client.get(f"/web/admin/{ADMIN_TOKEN}/review").status_code == 404
    assert web.client.get(f"{API}/review").status_code == 404


def test_list_approve_edit_reject(web):
    rl, (a, b) = seed(web)
    data = web.client.get(f"{API}/review").json()
    assert {i["id"] for i in data["items"]} == {a, b} and data["stats"]["records"] == 2 and data["enabled"] is False
    assert "user" not in data["items"][0] and "tester-1" not in str(data)  # no user reference leaves the server
    assert web.client.post(f"{API}/review/{a}", json={"action": "approve"}).json() == {"ok": True, "status": "approved"}
    r = web.client.post(f"{API}/review/{b}", json={"action": "edit", "text": "Meri pick: Rajdhani.\n\nAur jagah dekhun?"})
    assert r.json()["status"] == "edited"
    items = {i["id"]: i for i in rl.items()}
    assert items[a]["status"] == "approved" and items[b]["gold"] == ["Meri pick: Rajdhani.", "Aur jagah dekhun?"]
    assert web.client.post(f"{API}/review/{a}", json={"action": "reject"}).json()["status"] == "rejected"
    assert web.client.post(f"{API}/review/{a}", json={"action": "edit", "text": ""}).status_code == 422  # an edit needs text
    assert web.client.post(f"{API}/review/{a}", json={"action": "delete"}).status_code == 422
    assert web.client.post(f"{API}/review/nope", json={"action": "approve"}).status_code == 422


def test_a_thumbs_down_in_the_chat_becomes_a_reaction_on_the_logged_reply(web):
    rl, _ = seed(web, 0)
    pipeline = web.app.state.web.runtime.pipeline
    pipeline.reply_service = ReplyService(replylog=rl)
    web.consent()
    entries = web.say("hi")["entries"]
    reply = next(e for e in entries if e["dir"] == "out")
    inp = compare_input()
    out = TemplateWriter().write(inp).model_copy(update={"messages": [reply["text"]]})
    rid = rl.record("tester-1", inp, out)
    r = web.client.post(web.url("/feedback"), json={"message_id": reply["id"], "kind": "down", "note": "too long"})
    assert r.status_code == 200
    assert next(i for i in rl.items() if i["id"] == rid)["reactions"] == [{"kind": "down", "note": "too long"}]
