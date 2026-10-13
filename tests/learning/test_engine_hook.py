"""The playbook engine logs what the business said for the review queue."""

from __future__ import annotations

import json

from tests.playbooks.test_safety import PRICE, drive, make_brief


async def test_engine_logs_each_vendor_utterance_masked(tmp_path, monkeypatch):
    log = tmp_path / "u.jsonl"
    monkeypatch.setenv("FRIDAY_LEARNING_LOG", str(log))
    monkeypatch.setenv("FRIDAY_LEARNING_SALT", "test-salt")
    await drive([*PRICE], brief=make_brief())
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows and all(r["playbook_id"] == "salon_booking" for r in rows)
    assert all("call_ref" in r and "intent" in r for r in rows)


async def test_logging_off_during_plain_tests(tmp_path, monkeypatch):
    monkeypatch.delenv("FRIDAY_LEARNING_LOG", raising=False)
    from friday.learning.log import DEFAULT_LOG

    before = DEFAULT_LOG.stat().st_mtime if DEFAULT_LOG.exists() else None
    await drive([*PRICE], brief=make_brief())
    after = DEFAULT_LOG.stat().st_mtime if DEFAULT_LOG.exists() else None
    assert before == after
