# ruff: noqa: E501
"""Web channel tests: the real create_app + pipeline over fakes (scripted brain, stub STT/geocoder). No network."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from friday.api.app import create_app
from friday.webchat.config import WebConfig
from friday.webchat.registry import Registry
from tests.api.conftest import *  # noqa: F403 - brings the `wired`, `brain`, `settings` fixtures

FOUNDER = "+919811100001"
WIFE = "+919811100002"
OUTSIDER = "+919811100099"
ADMIN_TOKEN = "admin-token-for-tests-0123"


@dataclass
class Web:
    client: TestClient
    c: Any
    app: Any
    registry: Registry
    cfg: WebConfig
    token: str
    tester: Any
    tmp: Path

    def url(self, path: str, token: str | None = None) -> str:
        return f"/web/{token or self.token}/api{path}"

    def consent(self) -> None:
        assert self.client.post(self.url("/consent")).status_code == 200

    def say(self, text: str) -> dict[str, Any]:
        r = self.client.post(self.url("/send"), json={"phone": "me", "text": text})
        assert r.status_code == 200, r.text
        return r.json()


def make_web(wired, tmp_path, monkeypatch, **cfg_kw: Any) -> Web:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    s = wired.settings
    s.profile = "pilot"
    s.invite_only = False  # named testers are admitted by their personal link (docs/WEB_CHANNEL.md)
    s.pilot_allowed_numbers = [FOUNDER]
    s.chatbot_testers = [WIFE]
    s.pause_file = str(tmp_path / "paused.flag")
    cfg = WebConfig(
        _env_file=None, channel_enabled=True, dir=str(tmp_path / "web"), admin_token=ADMIN_TOKEN,
        reply_wait_s=3.0, **cfg_kw,
    )
    app = create_app(wired, background=False, fast_pin_hash=True, web_config=cfg)
    registry = Registry(cfg.path, wired.clock.now)
    tester, token = registry.invite(
        "Founder", FOUNDER, allowed={FOUNDER, WIFE}, now=wired.clock.now()
    )
    client = TestClient(app)
    client.__enter__()
    return Web(client, wired, app, registry, cfg, token, tester, tmp_path)


@pytest.fixture
def web(wired, tmp_path, monkeypatch):
    w = make_web(wired, tmp_path, monkeypatch)
    try:
        yield w
    finally:
        w.client.__exit__(None, None, None)
