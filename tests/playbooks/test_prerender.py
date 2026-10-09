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
    # the intro (who she is calling for) is pre-rendered, whole and sentence by sentence
    intro = "Main Rahul ji ki AI assistant hoon, unke liye haircut ki appointment ke regarding call kiya hai."  # noqa: E501
    assert intro in texts
    assert "Kya kal shaam ka appointment mil sakta hai?" in texts
    assert "Sir, haircut ka estimated charge kitna hoga?" in texts  # service filled
    assert "Yeh main Rahul ji se poochh kar bataungi." in texts
    assert "Theek hai, shukriya. Main Rahul ji se poochh kar aapko batati hoon." in texts  # noqa: E501
    assert "Sorry, ek baar phir?" in texts
    # lines that need collected values (the slot) are NOT pre-rendered: synthesised live
    assert not any("book kar lijiye" in t for t in texts)
    assert not any("400 rupaye" in t for t in texts)
    # a joined "say + next question" is warmed too (it is what is actually spoken)
    assert any(t.startswith("Haan, main ek AI assistant hoon") and t.endswith("appointment mil sakta hai?") for t in texts)  # noqa: E501
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
