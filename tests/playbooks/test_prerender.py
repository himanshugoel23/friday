"""Fixed lines are pre-rendered through the TTS cache while the phone rings."""

from __future__ import annotations

from friday.core.models import Language
from friday.playbooks import dryrun
from friday.playbooks.dryrun import PersonaFile, load_personas, run_persona
from friday.playbooks.engine import PlaybookPolicy, resolve_inputs, static_utterances
from friday.playbooks.model import get_playbook

from .conftest import make_brief


def test_static_utterances_cover_the_fixed_lines(salon):
    brief = make_brief()
    texts = static_utterances(salon, resolve_inputs(salon, brief))
    assert "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat Looks Salon se ho rahi hai?" in texts  # disclosure  # noqa: E501
    # the second line (who she is calling for) is pre-rendered too, whole and sentence by sentence
    s1 = "Main Rahul ji ki assistant hoon, unki appointment ke regarding call kiya hai. Kya abhi do minute baat ho sakti hai?"  # noqa: E501
    assert s1 in texts and "Kya abhi do minute baat ho sakti hai?" in texts
    assert "Rahul ji ke liye haircut chahiye, kal shaam. Slot milega?" in texts
    assert "Haircut ka kitna lagega, aur kitna time?" in texts  # service filled, capital H
    assert "Yeh main Rahul ji se poochh kar bataungi." in texts
    assert "Sorry, ek baar phir?" in texts
    # lines that need collected values (price, slot) are NOT pre-rendered: synthesised live
    assert not any("400 rupaye" in t for t in texts)
    assert not any(t.startswith("Matlab") for t in texts)
    # a joined "say + next question" is warmed too (it is what is actually spoken)
    assert any(t.startswith("Haan, main AI hoon") and t.endswith("Slot milega?") for t in texts)
    assert len(texts) == len(set(texts))


def test_policy_exposes_fixed_lines_for_the_runner():
    lines = PlaybookPolicy().fixed_lines(make_brief())
    assert set(lines) == {Language.HINGLISH} and len(lines[Language.HINGLISH]) > 20
    assert PlaybookPolicy().fixed_lines(make_brief(playbook=None)) == {}


async def test_runner_prerenders_and_no_fixed_line_misses_the_cache():
    pb = get_playbook("salon_booking")
    pf = load_personas("salon_booking")
    persona = next(p for p in pf.personas if p.id == "friendly_free_slot")
    r = await run_persona(pb, pf, persona)
    assert r.static_misses == 0 and r.checks["fixed_lines_prerendered"]


async def test_a_missing_prerender_hook_is_caught_by_the_dry_run(monkeypatch):
    monkeypatch.setattr(PlaybookPolicy, "fixed_lines", lambda self, brief: {})
    pb = get_playbook("salon_booking")
    pf: PersonaFile = load_personas("salon_booking")
    persona = next(p for p in pf.personas if p.id == "friendly_free_slot")
    r = await dryrun.run_persona(pb, pf, persona)
    assert r.static_misses > 0 and not r.checks["fixed_lines_prerendered"]
