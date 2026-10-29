# ruff: noqa: E501
"""Gateways with the style switch off (nothing changes) and on (budget, proof card), over the Chat Lab world with fakes."""

from __future__ import annotations

import pytest

from friday.bench import rules as R
from friday.bench import scenarios as S
from friday.bench.runner import FEATURE_SWITCHES
from friday.lab.world import LabWorld
from friday.style import check, prompt

PHONE = "+919800000001"
BASE = {k: True for k in FEATURE_SWITCHES if k != "style_layer_enabled"}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for n in ("FRIDAY_MODE", "FRIDAY_PROFILE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FRIDAY_LLM_PROVIDER"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.chdir("/")
    yield
    prompt.set_enabled(False)


async def talk(tmp_path, style: bool, *messages: str) -> list[list[str]]:
    w = await LabWorld.create(notes_path=tmp_path / "n.jsonl", overrides={**BASE, "style_layer_enabled": style})
    try:
        turns = []
        for m in messages:
            turn = await w.send_inbound(PHONE, w.inbound_text(PHONE, m), m)
            turns.append([o["text"] or "" for o in turn.get("outputs") or []])
        return turns
    finally:
        await w.close()


async def test_switch_off_is_byte_for_byte_the_old_behaviour(tmp_path):
    a = await talk(tmp_path, False, "Mera gmail check krna", "atta")
    b = await talk(tmp_path, False, "Mera gmail check krna", "atta")
    assert a == b
    assert not any("Proof" in t or "Dikha" in t for turn in a for t in turn)  # no proof card with the switch off


async def test_switch_on_adds_a_proof_card_after_a_lookup_and_keeps_messages_short(tmp_path):
    (turn,) = await talk(tmp_path, True, "Zepto par 5 kg atta ka price batao")
    card = [t for t in turn if t.startswith(("Ho gaya. Proof:", "Yeh nahi ho paya.", "Koshik"))]
    assert len(card) == 1 and "Kya: " in card[0]  # failed lookup in the fake world still sends what was seen
    assert check.check(card[0], kind="proof") == []
    assert all(len(check.lines_of(t)) <= 10 for t in turn)


async def test_intent_reply_unchanged_in_content_when_on(tmp_path):
    off = await talk(tmp_path, False, "kal mera interview hai")
    on = await talk(tmp_path, True, "kal mera interview hai")
    assert off == on  # an already-short owned template is not touched


def test_bench_has_ten_style_scenarios_and_rules_are_registered():
    scs = [s for s in S.load() if s.category == "style"]
    assert len(scs) == 10
    used = {n for s in scs for n in s.rule_names}
    assert used <= set(R.RULES) and {"style_length", "style_cancel_wording", "style_proof_present", "style_headline_first"} <= used


def test_bench_style_rules_pass_and_fail_as_intended():
    ctx = R.Ctx(user_text="kal interview hai")
    ok = R.Reply(["Interview kal hai. Reminder laga dun?"])
    assert all(R.check(n, ok, ctx, a)[0] for n, a in [("style_length", "text"), ("style_one_question", None), ("style_no_headers", None), ("style_script_mirror", None)])
    long = R.Reply(["\n".join(f"line {i}" for i in range(7))])
    assert not R.check("style_length", long, ctx, "text")[0] and R.check("style_length", long, ctx, "proof")[0]
    assert not R.check("style_one_question", R.Reply(["Ok?\nI check.\nSure?"]), ctx)[0]
    assert not R.check("style_no_headers", R.Reply(["# Result\nx"]), ctx)[0]
    assert not R.check("style_headline_first", R.Reply(["1. a\n2. b\nbest is a"]), ctx)[0]
    assert R.check("style_cancel_wording", R.Reply(["Cancelled. Nothing was charged or booked."]), ctx)[0]
    assert not R.check("style_cancel_wording", R.Reply(["Cancelled."]), ctx)[0]
    assert R.check("style_proof_present", R.Reply(["Done.\nProof:\nWhat: x"]), ctx)[0]
    assert not R.check("style_proof_present", R.Reply(["Ho gaya."]), ctx)[0]
    assert not R.check("style_script_mirror", R.Reply(["सब ठीक है, मैं देखती हूँ"]), ctx)[0]
    assert not R.check("style_no_flat_refusal", R.Reply(["Main theek se samajh nahi payi."]), ctx)[0]
