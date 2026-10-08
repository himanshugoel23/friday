"""QA-2: the simworld has an entry for every behaviour the simulators must exercise."""

from __future__ import annotations

from friday.simworld import load_world


def test_world_is_valid_and_phones_are_unique():
    w = load_world()
    phones = [b.phone for b in w.businesses]
    assert len(phones) == len(set(phones))
    assert len({b.id for b in w.businesses}) == len(w.businesses)


def test_every_edge_case_has_a_persona():
    biz = load_world().businesses
    notes = " ".join(n for b in biz for n in b.persona.notes)
    answers = {b.persona.answer for b in biz}
    assert {"answers", "busy", "no_answer", "voicemail", "callback_later"} <= answers
    assert any(b.persona.hangs_up_after_turns for b in biz)  # hang-up
    assert any(b.persona.switches_to for b in biz)  # language switch mid-call
    assert any(b.persona.asks_if_ai for b in biz)  # "are you a robot?"
    assert any(b.persona.ivr for b in biz)  # IVR tree
    assert any(b.persona.hold_seconds >= 2400 for b in biz)  # hold timeout
    assert "sim:agent_asks_otp" in notes  # OTP demand
    assert any(b.scam for b in biz)  # scam number
    assert any(b.persona.stock and not all(b.persona.stock.values()) for b in biz)  # stock miss
    assert any(b.persona.stock and all(b.persona.stock.values()) for b in biz)  # stock hit
    assert any(b.hotel and b.persona.holds_room_hours for b in biz)  # hotel hold
    assert any(b.hours and len(b.hours) < 7 for b in biz)  # closed hours
    assert "sim:calls_back_after=1800" in notes and "sim:missed_call_after=600" in notes
    assert any(b.persona.language.value in {"mr", "kn", "ta", "hi"} for b in biz)  # regional
