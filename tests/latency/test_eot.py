# ruff: noqa: E501
"""Semantic end-of-turn: rules, trained model, training/eval commands, gate, segmenter and leg wiring."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from friday.core.config import Settings
from friday.learning import cli as learn_cli
from friday.learning import eot_train
from friday.learning.eot_synth import generate
from friday.learning.eot_train import (
    Gate,
    TrainConfig,
    apply_gate,
    build_training_set,
    evaluate,
    load_gold,
    run_training,
)
from friday.voice import eot
from friday.voice.eot import (
    EotConfig,
    EotModel,
    SemanticEot,
    Verdict,
    apply_rules,
    build_semantic_eot,
    load_active,
)
from friday.voice.session import _Session
from friday.voice.telephony.media import UtteranceSegmenter
from tests.voice.test_vobiz_turns import (
    _frames,
    _leg,
    _silence_frames,
    _TextSTT,
)


def rules(text: str, kind: str = "") -> Verdict:
    hit = apply_rules(text, kind)
    return hit.verdict if hit and hit.confidence >= 0.9 else Verdict.UNSURE


# --------------------------------------------------------------------------- rules
@pytest.mark.parametrize("text,kind", [
    ("Haan, kal shaam ko", "time"), ("haan kal shaam ko...", "time"), ("500 ke liye", "price"),
    ("400 se", "price"), ("umm", ""), ("hmm", ""), ("main kal aaunga lekin", ""),
    ("kyunki", ""), ("because", ""), ("I was thinking that", ""), ("mera naam", "name"),
    ("mera naam hai", "name"), ("98765", "phone"), ("98765 43", "phone"), ("हाँ लेकिन", ""),
    ("मेरा नाम", "name"), ("कल शाम को", "time"), ("aur", ""), ("so basically", ""),
    ("around", "time"), ("lagbhag", "price"), ("the", ""), ("wo mere bhai ka", ""),
])
def test_unfinished_shapes_are_incomplete(text, kind):
    assert rules(text, kind) is Verdict.INCOMPLETE


@pytest.mark.parametrize("text,kind", [
    ("Haan ji, 500 rupaye", "price"), ("500", "price"), ("paanch sau", "price"),
    ("haan ji", "yesno"), ("nahi", "yesno"), ("ji bataiye", ""), ("haan ji bataiye", ""),
    ("kal shaam 6 baje", "time"), ("6:30", "time"), ("9876543210", "phone"),
    ("mera number 9876543210 hai", "phone"), ("wo kal aa jayega", ""), ("theek hai", ""),
    ("शाम 6 बजे", "time"), ("जी बताइए", ""), ("500 rupaye", ""), ("thank you sir", ""),
])
def test_finished_shapes_are_complete(text, kind):
    assert rules(text, kind) is Verdict.COMPLETE


def test_a_price_without_rupaye_is_complete_only_after_a_price_question():
    assert rules("500", "price") is Verdict.COMPLETE
    assert rules("500", "") is Verdict.UNSURE  # nothing says it is a price


def test_a_phone_number_dictated_in_pieces_needs_extra_wait():
    assert rules("98765", "phone") is Verdict.INCOMPLETE
    assert rules("98765 43210", "phone") is Verdict.COMPLETE
    assert rules("9876543", "phone") is Verdict.INCOMPLETE


def test_an_hour_without_baje_is_unfinished_but_with_baje_finished():
    hit = apply_rules("kal shaam 6", "time")  # softer rule (0.85): the model may overrule it
    assert hit is not None and hit.verdict is Verdict.INCOMPLETE and hit.confidence >= 0.8
    assert rules("kal shaam 6 baje", "time") is Verdict.COMPLETE


def test_a_terminal_full_stop_does_not_override_a_dangling_connector_to_certain():
    # STT puts "." after any audio that ended; the rule keeps it below the hard-rule bar
    assert rules("haan kal shaam ko.", "time") is Verdict.UNSURE
    hit = apply_rules("haan kal shaam ko.", "time")
    assert hit and hit.verdict is Verdict.INCOMPLETE and hit.confidence > 0.8


def test_unknown_text_is_unsure_and_garbage_never_raises():
    det = SemanticEot(None, 0.9, rules_only=True)
    for t in ("", "   ", "...", "@@@", "\x00", "a" * 5000, "१२३", "😀"):
        d = det.assess(t, "price")
        assert d.verdict in (Verdict.UNSURE, Verdict.INCOMPLETE, Verdict.COMPLETE)
    assert det.assess("", "").verdict is Verdict.UNSURE
    assert det.assess("kuchh bhi nahi samajh aaya mujhe is baat ka matlab", "bogus").verdict is not None


def test_detector_is_deterministic():
    det = SemanticEot(load_active()[0], 0.8)  # type: ignore[index]
    texts = ["haan ji 500 rupaye", "Haan, kal shaam ko...", "yes that works", "wo kal ka"]
    assert [det.assess(t, "").confidence for t in texts] == [det.assess(t, "").confidence for t in texts]


# --------------------------------------------------------------------------- data and the held-out set
def test_the_hand_written_list_is_big_enough_and_split():
    train, test = load_gold()
    assert len(train) + len(test) >= 300 and len(test) >= 100
    assert sum(1 for e in test if e.label == "incomplete") >= 30
    scripts = {"devanagari": 0, "roman": 0, "english": 0}
    for e in train + test:
        if any("ऀ" <= c <= "ॿ" for c in e.text):
            scripts["devanagari"] += 1
        elif any(w in e.text.lower().split() for w in ("the", "is", "and", "but", "because", "yes", "my")):
            scripts["english"] += 1
        else:
            scripts["roman"] += 1
    assert all(v >= 20 for v in scripts.values()), scripts


def test_held_out_sentences_are_never_trained_on():
    train, test = load_gold()
    held = {eot_train._key(e.text) for e in test}
    assert not held & {eot_train._key(e.text) for e in train}  # the two lists do not overlap
    all_train, gold, held_out = build_training_set()
    assert held_out == test
    assert not held & {eot_train._key(e.text) for e in all_train}  # nor does any synthetic row


def test_synthetic_data_is_deterministic_and_seeded():
    assert generate(7) == generate(7)
    assert generate(7) != generate(8)
    labels = {lab for _t, lab, _k in generate(7)}
    assert labels == {"complete", "incomplete"}


def test_training_is_deterministic_same_data_same_bytes():
    train, _gold, _held = build_training_set()
    a = eot_train.train_model(train, TrainConfig(7, 0.1, 0.4))
    b = eot_train.train_model(train, TrainConfig(7, 0.1, 0.4))
    assert a.dumps() == b.dumps()


# --------------------------------------------------------------------------- the shipped model
def test_the_shipped_model_is_gate_passed_and_matches_its_version_file():
    active = load_active()
    assert active is not None
    model, ver = active
    text = eot.MODEL_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(model.dumps().encode()).hexdigest() == ver["model_sha256"]
    assert hashlib.sha256(text.encode()).hexdigest() == ver["model_sha256"]
    assert ver["trained_on_held_out"] is False and ver["gate"]["passed"] is True
    _train, _gold, held = build_training_set()
    assert ver["data_hash"] == eot_train.data_hash(_train, held)  # data changed -> retrain


def test_the_shipped_model_beats_the_rules_only_baseline_with_few_false_cuts():
    model, ver = load_active()  # type: ignore[misc]
    _tr, test = load_gold()
    thr = float(ver["threshold"])
    m = evaluate(SemanticEot(model, thr), test)
    b = evaluate(SemanticEot(None, thr, rules_only=True), test)
    assert m["accuracy"] > b["accuracy"]
    assert m["false_cut_rate"] <= 0.02
    # per-class numbers exist and are in range
    for cls in ("complete", "incomplete"):
        assert 0.0 <= m["per_class"][cls]["precision"] <= 1.0
    assert m["decided_accuracy"] >= 0.9


def test_a_rules_hard_verdict_wins_over_the_model():
    model, _ = load_active()  # type: ignore[misc]
    det = SemanticEot(model, 0.8)
    d = det.assess("haan kal shaam ko", "time")
    assert d.incomplete and d.source.startswith("rule:")


def test_without_a_gate_passed_model_the_builder_falls_back_to_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(eot, "MODEL_PATH", tmp_path / "none.json")
    monkeypatch.setattr(eot, "VERSION_PATH", tmp_path / "none.version.json")
    det = build_semantic_eot(EotConfig(enabled=True))
    assert det is not None and det.model is None
    assert build_semantic_eot(EotConfig(enabled=False)) is None


def test_a_model_whose_version_file_says_gate_failed_is_not_loaded(tmp_path):
    model, ver = load_active()  # type: ignore[misc]
    (tmp_path / "m.json").write_text(model.dumps(), encoding="utf-8")
    bad = dict(ver, gate={"passed": False, "checks": []})
    (tmp_path / "m.version.json").write_text(json.dumps(bad), encoding="utf-8")
    assert load_active(tmp_path / "m.json") is None


# --------------------------------------------------------------------------- the gate
def _metrics(acc, cut_count, n_inc=60, n=120):
    return {"n": n, "n_incomplete": n_inc, "accuracy": acc, "false_cut_count": cut_count,
            "false_cut_rate": cut_count / n_inc}


def test_gate_passes_a_better_model_with_few_false_cuts():
    g = apply_gate(_metrics(0.92, 1), _metrics(0.85, 1), 0.9)
    assert g.passed


def test_gate_refuses_a_model_that_does_not_beat_the_baseline():
    g = apply_gate(_metrics(0.85, 0), _metrics(0.85, 0), 0.9)
    assert not g.passed
    assert not next(c for c in g.checks if c["name"].startswith("beats"))["ok"]


def test_gate_refuses_a_false_cut_rate_above_two_percent():
    g = apply_gate(_metrics(0.95, 2), _metrics(0.85, 0), 0.9)  # 2 of 60 = 3.3%
    assert not g.passed
    assert not next(c for c in g.checks if c["name"].startswith("false-cut"))["ok"]


def test_gate_refuses_a_held_out_set_too_small_to_mean_anything():
    g = apply_gate(_metrics(0.99, 0, n_inc=10, n=40), _metrics(0.5, 0, n_inc=10, n=40), 0.9)
    assert not g.passed


def test_a_refused_model_is_never_written(tmp_path, monkeypatch):
    monkeypatch.setattr(eot_train, "apply_gate", lambda *a, **k: Gate(False, [{"name": "x", "ok": False, "detail": ""}]))
    mp, vp = tmp_path / "m.json", tmp_path / "m.version.json"
    res = run_training(model_path=mp, version_path=vp, write=True)
    assert not res.gate.passed and not res.written
    assert not mp.exists() and not vp.exists()


def test_a_passing_model_is_written_with_its_version_file(tmp_path):
    mp, vp = tmp_path / "m.json", tmp_path / "m.version.json"
    res = run_training(model_path=mp, version_path=vp, write=True)
    assert res.gate.passed and res.written and mp.exists() and vp.exists()
    ver = json.loads(vp.read_text())
    assert ver["gate"]["passed"] and ver["held_out"]["false_cut_rate"] <= 0.02
    assert EotModel.loads(mp.read_text()).dumps() == mp.read_text()
    # the same data trains the same bytes as the model shipped in the repo
    assert mp.read_text() == eot.MODEL_PATH.read_text()


def test_dry_run_writes_nothing(tmp_path):
    mp, vp = tmp_path / "m.json", tmp_path / "m.version.json"
    run_training(model_path=mp, version_path=vp, write=False)
    assert not mp.exists()


def test_cli_train_dry_run_and_eval(capsys):
    assert learn_cli.run(argparse.Namespace(learn_cmd="train-eot", dry_run=True, seed=7)) == 0
    out = capsys.readouterr().out
    assert "FALSE-CUT rate" in out and "rules only" in out and "gate ok" in out
    ns = argparse.Namespace(learn_cmd="eval-eot", model=None, threshold=None, split="test", mistakes=True)
    assert learn_cli.run(ns) == 0
    out = capsys.readouterr().out
    assert "precision" in out and "recall" in out and "false-extend" in out and "mean added delay" in out


# --------------------------------------------------------------------------- segmenter
def _speech_then_silence(seg, speech_frames, silence_frames):
    from friday.voice.audio import tone

    loud = tone(440, 0.02, 8000, 0.9)
    quiet = b"\x00\x00" * 160
    got, n = [], None
    for _ in range(speech_frames):
        got += seg.feed_pcm16(loud)
    for i in range(silence_frames):
        out = seg.feed_pcm16(quiet)
        got += out
        if out and n is None:
            n = i + 1
    return got, n


def test_extend_wait_lengthens_this_pause_only():
    seg = UtteranceSegmenter(end_silence_ms=900, short_end_silence_ms=650)
    from friday.voice.audio import tone

    for _ in range(20):
        seg.feed_pcm16(tone(440, 0.02, 8000, 0.9))
    for _ in range(20):
        seg.feed_pcm16(b"\x00\x00" * 160)  # 400 ms of silence
    assert seg.extend_wait(700) is True
    got: list = []
    n = 0
    while not got and n < 80:
        got += seg.feed_pcm16(b"\x00\x00" * 160)
        n += 1
    assert (20 + n) * 20 >= 1350  # 650 + 700, not 650
    assert seg._extra_wait_ms == 0  # reset when the utterance closed


def test_extend_wait_is_capped_not_stacked_and_cleared_by_new_speech():
    seg = UtteranceSegmenter()
    assert seg.extend_wait(700) is False  # nothing is open
    from friday.voice.audio import tone

    for _ in range(10):
        seg.feed_pcm16(tone(440, 0.02, 8000, 0.9))
    seg.extend_wait(700)
    seg.extend_wait(700)
    assert seg._extra_wait_ms == 700  # not stacking
    seg.extend_wait(99999)
    assert seg._extra_wait_ms == seg.max_extra_wait_ms == 1500  # capped
    seg.feed_pcm16(tone(440, 0.02, 8000, 0.9))
    assert seg._extra_wait_ms == 0  # the caller spoke again: the judgement is stale


def test_hold_close_delays_the_close_but_only_up_to_the_cap():
    seg = UtteranceSegmenter(end_silence_ms=900, short_end_silence_ms=650)
    from friday.voice.audio import tone

    for _ in range(20):
        seg.feed_pcm16(tone(440, 0.02, 8000, 0.9))
    seg.hold_close(True)
    got, closed_at = [], None
    for i in range(120):
        out = seg.feed_pcm16(b"\x00\x00" * 160)
        if out:
            closed_at = (i + 1) * 20
            break
    assert closed_at is not None and 650 + 800 - 40 <= closed_at <= 650 + 800 + 40
    assert not got


# --------------------------------------------------------------------------- the call leg
def _eot_leg_setup(leg, extend_ms=700):
    leg.eot = SemanticEot(None, 0.9, rules_only=True)
    leg.eot_cfg = EotConfig(enabled=True, extend_ms=extend_ms)
    leg.eot_context = lambda: "time"


async def _speak_pause(leg, text):
    leg.tel.stt = _TextSTT(text)
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    await asyncio.sleep(0.05)


async def test_unfinished_words_extend_the_wait_for_this_pause():
    leg, _ = await _leg()
    _eot_leg_setup(leg)
    await _speak_pause(leg, "haan kal shaam ko")
    assert leg.eot_last is not None and leg.eot_last[1].incomplete
    for f in _silence_frames(0.6):  # 1.0 s of silence: today's 650 ms wait would have closed it
        leg.on_media(f)
    assert leg._segments.empty()
    for f in _silence_frames(0.5):  # 1.5 s: past 650 + 700
        leg.on_media(f)
    seg = leg._segments.get_nowait()
    t = await leg._transcribe(seg)
    assert t is not None and t.text == "haan kal shaam ko"


async def test_without_the_switch_the_same_words_close_at_the_normal_wait():
    leg, _ = await _leg()
    assert leg.eot is None
    await _speak_pause(leg, "haan kal shaam ko")
    for f in _silence_frames(0.4):
        leg.on_media(f)
    assert not leg._segments.empty()


async def test_finished_short_answer_is_committed_at_the_early_point():
    leg, _ = await _leg()
    _eot_leg_setup(leg)
    await _speak_pause(leg, "haan ji bataiye")  # no final punctuation: the old rule would wait
    assert leg.eot_last is not None and leg.eot_last[1].complete
    seg = leg._segments.get_nowait()  # committed with no more silence fed
    assert seg is not None


async def test_unfinished_words_veto_an_early_commit_even_with_a_full_stop():
    leg, _ = await _leg()
    _eot_leg_setup(leg)
    await _speak_pause(leg, "haan kal shaam ko.")
    assert leg._segments.empty()  # the old punctuation rule would have committed this


async def test_unsure_changes_nothing():
    leg, _ = await _leg()
    _eot_leg_setup(leg)
    await _speak_pause(leg, "kuchh bhi samajh nahi aaya pata nahi kya")
    assert leg.eot_last is not None and leg.eot_last[1].verdict is Verdict.UNSURE
    for f in _silence_frames(0.4):
        leg.on_media(f)
    assert not leg._segments.empty()  # closed at the normal 650 ms wait


async def test_the_close_is_held_while_the_words_are_judged_and_released_after():
    leg, _ = await _leg()
    _eot_leg_setup(leg)
    for f in _frames(1.0, 0.9) + _silence_frames(0.4):
        leg.on_media(f)
    assert leg._segmenter._hold_close is True  # judging has started
    await asyncio.sleep(0.05)
    assert leg._segmenter._hold_close is False  # verdict in: released


async def test_a_broken_detector_never_breaks_the_leg():
    leg, _ = await _leg()
    _eot_leg_setup(leg)

    class Boom:
        def assess(self, *a):
            raise RuntimeError("boom")

    leg.eot = Boom()  # type: ignore[assignment]
    await _speak_pause(leg, "haan ji")
    for f in _silence_frames(0.4):
        leg.on_media(f)
    assert leg._segmenter._hold_close is False


# --------------------------------------------------------------------------- session and switches
def test_switches_default_off_and_the_extension_is_capped_by_config():
    s = Settings(_env_file=None)
    assert s.voice_semantic_eot is False
    assert s.voice_semantic_eot_extend_ms == 700 and s.voice_semantic_eot_threshold is None
    assert EotConfig(enabled=True, extend_ms=5000).extend == 1500
    assert EotConfig(enabled=True, extend_ms=-5).extend == 0
    with pytest.raises(Exception):  # noqa: B017
        Settings(_env_file=None, voice_semantic_eot_extend_ms=5000)


def _fake_session(on, policy):
    return SimpleNamespace(
        settings=Settings(_env_file=None, voice_semantic_eot=on),
        r=SimpleNamespace(policy=policy), brief=object(), transcript=object(),
    )


async def test_session_attaches_the_detector_only_with_the_switch_on():
    leg, _ = await _leg()
    off = _fake_session(False, object())
    _Session._attach_semantic_eot(off, leg)  # type: ignore[arg-type]
    assert leg.eot is None and leg.eot_context is None

    on = _fake_session(True, SimpleNamespace(expected_answer=lambda b, t: "price"))
    on._expected_answer = lambda: _Session._expected_answer(on)  # type: ignore[arg-type]
    _Session._attach_semantic_eot(on, leg)  # type: ignore[arg-type]
    assert leg.eot is not None and leg.eot_cfg is not None and leg.eot_cfg.extend == 700
    assert leg.eot_context is not None and leg.eot_context() == "price"


async def test_a_policy_without_expected_answer_gives_no_context():
    s = _fake_session(True, object())
    assert _Session._expected_answer(s) == ""  # type: ignore[arg-type]


def test_the_playbook_policy_reports_what_the_step_expects():
    from friday.playbooks.engine import PlaybookPolicy
    from tests.playbooks.conftest import make_brief

    pol = PlaybookPolicy()
    brief = make_brief()
    pb = pol.playbook(brief)
    kinds = {sid: _expected_for_step(pol, brief, pb, sid) for sid in pb.steps}
    assert set(kinds.values()) <= {"", "price", "time", "yesno", "name", "phone"}
    assert "price" in kinds.values() and "yesno" in kinds.values()


def _expected_for_step(pol, brief, pb, step_id):
    from friday.core.models import Transcript

    tr = Transcript()
    st = pol._state(pb, tr)
    st.step = step_id
    return pol.expected_answer(brief, tr)
