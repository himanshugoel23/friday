"""Speculative understanding: hit, miss, cancel, one call per turn, no state change early."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from friday.core.models import AudioClass, Speaker
from friday.latency.speculative import Speculator, normalise_utterance, same_utterance
from friday.playbooks.engine import PlaybookPolicy
from friday.playbooks.understand import Understanding, heuristic
from tests.playbooks.conftest import START, drive, make_brief

# the rules are NOT confident about these (a model call would be made)
UNSURE = "haan toh phir"
UNSURE_2 = "haan toh phir kal dekhte hain"


# --------------------------------------------------------------------------- the Speculator
async def _slow(value: str, delay: float = 0.05, log: list[str] | None = None) -> str:
    if log is not None:
        log.append("start")
    await asyncio.sleep(delay)
    return value


def test_same_utterance_ignores_case_punctuation_spacing_but_not_digits():
    assert same_utterance("Haan ji, bataiye.", "haan  ji bataiye")
    assert same_utterance("हाँ जी।", "हाँ जी")
    assert not same_utterance("400 rupaye", "500 rupaye")
    assert not same_utterance("", "")
    assert normalise_utterance("A_b!") == "a b"


async def test_hit_when_the_final_text_is_the_same_reuses_one_call():
    calls: list[str] = []
    sp: Speculator[str] = Speculator()
    assert sp.start(("S1", "q"), "Haan ji bataiye", lambda: _slow("R", log=calls))
    got, how = await sp.take(("S1", "q"), "haan ji bataiye.")
    assert (got, how) == ("R", "hit")
    assert calls == ["start"]  # exactly one model call
    assert sp.stats.hits == 1 and sp.stats.hit_rate == 1.0 and sp.stats.saved_ms


async def test_miss_when_the_text_changed_and_the_guess_is_cancelled():
    started, finished = [], []

    async def work() -> str:
        started.append(1)
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            finished.append("cancelled")
            raise
        return "late"

    sp: Speculator[str] = Speculator()
    assert sp.start(("S1", "q"), "haan ji", work)
    await asyncio.sleep(0)
    got, how = await sp.take(("S1", "q"), "haan ji bataiye")
    await asyncio.sleep(0)
    assert (got, how) == (None, "miss")
    assert finished == ["cancelled"] and sp.stats.misses == 1


async def test_a_different_number_is_a_miss():
    sp: Speculator[str] = Speculator()
    sp.start(("S3", "q"), "400 rupaye", lambda: _slow("old"))
    assert (await sp.take(("S3", "q"), "500 rupaye"))[1] == "miss"


async def test_a_different_step_or_question_is_a_miss():
    sp: Speculator[str] = Speculator()
    sp.start(("S2", "q"), "haan", lambda: _slow("old"))
    assert (await sp.take(("S3", "q"), "haan"))[1] == "miss"


async def test_cancel_when_the_caller_keeps_talking():
    sp: Speculator[str] = Speculator()
    sp.start(("S1", "q"), "haan ji", lambda: _slow("R", delay=5))
    assert sp.cancel("caller kept talking") is True
    assert sp.current is None and sp.stats.cancelled == 1
    assert await sp.take(("S1", "q"), "haan ji") == (None, "none")


async def test_one_speculative_call_per_turn_then_a_new_turn_may_guess_again():
    calls: list[str] = []
    sp: Speculator[str] = Speculator()
    assert sp.start(("S1", "q"), "haan", lambda: _slow("a", log=calls))
    await asyncio.sleep(0)
    assert not sp.start(("S1", "q"), "haan ji bataiye", lambda: _slow("b", log=calls))
    assert sp.stats.skipped_cap == 1
    sp.cancel("x")  # a cancelled guess still spends the turn's call
    assert not sp.start(("S1", "q"), "haan ji", lambda: _slow("c", log=calls))
    await sp.take(("S1", "q"), "haan ji")  # the commit ends the turn
    assert sp.start(("S1", "q2"), "nahi", lambda: _slow("d", log=calls))
    await sp.take(("S1", "q2"), "nahi")
    assert calls == ["start", "start"]


async def test_the_same_text_again_does_not_start_a_second_call():
    calls: list[str] = []
    sp: Speculator[str] = Speculator()
    assert sp.start(("S1", "q"), "haan ji", lambda: _slow("a", log=calls))
    assert not sp.start(("S1", "q"), "Haan ji.", lambda: _slow("a", log=calls))
    assert calls == [] or calls == ["start"]
    assert sp.stats.started == 1


async def test_a_failed_guess_falls_back_instead_of_raising():
    async def boom() -> str:
        raise RuntimeError("model down")

    sp: Speculator[str] = Speculator()
    sp.start(("S1", "q"), "haan ji", boom)
    assert await sp.take(("S1", "q"), "haan ji") == (None, "failed")
    assert sp.stats.failed == 1


async def test_empty_text_never_starts():
    sp: Speculator[str] = Speculator()
    assert not sp.start(("S1", "q"), "  ", lambda: _slow("x"))


# --------------------------------------------------------------------------- the playbook policy
class CountingUnderstander:
    """Stands in for the model: counts calls, answers after a delay."""

    def __init__(self, delay: float = 0.02, intent: str = "YES") -> None:
        self.calls: list[str] = []
        self.delay = delay
        self.intent = intent
        self.llm_calls = 0

    async def understand(self, *, reply: str, **kw: Any) -> Understanding:
        self.calls.append(reply)
        self.llm_calls += 1
        await asyncio.sleep(self.delay)
        return Understanding(intent=self.intent, confident=True)


async def _waiting(policy: PlaybookPolicy):
    """A call that is waiting for the salon's next reply (the script has just asked a question)."""
    brief = make_brief()
    run = await drive(["Haan boliye"], brief=brief, policy=policy)
    assert run.state is not None and not run.state.finished
    return brief, run


def _commit(run, text: str) -> None:
    run.transcript.add(Speaker.CALLEE, text, at=START + timedelta(minutes=1),
                       audio_class=AudioClass.HUMAN)


def _state_view(st) -> dict[str, Any]:
    keep = {f.name for f in dataclasses.fields(st)} - {"speculator", "transcript"}
    return {k: repr(getattr(st, k)) for k in sorted(keep)}


def _policy(und: CountingUnderstander, **kw: Any) -> PlaybookPolicy:
    return PlaybookPolicy(understander=und, llm_mode="auto", speculative=True, **kw)


async def test_policy_hit_same_text_one_model_call_and_same_answer():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    assert run.policy.speculate(brief, run.transcript, UNSURE) is True
    await asyncio.sleep(0.05)  # the pause runs out; the guess finishes meanwhile
    _commit(run, "Haan toh phir.")  # the committed words: same text
    spec_action = await run.policy.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE]  # reused: the model was asked exactly once
    assert run.policy.stats["speculative_hit"] == 1

    # the answer is exactly what the normal (non-speculative) path gives
    und2 = CountingUnderstander()
    brief2, run2 = await _waiting(PlaybookPolicy(understander=und2, llm_mode="auto"))
    _commit(run2, "Haan toh phir.")
    plain = await run2.policy.next_call_action(brief2, run2.transcript, [])
    assert und2.calls == ["Haan toh phir."]
    assert (spec_action.type, spec_action.text) == (plain.type, plain.text)


async def test_policy_miss_text_changed_runs_again_on_the_final_text():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    assert run.policy.speculate(brief, run.transcript, UNSURE)
    await asyncio.sleep(0.05)
    _commit(run, UNSURE_2)  # the caller said more than the early transcript had
    await run.policy.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE, UNSURE_2]  # the guess is ignored; a fresh call is made
    assert run.policy.stats["speculative_miss"] == 1


async def test_policy_cancel_on_continued_speech_and_on_barge_in():
    und = CountingUnderstander(delay=5)
    brief, run = await _waiting(_policy(und))
    assert run.policy.speculate(brief, run.transcript, UNSURE)
    await asyncio.sleep(0)
    assert run.policy.cancel_speculation(run.transcript, "caller kept talking") is True
    sp = run.state.speculator
    assert sp.current is None and sp.stats.cancelled == 1
    # barge-in cancels the same way and a second cancel is a harmless no-op
    assert run.policy.cancel_speculation(run.transcript, "barge-in") is False
    und.delay = 0.0
    _commit(run, UNSURE)
    await run.policy.next_call_action(brief, run.transcript, [])
    assert und.calls == [UNSURE, UNSURE]  # the cancelled guess did not answer; a fresh call did


async def test_policy_one_speculative_call_per_turn():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    assert run.policy.speculate(brief, run.transcript, UNSURE) is True
    assert run.policy.speculate(brief, run.transcript, UNSURE_2) is False
    await asyncio.sleep(0.05)
    assert und.calls == [UNSURE]


async def test_policy_skips_when_the_rules_are_already_confident():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    assert heuristic("haan ji bataiye").confident
    assert run.policy.speculate(brief, run.transcript, "haan ji bataiye") is False
    await asyncio.sleep(0.05)
    assert und.calls == []


async def test_policy_no_state_change_before_the_commit():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    before = _state_view(run.state)
    turns_before = len(run.transcript.turns)
    assert run.policy.speculate(brief, run.transcript, UNSURE)
    await asyncio.sleep(0.1)  # the speculative understanding has finished
    assert _state_view(run.state) == before  # nothing moved, nothing learned, nothing counted
    assert len(run.transcript.turns) == turns_before
    assert run.state.llm_calls == 0 and run.state.intents == run.state.intents[:]


async def test_policy_switch_off_never_speculates():
    und = CountingUnderstander()
    pol = PlaybookPolicy(understander=und, llm_mode="auto")  # speculative defaults to False
    brief, run = await _waiting(pol)
    assert pol.speculative is False
    assert pol.speculate(brief, run.transcript, UNSURE) is False
    await asyncio.sleep(0.05)
    assert und.calls == [] and run.state.speculator is None


async def test_policy_never_speculates_on_a_stop_request_or_with_llm_never():
    und = CountingUnderstander()
    brief, run = await _waiting(_policy(und))
    assert run.policy.speculate(brief, run.transcript, "dobara call mat karna") is False
    pol = PlaybookPolicy(understander=und, llm_mode="never", speculative=True)
    brief2, run2 = await _waiting(pol)
    assert pol.speculate(brief2, run2.transcript, UNSURE) is False


async def test_policy_ignores_a_call_it_has_not_started():
    und = CountingUnderstander()
    pol = _policy(und)
    brief = make_brief()
    from friday.core.models import Transcript

    assert pol.speculate(brief, Transcript(), UNSURE) is False


@pytest.mark.parametrize("text", ["", "   "])
async def test_policy_empty_text_never_speculates(text):
    brief, run = await _waiting(_policy(CountingUnderstander()))
    assert run.policy.speculate(brief, run.transcript, text) is False
