"""FastAPI app via TestClient: boots without keys; webhook + /sim endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from friday.api.app import create_app
from friday.channels.whatsapp import sign
from friday.core.config import Settings
from friday.core.container import Container
from tests.api.conftest import ADMIN


@pytest.fixture
def client(wired):
    voice = APIRouter()

    @voice.get("/ping")
    async def ping() -> dict[str, str]:
        return {"voice": "ok"}

    wired.override("voice_router", voice)
    app = create_app(wired, background=False, fast_pin_hash=True)
    with TestClient(app) as c:
        yield c


def test_health_and_voice_mount(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}  # SECURITY-28
    assert client.get("/voice/ping").json() == {"voice": "ok"}


def test_whatsapp_verify(client):
    ok = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "friday-dev-verify",
            "hub.challenge": "42",
        },
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403


def _wa_payload(text: str, phone: str = ADMIN.lstrip("+"), mid: str = "wamid.1") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": mid,
                                    "timestamp": "1767600000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_whatsapp_webhook_signature_and_dispatch(wired, client):
    from pydantic import SecretStr

    wired.settings.whatsapp_app_secret = SecretStr("appsecret")
    body = json.dumps(_wa_payload("hi")).encode()
    r = client.post(
        "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=bad"}
    )
    assert r.status_code == 401
    r = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={
            "X-Hub-Signature-256": sign(body, "appsecret"),
            "content-type": "application/json",
        },
    )
    assert r.status_code == 200 and r.json() == {"messages": 1, "statuses": 0}
    # processed (background task ran) -> admin got the first onboarding question
    assert wired.messaging.render(wired.messaging.last_to(ADMIN)) == "ask name"
    # provider retry is de-duplicated
    client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body, "appsecret")},
    )
    assert len(wired.messaging.messages_to(ADMIN)) == 1


def test_sim_endpoints(client):
    r = client.post("/sim/messages", json={"phone": ADMIN, "text": "hello"})
    assert r.status_code == 200
    assert [m["rendered"] for m in r.json()["replies"]] == ["ask name"]
    r = client.post("/sim/messages", json={"phone": ADMIN, "text": "Rahul"})
    assert r.json()["replies"][0]["text"] == "city?"
    inbox = client.get(f"/sim/messages/{ADMIN}").json()["messages"]
    assert len(inbox) == 2
    assert len(client.get("/sim/outbox").json()["messages"]) == 2
    call = client.post(
        "/sim/calls/inbound", json={"from_phone": "+919811000000", "answered": False}
    )
    assert call.json()["status"] == "unmatched"
    assert "AI assistant" in call.json()["greeting"]


def test_app_boots_with_no_keys_default_container(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/f.db", anthropic_api_key=None
    )
    app = create_app(Container(settings), background=False)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
