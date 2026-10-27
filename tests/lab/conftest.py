"""Fixtures for the Chat Lab: the real app over TestClient, a movable token clock, no network."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from friday.core.config import Settings
from friday.lab.app import create_lab_app

RAHUL = "+919800000001"
PRIYA = "+919800000002"
SUNITA = "+919800000003"

SECRET_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-test-SECRET-VALUE-123",
    "OPENAI_API_KEY": "sk-openai-test-SECRET-VALUE-456",
    "WHATSAPP_ACCESS_TOKEN": "EAAG-test-SECRET-WHATSAPP-789",
    "SARVAM_API_KEY": "sarvam-test-SECRET-000",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FRIDAY_MODE",
        "FRIDAY_PROFILE",
        "ANTHROPIC_API_KEY",
        "FRIDAY_ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "FRIDAY_OPENAI_API_KEY",
        "FRIDAY_LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


@dataclass
class Lab:
    client: TestClient
    token: str
    world: Any
    clock: dict[str, float]
    tmp: Path
    bodies: list[str] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f"/lab/api/{self.token}{path}"

    def get(self, path: str, **params: Any):  # noqa: ANN201
        r = self.client.get(self.url(path), params=params)
        self.bodies.append(r.text)
        return r

    def post(self, path: str, **body: Any):  # noqa: ANN201
        r = self.client.post(self.url(path), json=body)
        self.bodies.append(r.text)
        return r

    def say(self, phone: str, text: str) -> dict[str, Any]:
        r = self.post("/send", phone=phone, text=text)
        assert r.status_code == 200, r.text
        return r.json()

    def tap(
        self, phone: str, title_part: str, snap: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        snap = snap or self.get("/state", phone=phone).json()
        for e in reversed(snap["entries"]):
            for b in e.get("buttons") or []:
                if title_part.lower() in b["title"].lower():
                    r = self.post("/tap", phone=phone, message_id=e["id"], button_id=b["id"])
                    assert r.status_code == 200, r.text
                    return r.json()
        raise AssertionError(f"no button containing {title_part!r}")

    @staticmethod
    def outs(snap: dict[str, Any], turn_only: bool = True) -> list[dict[str, Any]]:
        if turn_only and snap.get("turn"):
            seqs = set(snap["turn"]["output_seqs"])
            return [e for e in snap["entries"] if e["seq"] in seqs]
        return [e for e in snap["entries"] if e["dir"] == "out"]

    @staticmethod
    def text_of(snap: dict[str, Any]) -> str:
        return "\n".join((e.get("text") or "") for e in Lab.outs(snap))


@pytest.fixture
def make_lab(tmp_path: Path) -> Iterator[Any]:
    opened: list[TestClient] = []

    def make(**kw: Any) -> Lab:
        clock = {"t": 1_000_000.0}
        kw.setdefault("env", Settings(_env_file=None, mode="simulator"))
        app = create_lab_app(notes_path=tmp_path / "notes.jsonl", now=lambda: clock["t"], **kw)
        client = TestClient(app)
        client.__enter__()
        opened.append(client)
        return Lab(client, app.state.gate.token, app.state.world, clock, tmp_path)

    yield make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def lab(make_lab: Any) -> Lab:
    return make_lab()


PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ]{8,}\d(?!\w)")
