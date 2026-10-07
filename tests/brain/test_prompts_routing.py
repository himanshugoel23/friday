"""AI-2 persona/prompts (snapshots), cost rules: routing, caching, budgets, fast paths."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from friday.brain.llm import AnthropicLLM, system_blocks
from friday.brain.prompts import CACHE_BREAK, PERSONA, system_prompt
from friday.brain.routing import HAIKU, OPUS, SONNET, ModelRouter
from friday.core.config import Settings
from friday.core.container import FACTORIES, Container
from friday.core.interfaces import Brain, DocumentExtractor, LLMMessage
from friday.core.models import Language, MessageKind, Tone

from .conftest import make_ctx, msg

SNAP = Path(__file__).parent / "snapshots"
PURPOSES = ["interpret", "resolve_references", "call_turn", "summarize", "compare",
            "judge_nudge", "extract", "translate", "shortlist_reasons"]


@pytest.mark.parametrize("purpose", PURPOSES)
def test_prompt_snapshots(purpose):
    text = system_prompt(purpose, tone=Tone.FRIENDLY, language=Language.HINGLISH)
    path = SNAP / f"{purpose}.txt"
    if os.environ.get("FRIDAY_UPDATE_SNAPSHOTS") or not path.exists():
        SNAP.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"prompt changed: {purpose}"


def test_persona_rules():
    p = PERSONA.lower()
    assert "female" in p and "karti hoon" in p and "never claim or imply being human" in p
    for rule in ("otp", "never pay", "budget alone is not delegation", "private notes",
                 "no fillers", "medical"):
        assert rule in p, rule


def test_tone_and_language_change_prompt():
    a = system_prompt("interpret", tone=Tone.FORMAL, language=Language.EN)
    b = system_prompt("interpret", tone=Tone.PLAYFUL, language=Language.HI)
    assert a != b and "formal" in a.lower() and "Devanagari" in b


@pytest.mark.parametrize("purpose", ["call_turn", "interpret", "extract", "summarize"])
def test_prompts_mark_untrusted_input(purpose):
    text = system_prompt(purpose).lower()
    assert "untrusted" in text and "instruction" in text


async def test_tone_switch_changes_fake_output(brain):
    formal = await brain.interpret(make_ctx(language=Language.EN, tone=Tone.FORMAL),
                                   msg("Book a haircut at Looks Salon tomorrow 6pm"))
    playful = await brain.interpret(make_ctx(language=Language.EN, tone=Tone.PLAYFUL),
                                    msg("Book a haircut at Looks Salon tomorrow 6pm"))
    assert formal.reply != playful.reply


# ------------------------------------------------------------------ routing & budgets


def test_router_defaults_never_opus(brain_settings, monkeypatch):
    r = ModelRouter(brain_settings)
    assert r.model_for("call_turn") == SONNET
    for p in ("interpret", "extract", "judge_nudge", "summarize", "compare",
              "shortlist_reasons", "translate"):
        assert r.model_for(p) == HAIKU
    assert r.model_for("interpret", escalate=True) == OPUS
    monkeypatch.setenv("FRIDAY_LLM_MODEL_CALL_TURN", HAIKU)
    assert ModelRouter(brain_settings).model_for("call_turn") == HAIKU


def test_task_budget_downgrades(brain_settings):
    r = ModelRouter(brain_settings, task_token_budget=100)
    r.record("t1", 150)
    assert r.over_budget("t1") and r.model_for("call_turn", task_id="t1") == HAIKU
    assert r.model_for("call_turn", task_id="t2") == SONNET


async def test_interpret_routes_haiku_and_caches_stable_context(brain, fake_llm, family_ctx):
    await brain.interpret(family_ctx, msg("book a doctor for papa tomorrow morning"))
    call = fake_llm.calls_for("interpret")[-1]
    assert call.model == HAIKU and CACHE_BREAK in call.system
    stable = call.system.split(CACHE_BREAK)[1]
    assert "Suresh Verma" in stable and "papa tomorrow" not in stable  # message is volatile
    assert "papa tomorrow" in call.messages[0].content


@pytest.mark.parametrize("text,kw", [
    ("help", {}), ("status?", {}), ("delete everything", {}), ("be formal", {}),
    (None, {"button_id": "a:t1:yes", "kind": MessageKind.BUTTON_REPLY}),
    ("thanks!", {}), ("my OTP is 123456 save it", {}),
])
async def test_deterministic_inputs_skip_the_llm(brain, fake_llm, ctx, text, kw):
    await brain.interpret(ctx, msg(text, **kw))
    assert not fake_llm.calls_for("interpret")


async def test_unknown_long_message_escalates_once(brain, fake_llm, ctx):
    await brain.interpret(ctx, msg("the thing from yesterday about that other matter we "
                                   "discussed is still pending somehow"))
    models = [c.model for c in fake_llm.calls_for("interpret")]
    assert models == [HAIKU, OPUS]


def test_system_blocks_mark_cache_breakpoints():
    blocks = system_blocks(f"static rules{CACHE_BREAK}<data>brief</data>")
    assert [b["text"] for b in blocks] == ["static rules", "<data>brief</data>"]
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)


async def test_anthropic_logs_cache_usage(caplog):
    from types import SimpleNamespace

    from .test_llm import _StubClient

    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")],
                           stop_reason="end_turn", model=HAIKU,
                           usage=SimpleNamespace(input_tokens=50, output_tokens=10,
                                                 cache_read_input_tokens=2000,
                                                 cache_creation_input_tokens=0))
    llm = AnthropicLLM(api_key="k", client=_StubClient(resp))
    with caplog.at_level("INFO", logger="friday.brain.llm"):
        r = await llm.complete(system=f"a{CACHE_BREAK}b", purpose="interpret", model=HAIKU,
                               messages=[LLMMessage(role="user", content="x")])
    assert "cache_read=2000" in caplog.text and "purpose=interpret" in caplog.text
    assert llm.usage["interpret"].cache_read_tokens == 2000 and r.input_tokens == 2050


# ------------------------------------------------------------------ container / factories


def test_all_brain_factories_resolve(brain_settings):
    c = Container(brain_settings)
    brain_components = [k for k, v in FACTORIES.items()
                        if any(p.startswith("friday.brain.") for p in v.values())]
    assert set(brain_components) == {"llm", "brain", "document_extractor"}
    for comp in brain_components:
        for path in FACTORIES[comp].values():
            mod, _, attr = path.partition(":")
            assert callable(getattr(__import__(mod, fromlist=[attr]), attr))
        assert c.is_available(comp)
    assert isinstance(c.brain, Brain)
    assert isinstance(c.document_extractor, DocumentExtractor)


def test_real_llm_selected_with_key():
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    c = Container(s)
    assert c.provider_for("llm") == "anthropic" and isinstance(c.llm, AnthropicLLM)
