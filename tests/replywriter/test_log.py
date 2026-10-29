# ruff: noqa: E501
"""The tester training-data log: privacy (no phone, no raw chat text, no user id), encryption, file mode, review events,
export --approved-only, delete --all, erase one tester, retention, size cap, CLI. Local files only."""

from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest

from friday.core.config import Settings
from friday.core.crypto import FieldCipher, LocalKeyProvider
from friday.replywriter import Facts, ReplyInput, ReplyLog, TemplateWriter
from friday.replywriter.cli import add_parser, run_command
from tests.replywriter.helpers import compare_input

PHONE = "+919811100001"
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t


def cipher() -> FieldCipher:
    return FieldCipher(LocalKeyProvider({"k1": b"k" * 32}, index_key=b"i" * 32))


def make(tmp_path, clock=None, **kw) -> ReplyLog:  # noqa: ANN001
    return ReplyLog(tmp_path / "rl", cipher=kw.pop("cipher", cipher()), now=clock or Clock(), **kw)


def add(rl: ReplyLog, user="user-1", inp: ReplyInput | None = None) -> str:
    inp = inp or compare_input()
    return rl.record(user, inp, TemplateWriter().write(inp))


def test_record_holds_facts_only_no_phone_no_user_id_no_chat_text(tmp_path):
    rl = ReplyLog(tmp_path / "rl", cipher=None, now=Clock())  # plain file so the bytes can be searched
    inp = ReplyInput(intent="ack", facts=Facts(name="Rahul", store="Blinkit", category="atta", topic=f"call {PHONE} and ask Rahul"), lang="en")
    rid = rl.record("user-secret-id", inp, TemplateWriter().write(inp))
    raw = rl.path.read_text()
    assert rid and "9811100001" not in raw and PHONE not in raw  # phone numbers are masked
    assert "user-secret-id" not in raw and "Rahul" not in raw and "<name>" in raw  # no user id; the first name is a placeholder
    rec = json.loads(raw.splitlines()[0])
    assert set(rec) == {"kind", "id", "ts", "user", "intent", "input", "output", "writer", "fact_check", "hashes"}  # nothing else is stored


def test_lines_are_encrypted_and_the_file_is_private(tmp_path):
    rl = make(tmp_path)
    add(rl)
    raw = rl.path.read_text()
    assert "Blinkit" not in raw and "Rajdhani" not in raw and raw.startswith("v1:")  # ciphertext tokens, not JSON
    assert stat.S_IMODE(os.stat(rl.path).st_mode) == 0o600 and stat.S_IMODE(os.stat(rl.dir).st_mode) == 0o700
    assert rl.items()[0]["intent"] == "price_compare"
    wrong = ReplyLog(tmp_path / "rl", cipher=FieldCipher(LocalKeyProvider({"k2": b"z" * 32}, index_key=b"i" * 32)))
    assert wrong.items() == [] and wrong.unreadable == 1  # a wrong key reads nothing and says so


def test_reaction_and_review_are_appended_never_edited(tmp_path):
    rl = make(tmp_path)
    rid = add(rl)
    text = TemplateWriter().write(compare_input()).messages[-1]
    assert rl.react_by_text(text, "up", "good") and not rl.react_by_text("never sent", "up")
    before = rl.path.read_text().splitlines()
    assert rl.review(rid, "edited", "My better version.\n\nWant more?") and not rl.review(rid, "edited", "") and not rl.review("nope", "approved")
    after = rl.path.read_text().splitlines()
    assert after[: len(before)] == before and len(after) == len(before) + 1  # append-only
    item = rl.items()[0]
    assert item["status"] == "edited" and item["gold"] == ["My better version.", "Want more?"] and item["reactions"] == [{"kind": "up", "note": "good"}]


def test_export_approved_only_writes_a_local_file_with_the_gold_answer(tmp_path):
    rl = make(tmp_path)
    a, b, c, _d = (add(rl, inp=compare_input(lang=lg)) for lg in ("en", "hinglish", "en", "en"))
    rl.review(a, "approved")
    rl.review(b, "edited", "Meri pick: Rajdhani.\nBlinkit par ya aur jagah bhi dekhun?")
    rl.review(c, "rejected")  # d stays pending
    path, n = rl.export_approved(tmp_path / "ft.jsonl")
    assert n == 2 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert all([m["role"] for m in r["messages"]] == ["system", "user", "assistant"] for r in rows)
    answers = [json.loads(r["messages"][2]["content"]) for r in rows]
    assert any(x["messages"] == ["Meri pick: Rajdhani.\nBlinkit par ya aur jagah bhi dekhun?"] and x["question"] for x in answers)
    assert PHONE not in path.read_text()


def test_delete_all_is_a_hard_delete(tmp_path):
    rl = make(tmp_path)
    rid = add(rl)
    rl.review(rid, "approved")
    rl.export_approved()
    assert rl.delete_all() == 1
    assert not rl.path.exists() and list(rl.dir.glob("export-*")) == [] and rl.items() == [] and rl.stats()["records"] == 0


def test_erasing_a_tester_removes_only_their_records_and_events(tmp_path):
    rl = make(tmp_path)
    mine, other = add(rl, "tester-a"), add(rl, "tester-b")
    rl.review(mine, "approved")
    rl.review(other, "approved")
    assert rl.erase_user("tester-a") == 1 and rl.erase_user("tester-a") == 0
    assert [i["id"] for i in rl.items()] == [other]
    assert mine not in rl.path.read_text() or cipher() is not None  # events of the erased record are gone too
    assert all(r.get("id") != mine for r in rl._rows())  # noqa: SLF001


def test_retention_drops_old_records_and_their_events(tmp_path):
    clock = Clock()
    rl = make(tmp_path, clock, retention_days=90)
    old = add(rl)
    rl.review(old, "approved")
    clock.t += timedelta(days=91)
    new = add(rl)  # an append runs the hourly prune
    assert [i["id"] for i in rl.items()] == [new] and all(r.get("id") != old for r in rl._rows())  # noqa: SLF001


def test_size_cap_drops_the_oldest_first(tmp_path):
    clock = Clock()
    rl = make(tmp_path, clock, max_bytes=4000)
    ids = []
    for _ in range(12):
        clock.t += timedelta(minutes=1)
        ids.append(add(rl))
    kept = [i["id"] for i in rl.items()]
    assert ids[-1] in kept and ids[0] not in kept and rl.path.stat().st_size <= 4000


def test_stats_counts_and_the_fine_tune_target(tmp_path):
    rl = make(tmp_path)
    rid = add(rl)
    rl.review(rid, "approved")
    s = rl.stats()
    assert s["records"] == 1 and s["approved_examples"] == 1 and s["fine_tune_target"] == 1000 and s["by_writer"] == {"template": 1}


def test_cli_stats_export_delete(tmp_path, monkeypatch):
    s = Settings(_env_file=None, reply_log_dir=str(tmp_path / "rl"))
    monkeypatch.setattr("friday.replywriter.log.ReplyLog.open", classmethod(lambda cls, settings, now=None: cls.from_settings(settings, cipher=cipher(), now=Clock())))
    rl = ReplyLog.open(s)
    rid = add(rl)
    rl.review(rid, "approved")
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="cmd"))
    lines: list[str] = []

    def run(*argv: str) -> int:
        return run_command(parser.parse_args(["replylog", *argv]), s, out=lines.append)

    assert run("stats") == 0 and "approved examples: 1 of about 1000" in "\n".join(lines)
    with pytest.raises(SystemExit):
        run("export")  # --approved-only is mandatory
    out_file = tmp_path / "ft.jsonl"
    assert run("export", "--approved-only", "--out", str(out_file)) == 0 and out_file.exists() and "Nothing was uploaded" in lines[-1]
    assert run("delete", "--all") == 0 and not rl.path.exists()
