# ruff: noqa: E501
"""T06: payload fuzz for /robin/device/*: oversize, wrong content-type, extra fields, unicode, malformed JSON. Never a 500, never an
echo of the sent value, nothing stored from a rejected body. Tested with fakes."""

from __future__ import annotations

import json

import pytest

from friday.robindevice import api as device_api
from friday.robindevice.api import MAX_BODY

from .conftest import ev

B = "/robin/device"
JSON_POST = ["/heartbeat", "/signals", "/share", "/ack", "/pause", "/pair"]
CANARY = "CANARY-7f3a9c"

BAD_BODIES: list[tuple[str, bytes]] = [
    ("empty-array", b"[]"),
    ("string", b'"hello"'),
    ("number", b"12345"),
    ("null", b"null"),
    ("truncated", b'{"app_version": "1.0", '),
    ("not-json", b"\xff\xfe\x00garbage"),
    ("nul-bytes", b'{"a":"\x00\x00"}'),
    ("deep-nesting", b"[" * 5000 + b"]" * 5000),
    ("nan", b'{"os_sdk": NaN}'),
    ("huge-int", b'{"os_sdk": ' + b"9" * 400 + b"}"),
    ("bad-utf8-string", b'{"app_version": "\xed\xa0\x80"}'),
    ("canary-extra", json.dumps({CANARY: CANARY, "app_version": "1.0", "os_sdk": 34}).encode()),
]


@pytest.fixture(autouse=True)
def no_limits(monkeypatch):
    for k in list(device_api.LIMITS):
        monkeypatch.setitem(device_api.LIMITS, k, (100_000, 60))


def ok_status(code: int) -> bool:
    return code in (200, 400, 403, 404, 413, 415, 422, 503)


@pytest.mark.parametrize("path", JSON_POST)
@pytest.mark.parametrize("name,raw", BAD_BODIES, ids=[n for n, _ in BAD_BODIES])
async def test_garbage_bodies_never_500_and_never_echo(rig, path, name, raw):
    t = await rig.pair()
    r = await rig.client.post(f"{B}{path}", content=raw, headers={**rig.h(t), "content-type": "application/json"})
    assert ok_status(r.status_code), (path, name, r.status_code)
    assert CANARY not in r.text and "garbage" not in r.text


@pytest.mark.parametrize("path", ["/heartbeat", "/signals", "/share", "/ack", "/pause", "/consent"])
@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "application/xml", "multipart/form-data; boundary=x", "audio/ogg", "application/jsonp"])
async def test_wrong_content_type_is_415(rig, path, ctype):
    t = await rig.pair()
    method = "PUT" if path == "/consent" else "POST"
    r = await rig.client.request(method, f"{B}{path}", content=b'{"minutes": 5}', headers={**rig.h(t), "content-type": ctype})
    assert r.status_code == 415


async def test_json_with_charset_and_case_is_still_accepted(rig):
    t = await rig.pair()
    r = await rig.client.post(f"{B}/pause", content=b'{"minutes": 5}', headers={**rig.h(t), "content-type": "Application/JSON; charset=utf-8"})
    assert r.status_code == 200


async def test_sos_rejects_a_non_json_body_but_an_empty_body_works_in_any_type(rig):
    t = await rig.pair()
    assert (await rig.client.post(f"{B}/sos", content=b"", headers={**rig.h(t), "content-type": "text/plain"})).status_code == 200
    assert (await rig.client.post(f"{B}/sos", content=b'{"lat": 1}', headers={**rig.h(t), "content-type": "text/plain"})).status_code == 415
    assert (await rig.client.post(f"{B}/sos", content=b"[1,2]", headers={**rig.h(t), "content-type": "application/json"})).status_code == 422


@pytest.mark.parametrize("path", ["/heartbeat", "/signals", "/share", "/ack", "/pause", "/sos"])
async def test_oversize_body_is_413_declared_or_streamed(rig, path):
    t = await rig.pair()
    big = b'{"x":"' + b"a" * (MAX_BODY + 10) + b'"}'
    r = await rig.client.post(f"{B}{path}", content=big, headers={**rig.h(t), "content-type": "application/json"})
    assert r.status_code == 413

    async def stream():  # no Content-Length: chunked
        for i in range(0, len(big), 4096):
            yield big[i : i + 4096]

    r = await rig.client.post(f"{B}{path}", content=stream(), headers={**rig.h(t), "content-type": "application/json"})
    assert r.status_code == 413


async def test_oversize_body_with_a_bad_token_is_404_not_413_and_never_read(rig):
    big = b'{"x":"' + b"a" * (MAX_BODY * 4) + b'"}'
    r = await rig.client.post(f"{B}/signals", content=big, headers={"authorization": "Bearer nope", "content-type": "application/json"})
    assert r.status_code == 404


async def test_oversize_voice_is_413_and_wrong_voice_types_are_422(rig):
    t = await rig.pair()
    h = {**rig.h(t), "x-duration-s": "5"}
    big = b"\x00" * (device_api.MAX_VOICE_BYTES + 5)
    assert (await rig.client.post(f"{B}/voice", content=big, headers={**h, "content-type": "audio/ogg"})).status_code == 413
    assert (await rig.client.post(f"{B}/voice", content=b"abc", headers={**h, "content-type": "application/json"})).status_code == 422
    assert (await rig.client.post(f"{B}/voice", content=b"abc", headers={**rig.h(t), "content-type": "audio/ogg", "x-duration-s": "abc"})).status_code == 422
    assert (await rig.client.post(f"{B}/voice", content=b"abc", headers={**rig.h(t), "content-type": "audio/ogg", "x-duration-s": "9999"})).status_code == 422


@pytest.mark.parametrize("path,body", [
    ("/heartbeat", {"app_version": "1.0", "os_sdk": 34, "ts_ms": 1, "roles": {}}),
    ("/pause", {"minutes": 5}),
    ("/ack", {"prompt_id": "x", "action": "ok"}),
    ("/share", {"kind": "text", "value": "hi"}),
])
async def test_extra_fields_are_rejected_without_echo(rig, path, body):
    t = await rig.pair()
    r = await rig.client.post(f"{B}{path}", json={**body, "admin": CANARY, "parent_id": "p2"}, headers=rig.h(t))
    assert r.status_code == 422 and CANARY not in r.text and "p2" not in r.text
    assert "fields" in r.json()


async def test_extra_fields_inside_signal_events_are_rejected(rig):
    t = await rig.pair()
    e = ev("camera_in_use_start", rig.clock.ms)
    e["note"] = CANARY
    r = await rig.client.post(f"{B}/signals", json={"events": [e]}, headers=rig.h(t))
    assert r.status_code == 422 or (r.status_code == 200 and r.json().get("accepted") == 0)
    assert CANARY not in r.text
    st = rig.service.store.peek("p1")
    assert CANARY not in json.dumps([vars(x) for x in st.events], default=str)


UNICODE = ["नमस्ते", "😀" * 10, "‮‭direction", "\u0000", "å" * 50, "ｆｕｌｌｗｉｄｔｈ", "\ud83d" if False else "\U0001f9ea", "'; DROP TABLE x;--", "<script>alert(1)</script>", "../../etc/passwd", "%00%0d%0a"]


@pytest.mark.parametrize("text", UNICODE)
async def test_unicode_in_every_free_field_is_rejected_or_harmless(rig, text):
    t = await rig.pair()
    for path, body in [
        ("/heartbeat", {"app_version": text, "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}}),
        ("/share", {"kind": "text", "value": text}),
        ("/ack", {"prompt_id": text, "action": "ok"}),
        ("/signals", {"events": [{"id": text, "type": "camera_in_use_start", "ts_ms": rig.clock.ms}]}),
    ]:
        r = await rig.client.post(f"{B}{path}", json=body, headers=rig.h(t))
        assert ok_status(r.status_code), (path, text, r.status_code)
        if r.status_code == 422:
            assert text not in r.text  # never echoes the value
    assert (await rig.client.get(f"{B}/transparency", headers=rig.h(t))).status_code == 200


async def test_unicode_and_odd_auth_headers_are_404_not_500(rig):
    await rig.pair()
    for value in ["Bearer नमस्ते", "Bearer " + "A" * 100_000, "Bearer \x7f", "bearer", "Bearer ", "Bearer a b c"]:
        try:
            r = await rig.client.get(f"{B}/prompts", headers={"authorization": value})
        except Exception:  # noqa: BLE001 - the client refuses to send some header bytes: also fine
            continue
        assert r.status_code == 404


async def test_pair_code_shapes(rig):
    for code in ["", "a" * 8, "ABCDEFG", "ABCDEFGHI", "ABCDEF0H", "नमस्ते1234", "ABCD EFG", "ABCD\nEFG"]:
        r = await rig.client.post(f"{B}/pair", json={"code": code, "app_version": "1.0", "os_sdk": 34})
        assert r.status_code in (404, 422, 429), code
        assert code not in r.text or code == ""


async def test_unknown_methods_and_paths_do_not_500(rig):
    t = await rig.pair()
    for method, path in [("GET", "/pair"), ("DELETE", "/sos"), ("PATCH", "/consent"), ("GET", "/nope"), ("POST", "/prompts")]:
        r = await rig.client.request(method, f"{B}{path}", headers=rig.h(t))
        assert r.status_code in (404, 405)
