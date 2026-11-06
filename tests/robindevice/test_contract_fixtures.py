"""Shared contract fixtures for the device API (``tests/robindevice/contract/*.json``).

The SAME files are read by the Kotlin tests in ``android/robin-app`` (ApiClient builds exactly these requests and
parses exactly these replies). Here we prove the fixtures are what the real server accepts and returns, so the
two sides cannot drift apart: change a schema or a reply and one of the two test suites fails.

Fixture format::

    {"name", "note", "setup": ["prompt" | "bad_token" | "no_voice_consent"],
     "request":  {"method", "path", "auth", "json"? | "body_ascii"?, "headers"?},
     "response": {"status", "json"},
     "open": ["counters", ...]   # dotted paths whose KEYS may vary (only their value types are not compared)
    }

Literal placeholders: the pairing code ``K7M2QX9A`` and the prompt id ``Rz4s3EUoCPqh`` are swapped for live values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from friday.robindevice.ports import CONSENT_ITEMS
from friday.robindevice.schemas import (
    AckIn,
    ConsentIn,
    HeartbeatIn,
    LocationIn,
    PairIn,
    PauseIn,
    ShareIn,
    SignalBatchIn,
    validate_event,
)

from .conftest import ev

DIR = Path(__file__).parent / "contract"
FIXTURES = sorted(DIR.glob("*.json"))
CODE = "K7M2QX9A"
PROMPT_ID = "Rz4s3EUoCPqh"
BODY_MODELS = {
    ("POST", "/robin/device/pair"): PairIn,
    ("POST", "/robin/device/heartbeat"): HeartbeatIn,
    ("POST", "/robin/device/signals"): SignalBatchIn,
    ("POST", "/robin/device/share"): ShareIn,
    ("POST", "/robin/device/ack"): AckIn,
    ("POST", "/robin/device/pause"): PauseIn,
    ("PUT", "/robin/device/consent"): ConsentIn,
}
INVALID_ON_PURPOSE = {"err_invalid"}  # the request body is wrong on purpose (server answers 422)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ids() -> list[str]:
    return [p.stem for p in FIXTURES]


def test_fixtures_exist_and_cover_every_route():
    assert len(FIXTURES) >= 20
    paths = {(_load(p)["request"]["method"], _load(p)["request"]["path"]) for p in FIXTURES}
    for m, route in [
        ("POST", "pair"), ("POST", "heartbeat"), ("POST", "signals"), ("GET", "prompts"), ("POST", "ack"),
        ("POST", "sos"), ("POST", "voice"), ("POST", "share"), ("GET", "consent"), ("PUT", "consent"),
        ("POST", "pause"), ("POST", "stop"), ("POST", "resume"), ("GET", "transparency"), ("DELETE", "erase"),
    ]:
        assert (m, f"/robin/device/{route}") in paths, f"no fixture for {m} {route}"


def test_fixtures_contain_no_secret_looking_values():
    for p in FIXTURES:
        text = p.read_text(encoding="utf-8")
        assert "EXAMPLE" in text or "rbn_" not in text  # the only token-like value is an obvious example
        assert "sk-" not in text and "BEGIN" not in text


@pytest.mark.parametrize("path", FIXTURES, ids=_ids())
def test_fixture_request_matches_strict_schema(path: Path):
    doc = _load(path)
    req = doc["request"]
    model = BODY_MODELS.get((req["method"], req["path"]))
    body = req.get("json")
    if model is None or body is None:
        return
    if doc["name"] in INVALID_ON_PURPOSE:
        with pytest.raises(ValueError):
            model.model_validate(body)
        return
    model.model_validate_json(json.dumps(body))
    if doc["name"] == "signals":  # the batch holds raw events; validate them one by one
        valid, invalid = validate_event(body["events"][0]), validate_event(body["events"][1])
        assert valid[1] is None and invalid[1] == "unknown_type"
    if req["path"].endswith("/sos") and body:
        LocationIn.model_validate(body)


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int | float):
        return "number"
    return type(v).__name__


def _shape(live: Any, fix: Any, open_paths: set[str], at: str = "") -> list[str]:
    """Differences between the live reply and the fixture (keys and value kinds, not values)."""
    if fix is None:
        return []  # null in the fixture = any value (optional field)
    if _kind(live) != _kind(fix):
        return [f"{at or '/'}: live {_kind(live)} vs fixture {_kind(fix)}"]
    if isinstance(fix, dict):
        if at in open_paths:
            return []
        diffs: list[str] = []
        for k in sorted(set(live) | set(fix)):
            if k not in live:
                diffs.append(f"{at}.{k}: in fixture, missing in live reply")
            elif k not in fix:
                diffs.append(f"{at}.{k}: in live reply, missing in fixture")
            else:
                diffs += _shape(live[k], fix[k], open_paths, f"{at}.{k}".lstrip("."))
        return diffs
    if isinstance(fix, list):
        if live and fix:
            return _shape(live[0], fix[0], open_paths, f"{at}[]")
        return []
    return []


@pytest.mark.parametrize("path", FIXTURES, ids=_ids())
async def test_live_server_matches_fixture(rig, path: Path):
    doc = _load(path)
    req, resp, setup = doc["request"], doc["response"], set(doc["setup"])
    token = ""
    live_pid = PROMPT_ID
    code = CODE
    if req["auth"]:
        token = await rig.pair(language="hinglish", shadow_days=0, grant="no_voice_consent" not in setup)
        if "prompt" in setup:
            r = await rig.client.post(
                "/robin/device/signals", headers=rig.h(token),
                json={"events": [ev("remote_access_app_opened", rig.clock.ms, app="anydesk")]},
            )
            assert r.json()["accepted"] == 1
            live_pid = (await rig.client.get("/robin/device/prompts", headers=rig.h(token))).json()["prompts"][0]["prompt_id"]
        if "bad_token" in setup:
            token = "rbn_this_is_not_a_paired_token"
    elif doc["name"] == "pair":
        rig.parents.add("p1", "hinglish")
        code = await rig.service.create_pairing_code("p1")
    headers = dict(req.get("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    kwargs: dict[str, Any] = {}
    if "json" in req:
        kwargs["content"] = json.dumps(req["json"]).replace(CODE, code).replace(PROMPT_ID, live_pid).encode()
        headers["Content-Type"] = "application/json"
    elif "body_ascii" in req:
        kwargs["content"] = req["body_ascii"].encode()
    r = await rig.client.request(req["method"], req["path"], headers=headers, **kwargs)
    assert r.status_code == resp["status"], r.text
    diffs = _shape(r.json(), resp["json"], set(doc["open"]))
    assert diffs == [], diffs
    if doc["name"] == "pair":
        assert r.json()["device_token"].startswith("rbn_")
        assert r.json()["consent_items"] == list(CONSENT_ITEMS)
        assert resp["json"]["consent_items"] == list(CONSENT_ITEMS)
