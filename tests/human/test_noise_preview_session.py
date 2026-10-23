# ruff: noqa: E501
"""Noise handling on synthetic noisy audio, metrics, pronunciation lab, preview kit, doctor and a full simulated call."""

from __future__ import annotations

import json
import sys

import pytest

from friday.core.config import Settings
from friday.core.models import CallOutcome
from friday.human import metrics as hm
from friday.human import preview, pronlab
from friday.human.layer import HumanLayer
from friday.human.lines import VARIANTS, all_lines
from friday.human.noise import NoiseGate, NoiseTracker, classify_floor, looks_like_noise, params_for
from friday.human.synth import call_audio, noise_only
from friday.voice.telephony.media import UtteranceSegmenter


def _track(rms: float, **kw):
    t, seg = NoiseTracker(), UtteranceSegmenter()
    for f in call_audio(noise_rms=rms, **kw):
        fr = seg.analyse(f)
        t.feed(fr.level, fr.speech)
    return t


@pytest.mark.parametrize("rms,klass", [(40, "clean"), (60, "clean"), (300, "moderate"), (600, "noisy"), (1500, "very_noisy")])
def test_noise_level_from_synthetic_audio(rms, klass):
    t = _track(rms)
    assert t.klass == klass
    assert t.summary()["noise_class"] == klass


def test_her_own_voice_is_not_counted_as_noise():
    t = NoiseTracker()
    for _ in range(300):
        t.feed(5000, True, friday_talking=True)
    assert t.n_noise == 0 and not t.levels


def test_params_get_more_conservative_with_noise():
    c, m, n, v = (params_for(k) for k in ("clean", "moderate", "noisy", "very_noisy"))
    assert c.end_silence_ms < m.end_silence_ms < n.end_silence_ms < v.end_silence_ms
    assert c.barge_level < n.barge_level < v.barge_level and c.start_prob_delta < v.start_prob_delta
    assert classify_floor(10) == "clean"


def test_pure_noise_is_not_speech_at_low_level_and_gate_ignores_it():
    seg = UtteranceSegmenter()
    assert not any(seg.analyse(f).speech for f in noise_only(1.0, 100))
    g = NoiseGate()
    assert g.decide("", speech_s=0.3) == "ignore" and g.ignored == 1 and g.asked == 0


def test_repeat_then_give_up_after_two_failures_and_reset_on_real_answer():
    g = NoiseGate()
    assert g.decide("###", speech_s=1.0) == "ask_repeat"
    assert g.decide("hmm", speech_s=0.2) == "ask_repeat"
    assert g.decide("...", speech_s=1.0) == "give_up"
    g2 = NoiseGate()
    assert g2.decide("???", speech_s=1.0) == "ask_repeat"
    assert g2.decide("haan kal aa jao", speech_s=1.0) == "answer" and g2.fails == 0
    assert looks_like_noise("x", confidence=0.1) and not looks_like_noise("rate kya hai")


def test_clean_calls_are_never_gated():
    assert NoiseGate().decide("", speech_s=0.2, noisy=False) == "answer"


# ------------------------------------------------------------------ metrics
def test_metrics_hangup_robot_length_and_aggregate(tmp_path):
    layer = HumanLayer(Settings(_env_file=None), "seed", call_id="c1")
    layer.observe_callee("kya aap robot ho?")
    layer.observe_callee("are you an AI?")
    m = layer.finish(hung_up_by_callee=True, length_s=7.0)
    assert m.hangup_within_10s and m.robot_asked == 2 and m.length_s == 7.0
    m2 = HumanLayer(Settings(_env_file=None), "s2", call_id="c2").finish(hung_up_by_callee=False, length_s=95)
    assert not m2.hangup_within_10s
    f = tmp_path / "m.jsonl"
    hm.append(m, f)
    hm.append(m2, f)
    a = hm.aggregate(hm.load(f))
    assert a["calls"] == 2 and a["hangup_within_10s_rate"] == 0.5 and a["calls_where_robot_asked"] == 1
    assert "noise" in m.line() and "no human-feel" in hm.report([])
    assert "phone" not in f.read_text().lower()


def test_noise_level_is_in_the_metrics_line():
    layer = HumanLayer(Settings(_env_file=None), "seed", call_id="c3")
    for fr in call_audio(noise_rms=1500):
        layer.noise.feed(float(abs(int.from_bytes(fr[:2], "little", signed=True))) + 1500, False)
    m = layer.finish(hung_up_by_callee=False, length_s=30)
    assert m.noise_class in ("noisy", "very_noisy") and m.noise_rms is not None


def test_asks_if_robot():
    assert hm.asks_if_robot("Kya aap robot ho?") and hm.asks_if_robot("is this a recording?")
    assert not hm.asks_if_robot("rate kya hai")


# ------------------------------------------------------------------ pronunciation lab
def test_pronlab_add_remove_and_view(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"pronunciations": {"hi-IN": {"AI": "A I"}, "en-IN": {"AI": "A I"}}}))
    done = pronlab.add("Shreya", "Shree-ya", file=f)
    assert done == {"hi-IN": "Shree-ya", "en-IN": "Shree-ya"}
    assert pronlab.dictionary_view("Namaste Shreya ji", "hi-IN", f) == "Namaste Shree-ya ji"
    with pytest.raises(ValueError):
        pronlab.add(" ", "x", file=f)
    assert pronlab.remove("Shreya", f) == 2
    assert pronlab.dictionary_view("Shreya", "hi-IN", f) == "Shreya"


# ------------------------------------------------------------------ preview + kit
async def _fake_synth(text, lang, pace):
    return b"\x01\x02" * (400 + len(text) * 20)


async def test_preview_renders_every_group_with_a_synth(tmp_path):
    files, msg = await preview.render_all(_fake_synth, tmp_path)
    groups = {p.split("/")[-2] for p in files}
    assert {"numbers", "prosody", "variants", "mood", "listener", "pauses", "resume", "noise"} <= groups
    assert sum(g == "variants" for g in (p.split("/")[-2] for p in files)) == len(all_lines())
    assert "rendered" in msg and (tmp_path / "index.tsv").exists()
    assert (tmp_path / "pauses" / "pause_600ms.wav").stat().st_size > (tmp_path / "pauses" / "pause_0ms.wav").stat().st_size


async def test_preview_without_keys_skips_with_a_message_and_prints_no_key(tmp_path):
    files, msg = await preview.render_all(None, tmp_path)
    assert files == [] and "no TTS key" in msg and "SARVAM_API_KEY" in msg  # key NAMES only
    assert (tmp_path / "index.tsv").read_text().count("\n") > 20


def test_make_synth_returns_none_without_keys():
    assert preview.make_synth(Settings(_env_file=None, sarvam_api_key=None, elevenlabs_api_key=None)) is None


async def test_listening_kit_blind_pairs_and_key(tmp_path):
    files, msg = await preview.build_listening_kit(_fake_synth, 4, tmp_path, seed=3)
    key = json.loads((tmp_path / "KEY_do_not_open_before_rating.json").read_text())
    assert len([f for f in files if "pair_" in f]) == 8 and (tmp_path / "call_1.wav").exists()
    assert {key["call_1.wav"]["is"], key["call_2.wav"]["is"]} == {"old", "new"}
    assert {key["pair_01"]["A"], key["pair_01"]["B"]} == {"old", "new"}
    assert "pair" in (tmp_path / "rating_sheet.csv").read_text()
    again, _ = await preview.build_listening_kit(None, 2, tmp_path / "x")
    assert again == []


# ------------------------------------------------------------------ CLI / doctor / selftest
def test_selftest_passes_and_lists_switches(capsys):
    from friday.human.selftest import run

    assert run(Settings(_env_file=None, voice_profile="internal-test")) == 0
    out = capsys.readouterr().out
    assert "VOICE SELFTEST PASS" in out and "FRIDAY_HUMAN_BACKCHANNELS" in out and "ON " in out


def test_cli_voice_commands(capsys, monkeypatch, tmp_path):
    from friday import cli

    monkeypatch.setattr(sys, "argv", ["friday"])
    assert cli.main(["voice", "switches"]) == 0
    assert "FRIDAY_INTENT_CLASSIFIER" in capsys.readouterr().out
    monkeypatch.setenv("SARVAM_API_KEY", "")
    assert cli.main(["voice", "human-preview", "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "index.tsv").exists()
    assert cli.main(["voice", "metrics", "--file", str(tmp_path / "none.jsonl")]) == 0


def test_doctor_switches_report_each_voice_switch():
    from friday.ops.doctor import check_switches

    sec = check_switches(Settings(_env_file=None, voice_profile="internal-test"))
    text = "\n".join(str(x) for x in sec.items) if hasattr(sec, "items") else str(sec.__dict__)
    for name in ("FRIDAY_HUMAN_BACKCHANNELS=on", "FRIDAY_VOICE_STREAM_STT=off", "FRIDAY_INTENT_CLASSIFIER=on"):
        assert name in text


def test_doc_lists_every_pending_line():
    from pathlib import Path

    doc = Path("docs/HUMAN_VOICE.md").read_text(encoding="utf-8")
    for key, lang, _i, text in all_lines():
        assert text in doc, (key, lang, text)
    assert set(VARIANTS)  # table not empty
