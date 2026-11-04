"""Conversation-pattern analyzer: invented multilingual dialogues, incremental scoring, privacy."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from friday.core.interfaces import LLMResponse
from friday.robindevice.callpattern import TIERS, CallPatternAnalyzer

DATA = yaml.safe_load((Path(__file__).parent / "call_dialogues.yaml").read_text(encoding="utf-8"))["dialogues"]


def _run(d: dict) -> CallPatternAnalyzer:
    ctx = {k: True for k in d.get("context", [])}
    a = CallPatternAnalyzer(context=ctx)
    for i, line in enumerate(d["turns"]):
        who, text = line.split(": ", 1)
        a.turn({"c": "caller", "p": "parent"}[who], text, float(i * 15))
    return a


def test_fixture_count():
    assert len(DATA) >= 40
    assert len({d["id"] for d in DATA}) == len(DATA)


@pytest.mark.parametrize("d", DATA, ids=[d["id"] for d in DATA])
def test_dialogue(d):
    a = _run(d)
    rank = TIERS.index(a.state.tier)
    cues = [c.id for c in a.state.cues]
    if "min" in d:
        assert rank >= TIERS.index(d["min"]), (a.state.score, cues)
    if "max" in d:
        assert rank <= TIERS.index(d["max"]), (a.state.score, cues)


def test_incremental_score_never_drops_and_rises():
    d = next(x for x in DATA if x["id"] == "en_digital_arrest_cbi")
    a = CallPatternAnalyzer(context={"unknown_number": True, "first_contact": True})
    scores = []
    for line in d["turns"]:
        who, text = line.split(": ", 1)
        scores.append(a.turn({"c": "caller", "p": "parent"}[who], text).score)
    assert scores == sorted(scores) and scores[-1] > scores[0]


def test_no_raw_text_kept_by_default():
    a = CallPatternAnalyzer()
    a.turn("caller", "I am from the CBI, your account has an arrest warrant against you")
    assert a.kept == []
    out = a.finish(1)
    assert "CBI" not in str(out) and out["cues"]
    assert len(a._recent) == 0


def test_retention_keeps_text_only_when_configured():
    a = CallPatternAnalyzer(retain_days=1)
    a.turn("caller", "hello there")
    assert len(a.kept) == 1


def test_bad_speaker_rejected():
    with pytest.raises(ValueError):
        CallPatternAnalyzer().turn("robot", "x")


class _LLM:
    def __init__(self, text):
        self.text = text

    async def complete(self, **kw):
        return LLMResponse(text=self.text, model="fake")


async def test_llm_may_raise_one_step_never_lower():
    a = CallPatternAnalyzer()
    await a.turn_with_llm("caller", "Please come to the shop tomorrow", 0, _LLM('{"tier": "HIGH"}'))
    st = await a.turn_with_llm("caller", "bring some money for the order", 5, _LLM('{"tier": "HIGH"}'))
    assert TIERS.index(st.tier) <= TIERS.index(st.rule_tier) + 1
    b = CallPatternAnalyzer()
    for t in ("I am from the CBI, you have an arrest warrant", "stay on the line, do not tell anyone"):
        st = await b.turn_with_llm("caller", t, 0, _LLM('{"tier": "NONE"}'))
    assert st.tier == st.rule_tier == "HIGH"
    st2 = await b.turn_with_llm("caller", "ok", 9, _LLM("not json"))
    assert st2.tier == "HIGH"
