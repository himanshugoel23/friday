# ruff: noqa: E501
"""The deterministic latency simulator: virtual clock, before / after reply gaps."""

from __future__ import annotations

import asyncio
import time

import pytest

from friday.latency.simulator import (
    FREEFORM_REPLIES,
    ScriptedCase,
    Timing,
    default_scripted_cases,
    run_benchmark,
    run_virtual,
    timeline_ms,
)
from friday.playbooks.classifier import load_active


def test_virtual_time_jumps_instead_of_waiting():
    async def main() -> float:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.gather(asyncio.sleep(10), asyncio.sleep(3), asyncio.sleep(25))
        return loop.time() - t0

    real0 = time.perf_counter()
    assert run_virtual(main()) == 25.0
    assert time.perf_counter() - real0 < 1.0  # 25 virtual seconds, a blink of real time


@pytest.fixture(scope="module")
def default_report():
    return run_benchmark()


def test_the_benchmark_is_deterministic(default_report):
    a, b = default_report, run_benchmark()
    assert a.format() == b.format()
    assert [r.baseline.gap_ms for r in a.scripted] == [r.baseline.gap_ms for r in b.scripted]


def _rows(rep, mode):
    return {r.case.name: r for r in rep.scripted_by_mode[mode]}


def test_speculation_never_makes_a_turn_slower_and_never_adds_more_than_one_call(default_report):
    rep = default_report
    for mode, rows in rep.scripted_by_mode.items():
        for r in rows:
            assert r.speculative.gap_ms <= r.baseline.gap_ms + 1e-6, (mode, r.case.name)
            assert r.both.gap_ms <= r.classifier.gap_ms + 1e-6
            assert r.speculative.model_calls <= r.baseline.model_calls + 1


def test_streaming_stt_partials_give_the_speculation_room_to_save_time(default_report):
    rep = default_report
    rows = _rows(rep, "stream")
    hit = rows["rules unsure, early text = final"]
    long = rows["rules unsure, long answer"]
    assert hit.speculative.path == "speculative_hit" and hit.baseline.gap_ms - hit.speculative.gap_ms > 0
    assert long.speculative.path == "speculative_hit" and long.baseline.gap_ms - long.speculative.gap_ms >= 300
    # rules-sure turns have nothing to speculate on
    sure = rows["rules sure (haan ji bataiye)"]
    assert sure.speculative.gap_ms == sure.baseline.gap_ms and sure.speculative.model_calls == 0


def test_a_text_change_costs_a_wasted_call_and_saves_nothing(default_report):
    rep = default_report
    drift = _rows(rep, "stream")["text drifted (guess wasted)"]
    assert drift.speculative.path == "speculative_miss"
    assert drift.speculative.gap_ms == drift.baseline.gap_ms
    assert drift.speculative.model_calls == drift.baseline.model_calls + 1
    cont = _rows(rep, "stream")["caller kept talking (cancelled)"]
    assert cont.speculative.path == "speculative_cancelled" and cont.speculative.gap_ms == cont.baseline.gap_ms
    assert rep.extra_model_calls_per_100("stream") > 0


def test_rest_speech_to_text_leaves_little_room_and_a_faster_stt_opens_it():
    slow = run_benchmark(Timing(stt_ms=500), modes=("rest",))
    # early REST text (340 + 500 ms) arrives after the 650 ms wait: no saving on short answers
    row = _rows(slow, "rest")["rules unsure, early text = final"]
    assert row.speculative.gap_ms == row.baseline.gap_ms
    fast = run_benchmark(Timing(stt_ms=200), modes=("rest",))
    row = _rows(fast, "rest")["rules unsure, early text = final"]
    assert row.baseline.gap_ms - row.speculative.gap_ms >= 100


def test_the_classifier_removes_the_model_call_for_the_common_answers(default_report):
    if load_active() is None:
        return
    rep = default_report
    for mode in ("rest", "stream"):
        row = _rows(rep, mode)["rules unsure, classifier knows"]
        assert row.classifier.path == "classifier" and row.classifier.model_calls == 0
        assert row.baseline.gap_ms - row.classifier.gap_ms >= 600  # about one model call
        assert rep.mean("classifier", mode) < rep.mean("baseline", mode)
        assert rep.mean("both", mode) <= rep.mean("classifier", mode)


def test_timeline_matches_the_documented_numbers():
    t = Timing()
    short = ScriptedCase("s", "haan ji", "haan ji")
    long = ScriptedCase("l", "a b c d e f g h", "a b c d e f g h")
    assert timeline_ms(short, t, "rest") == (None, 840.0)  # 340 + 500 > the 650 ms wait
    assert timeline_ms(long, t, "rest") == (840.0, 900.0)
    assert timeline_ms(short, t, "stream") == (500.0, 570.0)  # guess at 350 + 150, commit 350 + 220
    assert timeline_ms(long, t, "stream") == (500.0, 850.0)  # 350 + 150, final at 850


def test_streamed_free_form_replies_start_on_the_first_sentence(default_report):
    rep = default_report
    by = {f.name: f for f in rep.freeform}
    assert set(by) == set(FREEFORM_REPLIES)
    one, two, three = by["1 short sentence"], by["2 sentences"], by["3 sentences"]
    assert not any(f.fell_back for f in rep.freeform)
    assert one.streamed_gap_ms == pytest.approx(one.baseline_gap_ms)  # one sentence: nothing to overlap
    assert two.baseline_gap_ms - two.streamed_gap_ms > 150
    assert three.baseline_gap_ms - three.streamed_gap_ms > two.baseline_gap_ms - two.streamed_gap_ms
    for f in rep.freeform:
        assert f.streamed_gap_ms <= f.baseline_gap_ms + 1e-6
    # first sentence at ~ time to first token + the characters of that sentence at the model's speed
    t = rep.timing
    chars = len('{"type": "say", "text": "') + len(FREEFORM_REPLIES["2 sentences"][0])
    expect = t.ttft_ms + chars / (t.tokens_per_s * t.chars_per_token) * 1000
    assert abs(two.first_sentence_ms - expect) < 40


def test_a_slower_model_makes_streaming_matter_more():
    fast = run_benchmark(Timing(tokens_per_s=200), modes=("rest",))
    slow = run_benchmark(Timing(tokens_per_s=50), modes=("rest",))

    def saved(rep):
        f = next(x for x in rep.freeform if x.name == "3 sentences")
        return f.baseline_gap_ms - f.streamed_gap_ms

    assert saved(slow) > saved(fast)


def test_the_cases_cover_every_kind_and_the_weights_make_a_mix():
    cases = default_scripted_cases()
    assert abs(sum(c.weight for c in cases) - 1.0) < 1e-9
    assert any(c.caller_continues for c in cases) and any(c.early_text != c.final_text for c in cases)


def test_the_report_names_what_it_measures(default_report):
    text = default_report.format()
    for needle in ("Reply gap", "REST", "STREAM", "FREE-FORM", "ASSUMED mix", "wasted"):
        assert needle in text
