# ruff: noqa: E501
"""A whole simulated call with the human-voice layer off and on (profile production / internal-test)."""

from __future__ import annotations

import pytest

from friday.core.models import CallOutcome

from .conftest import LOOKS, ScriptedPolicy, hangup, make_brief, no_answer_user, say


@pytest.mark.parametrize("profile", ["production", "internal-test"])
async def test_simulated_call_runs_in_both_profiles(make_runner, vsettings, profile):
    on = profile == "internal-test"
    for n in ("human_numbers", "human_prosody", "human_pauses", "human_variants", "human_mood", "human_match_listener", "human_mirror", "human_backchannels", "human_noise_adapt"):
        setattr(vsettings, n, on)
    policy = ScriptedPolicy([say("Haircut ka rate 450 rupaye hai na?"), hangup(CallOutcome.PARTIAL, "Dhanyavaad.")])
    result = await make_runner(policy).run(make_brief(LOOKS), no_answer_user)
    assert result.outcome != CallOutcome.FAILED
    first = [t.text for t in result.transcript.turns if t.speaker.value == "friday"][0]
    assert "assistant" in first.lower() or "AI" in first  # the disclosure line is untouched
