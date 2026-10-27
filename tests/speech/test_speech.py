"""Speech Understander: rules floor, grounding, model path, failure fallbacks, shadow mode."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from friday.speech import SpeechUnderstander
from friday.speech.ground import violations
from friday.speech.rules import clean_basic
from friday.speech.schema import wire_schema


class ScriptedLLM:
    def __init__(self, reply=None, *, delay=0.0, boom=False):
        self.reply, self.delay, self.boom, self.seen = reply, delay, boom, []

    async def complete(self, **kw):
        self.seen.append(kw)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.boom:
            raise RuntimeError("down")
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return SimpleNamespace(text=text)


def settings(**kw):
    base = dict(
        speech_understanding="on",
        speech_understanding_voice_notes=True,
        speech_understanding_calls=True,
        speech_understanding_text=False,
        speech_understanding_model=None,
        speech_understanding_timeout_s=1.0,
        speech_understanding_min_words=3,
        resolve_llm=lambda: "real",
        model_for=lambda p: "small-model",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def reply(text, repairs=(), unintelligible=False):
    return {"corrected_text": text, "repairs": list(repairs), "unintelligible": unintelligible}


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- rules floor
def test_rules_remove_fillers_and_stutter():
    out, repairs = clean_basic("umm mujhe mujhe ek haircut chahiye hmm")
    assert out == "mujhe ek haircut chahiye"
    assert repairs


def test_rules_self_correction_day_and_number():
    assert clean_basic("kal nahi parso aana hai")[0] == "parso aana hai"
    assert clean_basic("5 nahi 6 baje aana")[0] == "6 baje aana"


def test_rules_leave_clean_text_alone():
    text = "kal shaam 5 baje salon mein slot chahiye"
    assert clean_basic(text) == (text, [])


# ---------------------------------------------------------------- grounding
def test_grounding_rejects_invented_number_and_day():
    assert violations("haircut book karo kal", "haircut book karo kal 500 rupees") != []
    assert violations("haircut book karo", "haircut book karo parso") != []


def test_grounding_allows_correction_of_existing_number():
    assert violations("5 nahi 6 baje aana hai", "6 baje aana hai") == []


def test_grounding_rejects_invented_name_but_allows_memory_name():
    assert violations("salon mein slot chahiye", "Shreya salon mein slot chahiye") != []
    assert violations("shriya salon mein slot", "Shreya salon mein slot", {"shreya"}) == []


def test_grounding_rejects_devanagari():
    assert violations("kal salon jana hai", "कल salon जाना है") != []


# ---------------------------------------------------------------- model path
def test_model_fix_applied_silently():
    llm = ScriptedLLM(reply("Shreya salon mein kal 5 baje slot chahiye", [
        {"old": "Shriya sallon", "new": "Shreya salon", "kind": "mishearing"}]))
    u = SpeechUnderstander(llm, settings())
    from friday.speech.memory import MemoryView

    mv = MemoryView(places=["Shreya salon"], vocab={"shreya", "salon"})
    r = run(u.understand("umm Shriya sallon mein kal 5 baje slot chahiye", memory=mv))
    assert r.source == "llm" and r.apply and r.text == "Shreya salon mein kal 5 baje slot chahiye"
    assert r.original_text.startswith("umm Shriya")
    assert llm.seen[0]["purpose"] == "speech_understand"
    assert llm.seen[0]["json_schema"] == wire_schema()


def test_ungrounded_model_answer_falls_back_to_rules():
    llm = ScriptedLLM(reply("hmm haircut kal 9 baje 500 rupees"))
    r = run(SpeechUnderstander(llm, settings()).understand("umm haircut book karo kal"))
    assert r.source == "rules" and r.text == "haircut book karo kal"
    assert r.reason.startswith("ungrounded")


@pytest.mark.parametrize("llm", [ScriptedLLM(boom=True), ScriptedLLM("not json"),
                                 ScriptedLLM(reply("x"), delay=0.5)])
def test_failures_never_raise_and_keep_text(llm):
    u = SpeechUnderstander(llm, settings(speech_understanding_timeout_s=0.1))
    r = run(u.understand("mujhe ek haircut book karna hai"))
    assert r.text == "mujhe ek haircut book karna hai" and r.source in {"raw", "rules"}


def test_deadline_override_is_respected():
    u = SpeechUnderstander(ScriptedLLM(reply("a b c"), delay=0.5), settings())
    r = run(u.understand("mujhe ek haircut book karna hai", deadline_s=0.05))
    assert r.reason == "timeout"


def test_short_secret_and_off_are_skipped():
    llm = ScriptedLLM(reply("x y z"))
    u = SpeechUnderstander(llm, settings())
    assert run(u.understand("haan")).reason == "short"
    assert run(u.understand("mera otp hai 482913 bhej do")).reason == "secret_context"
    assert not llm.seen
    off = SpeechUnderstander(llm, settings(speech_understanding="off"))
    assert run(off.understand("mujhe ek haircut book karna hai")).reason == "off"
    assert not llm.seen


def test_text_channel_off_by_default_and_calls_on():
    u = SpeechUnderstander(ScriptedLLM(reply("a")), settings())
    assert u.wants("voice_note") and u.wants("call") and not u.wants("text")


def test_shadow_mode_computes_but_does_not_apply():
    llm = ScriptedLLM(reply("haircut book karo"))
    r = run(SpeechUnderstander(llm, settings(speech_understanding="shadow"))
            .understand("umm haircut book karo"))
    assert r.changed and not r.apply


def test_fake_llm_only_uses_floor():
    llm = ScriptedLLM(reply("x"))
    u = SpeechUnderstander(llm, settings(resolve_llm=lambda: "fake"))
    r = run(u.understand("umm haircut book karo"))
    assert r.source == "rules" and not llm.seen


def test_audit_has_counts_not_text():
    r = run(SpeechUnderstander(ScriptedLLM(reply("haircut book karo")), settings())
            .understand("umm haircut book karo"))
    assert "haircut" not in json.dumps(r.audit())
