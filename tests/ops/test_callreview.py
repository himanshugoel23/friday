"""Call review of founder test calls (docs/CALL_REVIEW.md): fakes only, no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from friday.api.opsstatus import ops_status_router
from friday.db.tables import CallRow, CallTurnRow, TaskRow, UserRow
from friday.ops import callreview

TESTER = "+919811112233"
VENDOR = "+918044556677"
TOKEN = "t" * 20
T0 = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


async def _call(db, cid, to, turns, *, collected=None, minutes=0):
    async with db.session() as s:
        if await s.get(UserRow, "user1") is None:
            s.add(UserRow(id="user1", phone=TESTER, phone_hmac="h" * 64))
            await s.flush()
            s.add(TaskRow(id="task1", requester_user_id="user1", type="call", spec={}))
            await s.flush()
        s.add(CallRow(
            id=cid, task_id="task1", provider="sarvam", to_phone=to, dial_status="answered",
            outcome="completed", collected=collected or {}, languages_heard=["hi"], hold_seconds=2,
            started_at=T0 + timedelta(minutes=minutes), answered_at=T0 + timedelta(minutes=minutes),
            ended_at=T0 + timedelta(minutes=minutes, seconds=42),
        ))
        await s.flush()
        for i, (sp, tx, conf) in enumerate(turns):
            s.add(CallTurnRow(call_id=cid, seq=i, speaker=sp, text=tx, confidence=conf, at=T0))


@pytest.fixture
def cfg(settings):
    settings.pilot_allowed_numbers = [TESTER]
    return settings


async def test_render_masks_filters_and_shows_metrics(db, cfg):
    await _call(db, "aaaaaaaa1111", TESTER, [("friday", "Namaste", None), ("callee", "haan boliye", 0.8)])
    await _call(db, "bbbbbbbb2222", VENDOR, [("callee", "SECRET-VENDOR-TALK", 0.9)], minutes=1)
    await _call(db, "cccccccc3333", TESTER, [("callee", "FLAGGED-TALK", None)], collected={"real_vendor": True}, minutes=2)
    out = await callreview.render_review(db, cfg, 5)
    assert "aaaaaaaa" in out and "friday: Namaste" in out and "callee: haan boliye [conf 0.80]" in out
    assert "to ********33" in out and TESTER not in out and "9811112233" not in out
    assert "asr_conf_avg=0.80" in out and "hold_s=2" in out and "42s" in out
    assert "SECRET-VENDOR-TALK" not in out and "bbbbbbbb" not in out  # not allow-listed
    assert "FLAGGED-TALK" not in out  # flagged real vendor / third party


async def test_redaction_and_n_limit(db, cfg):
    await _call(db, "dddddddd4444", TESTER, [("callee", "otp 482913 mail me a.b@x.co key sk-abcdefghij12345 ok 12345678", None)])
    for i in range(3):
        await _call(db, f"eeeeeeee{i}000", TESTER, [("callee", "hi", None)], minutes=i + 1)
    out = await callreview.render_review(db, cfg, 2)
    assert out.count("=== call") == 2
    full = await callreview.render_review(db, cfg, 99)
    assert full.count("=== call") == 4 and callreview.clamp_n(99) == 20 and callreview.clamp_n(None) == 5
    for bad in ("482913", "a.b@x.co", "sk-abcdefghij12345", "12345678"):
        assert bad not in full
    assert "[digits]" in full and "[email]" in full and "[secret]" in full


async def test_cipher_round_trip_text_is_encrypted_at_rest(db, cfg):
    from friday.core.crypto import FieldCipher, LocalKeyProvider, get_field_cipher, set_field_cipher

    try:
        get_field_cipher()
        installed = True
    except Exception:  # noqa: BLE001
        installed = False
    if not installed:
        set_field_cipher(FieldCipher(LocalKeyProvider("test-secret")))
    try:
        await _call(db, "ffffffff5555", TESTER, [("callee", "plain words here", None)])
        async with db.session() as s:
            raw = (await s.execute(text("select text from call_turns"))).scalar_one()
        assert "plain words here" not in str(raw)
        assert "plain words here" in await callreview.render_review(db, cfg, 5)
    finally:
        if not installed:
            set_field_cipher(None)


async def test_size_cap(db, cfg):
    await _call(db, "gggggggg6666", TESTER, [("callee", "word " * 400, None)])
    await _call(db, "hhhhhhhh7777", TESTER, [("callee", "word " * 400, None)], minutes=1)
    out = await callreview.render_review(db, cfg, 5, max_bytes=2500)
    assert len(out.encode()) < 2500 + 100 and "truncated" in out


async def test_empty(db, cfg):
    assert "no test calls" in await callreview.render_review(db, cfg, 5)


def _client(container) -> TestClient:
    app = FastAPI()
    app.include_router(ops_status_router(), prefix="/ops-status")
    app.state.container = container
    return TestClient(app)


async def test_route_auth_and_switch(container, monkeypatch):
    container.settings.pilot_allowed_numbers = [TESTER]
    await _call(container.db, "iiiiiiii8888", TESTER, [("friday", "Namaste", None)])
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", TOKEN)
    monkeypatch.delenv("FRIDAY_OPS_CALL_REVIEW_ENABLED", raising=False)
    monkeypatch.chdir("/")  # no .env to pick up
    c = _client(container)
    assert c.get(f"/ops-status/{TOKEN}/calls").status_code == 404  # switch off
    monkeypatch.setenv("FRIDAY_OPS_CALL_REVIEW_ENABLED", "true")
    assert c.get(f"/ops-status/{'x' * 20}/calls").status_code == 404  # wrong token
    r = c.get(f"/ops-status/{TOKEN}/calls?n=3")
    assert r.status_code == 200 and "friday: Namaste" in r.text
    monkeypatch.delenv("FRIDAY_OPS_STATUS_TOKEN")
    assert c.get(f"/ops-status/{TOKEN}/calls").status_code == 404


def test_cli_off_without_switch(monkeypatch, cfg):
    monkeypatch.delenv("FRIDAY_OPS_CALL_REVIEW_ENABLED", raising=False)
    monkeypatch.chdir("/")
    lines: list[str] = []
    assert callreview.cli_review(cfg, 5, out=lines.append) == 2
    assert "off" in lines[0]


def test_cli_parser_wired():
    import argparse

    from friday import cli

    src = open(cli.__file__).read()
    assert '"calls"' in src and "cli_review" in src
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)


async def test_pilot_redirect_makes_vendor_numbered_calls_reviewable(db, cfg):
    # In the pilot the guard rings the tester's own phone whatever business was 'called', so the
    # stored destination is the business's number but the speaker was the tester.
    await _call(db, "eeeeeeee5555", VENDOR, [("callee", "haan ji bataiye", 0.9)])
    assert "eeeeeeee" not in await callreview.render_review(db, cfg, 5)  # no redirect: hidden
    cfg.vendor_call_redirect_to = TESTER
    out = await callreview.render_review(db, cfg, 5)
    assert "eeeeeeee" in out and "haan ji bataiye" in out and VENDOR not in out
