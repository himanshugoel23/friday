"""Fixed lines are pre-rendered through the TTS cache while the phone rings."""

from __future__ import annotations

from friday.core.models import Language
from friday.playbooks import dryrun
from friday.playbooks.dryrun import PersonaFile, load_personas, run_persona
from friday.playbooks.engine import PlaybookPolicy, resolve_inputs, static_utterances
from friday.playbooks.model import get_playbook

from .conftest import make_brief


def test_static_utterances_cover_the_fixed_lines(salon):
    brief = make_brief(book=True, inputs={"fallback_when": "kal shaam 5 baje"})
    texts = static_utterances(salon, resolve_inputs(salon, brief))
    assert "Hello, kya meri baat लुक्स saloon se ho rahi hai?" in texts  # the identity question
    who = "Main Friday baat kar rahi hoon, Rahul sir ki virtual assistant."
    why = "Rahul sir ko haircut karwana hai, toh unki booking ke regarding call kiya hai."
    ask = "Toh sir, ek baar bata sakte hain inke kya charges rahenge?"
    assert who in texts and why in texts and ask in texts and f"{who} {why} {ask}" in texts
    assert "Sir, haircut ke kya charges rahenge?" in texts  # asked again
    assert "Theek hai sir. Kya aaj shaam 5 baje ka slot mil sakta hai?" in texts
    assert "Achha, nahi ho sakta. Toh kya kal ka slot available rahega?" in texts
    assert "Haan ji, main Rahul sir ki personal AI assistant hoon." in texts
    assert "Main Friday hoon, Rahul sir ki virtual assistant." in texts  # the re-intro after a hold
    assert "Theek hai sir, main Rahul sir ko bata deti hoon. Thank you." in texts
    assert "Sorry, ek baar phir?" in texts
    # lines that need collected values (the slot) are NOT pre-rendered: synthesised live
    assert not any("book kar lijiye" in t or "book kar lete" in t for t in texts)
    assert not any("400 rupaye" in t for t in texts)
    assert len(texts) == len(set(texts))


def test_policy_exposes_fixed_lines_for_the_runner():
    lines = PlaybookPolicy().fixed_lines(make_brief())
    assert set(lines) == {Language.HINGLISH} and len(lines[Language.HINGLISH]) > 20
    assert PlaybookPolicy().fixed_lines(make_brief(playbook=None)) == {}


async def test_runner_prerenders_and_no_fixed_line_misses_the_cache():
    pb = get_playbook("salon_booking")
    pf = load_personas("salon_booking")
    for pid in ("quote_friendly", "book_busy_fallback_accepted"):
        persona = next(p for p in pf.personas if p.id == pid)
        r = await run_persona(pb, pf, persona)
        assert r.static_misses == 0 and r.checks["fixed_lines_prerendered"], pid


async def test_a_missing_prerender_hook_is_caught_by_the_dry_run(monkeypatch):
    monkeypatch.setattr(PlaybookPolicy, "fixed_lines", lambda self, brief: {})
    pb = get_playbook("salon_booking")
    pf: PersonaFile = load_personas("salon_booking")
    persona = next(p for p in pf.personas if p.id == "quote_friendly")
    r = await dryrun.run_persona(pb, pf, persona)
    assert r.static_misses > 0 and not r.checks["fixed_lines_prerendered"]
