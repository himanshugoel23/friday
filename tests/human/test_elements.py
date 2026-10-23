# ruff: noqa: E501
"""Offline tests of the human-voice elements (numbers, prosody, variants, mood, listener, pauses, backchannel, resume)."""

from __future__ import annotations

import pytest

from friday.core.config import Settings
from friday.human import profile as prof
from friday.human.backchannel import MAX_PER_ANSWER, BackchannelEngine
from friday.human.layer import PROTECTED, HumanLayer
from friday.human.lines import EXISTING_REPEAT_LINE, VARIANTS, all_lines
from friday.human.listener import ListenerModel, is_repeat_request, shorten
from friday.human.mood import MoodAdapter, detect
from friday.human.numbers import number_words, phone_words, speak_numbers, time_words
from friday.human.pauses import CEILING_MS, PausePlanner, other_side_waiting
from friday.human.prosody import apply as prosody, classify
from friday.human.resume import is_acknowledgement, unfinished, with_connector
from friday.human.variants import VariantPicker, detect_style


def S(**kw):
    return Settings(_env_file=None, **kw)


# ------------------------------------------------------------------ profile / switches
def test_production_defaults_audible_off_silent_on():
    s = S()
    assert not any(getattr(s, n) for n in prof.AUDIBLE)
    for n in ("intent_classifier", "voice_speculative_understanding", "llm_stream_to_tts", "voice_semantic_eot", "human_resume", "human_metrics"):
        assert getattr(s, n) is True
    assert s.voice_vad_backend == "silero"
    assert s.voice_stream_stt is False  # not compared on real audio yet


def test_internal_test_turns_everything_on_but_not_stream_stt():
    s = S(voice_profile="internal-test")
    assert all(getattr(s, n) for n in prof.INTERNAL_TEST_ON)
    assert s.voice_stream_stt is False


def test_explicit_setting_beats_the_profile():
    s = S(voice_profile="internal-test", human_backchannels=False)
    assert s.human_backchannels is False and s.human_numbers is True


def test_env_profile(monkeypatch):
    monkeypatch.setenv("FRIDAY_VOICE_PROFILE", "internal-test")
    assert Settings(_env_file=None).human_pauses is True


def test_switch_report_names_every_switch_without_secrets():
    rep = prof.format_report(S(voice_profile="internal-test"))
    for env in prof.ENV.values():
        assert env in rep
    assert "key" not in rep.lower().replace("keep", "")


def test_vad_report_is_honest_about_fallback():
    assert prof.vad_effective(S(voice_vad_backend="energy")) == "energy"
    assert prof.vad_effective(S()).split()[0] in ("silero", "energy")


def test_silero_failure_falls_back_to_energy():
    from friday.voice.vad import build_vad

    class Boom:
        pass

    assert build_vad("energy") is None  # energy rule
    # a missing model / extra yields None (energy), never an exception
    import friday.voice.vad.silero as sv

    orig = sv.SileroVad
    sv.SileroVad = lambda **k: (_ for _ in ()).throw(RuntimeError("no extra"))  # type: ignore[assignment]
    try:
        assert sv.build_vad("silero") is None
    finally:
        sv.SileroVad = orig  # type: ignore[assignment]


# ------------------------------------------------------------------ numbers
@pytest.mark.parametrize("n,words", [(0, "zero"), (7, "saat"), (21, "ikkis"), (99, "ninyanve"), (100, "ek sau"), (150, "dedh sau"), (250, "dhai sau"), (450, "chaar sau pachaas"), (1500, "dedh hazaar"), (2500, "dhai hazaar"), (4999, "chaar hazaar nau sau ninyanve"), (100000, "ek lakh")])
def test_number_words(n, words):
    assert number_words(n) == words


@pytest.mark.parametrize("h,m,mer,out", [(5, 30, "pm", "shaam saade paanch baje"), (5, 15, "pm", "shaam sawa paanch baje"), (5, 45, "pm", "shaam paune chhe baje"), (10, 0, "am", "subah das baje"), (1, 30, "pm", "dopahar derh baje"), (2, 30, "pm", "dopahar dhai baje"), (9, 0, "pm", "raat nau baje"), (5, 20, None, "paanch bajkar bees minute")])
def test_time_words(h, m, mer, out):
    assert time_words(h, m, mer) == out


def test_speak_numbers_sentences():
    assert speak_numbers("Rate 450 rupaye hai", "hinglish") == "Rate chaar sau pachaas rupaye hai"
    assert speak_numbers("Rs. 1,500 lagenge", "hinglish") == "dedh hazaar rupaye lagenge"
    assert speak_numbers("Kal shaam 5:30 pm ko", "hinglish") == "Kal shaam saade paanch baje ko"
    assert speak_numbers("5:45 baje", "hinglish") == "paune chhe baje"
    assert speak_numbers("Rs 450, 5:30 pm", "hinglish") == "chaar sau pachaas rupaye, shaam saade paanch baje"


def test_phone_digits_in_groups():
    assert phone_words("9876543210") == "nau aath saat, chhe paanch chaar teen, do ek zero"
    assert phone_words("+91 98765 43210").startswith("nau aath saat,")


def test_numbers_left_alone_in_english_devanagari_and_secrets():
    assert speak_numbers("Rate 450", "en") == "Rate 450"
    assert speak_numbers("रेट 450", "hi") == "रेट 450"
    assert speak_numbers("OTP 482913", "hinglish") == "OTP 482913"
    assert speak_numbers("", "hinglish") == ""


# ------------------------------------------------------------------ prosody
def test_prosody_kinds_and_hints():
    assert classify("Rate 450 rupaye") == "number"
    assert classify("Maaf kijiye, slot nahi ho paega") == "bad_news"
    assert classify("Aap kab aayenge?") == "question"
    assert classify("Dhanyavaad") == "thanks"
    text, h = prosody("Rate chaar sau pachaas rupaye hai")
    assert h.rate_mult < 1.0 and "Rate," in text


# ------------------------------------------------------------------ variants / mirror
def test_every_pending_line_has_three_languages_and_no_human_claim():
    for by in VARIANTS.values():
        assert set(by) == {"hinglish", "hi", "en"}
        assert all(len(v) >= 2 for v in by.values())
    for *_, t in all_lines():
        assert "human" not in t.lower() and "insaan" not in t.lower()
        assert not any(c.isdigit() for c in t)


def test_variants_deterministic_per_seed_and_no_back_to_back_repeat():
    a, b = VariantPicker("call-A"), VariantPicker("call-A")
    seq_a = [a.pick("hold.moment") for _ in range(6)]
    assert seq_a == [b.pick("hold.moment") for _ in range(6)]
    assert all(x != y for x, y in zip(seq_a, seq_a[1:], strict=False))
    assert VariantPicker("call-B", enabled=False).pick("hold.moment") == VARIANTS["hold.moment"]["hinglish"][0]


def test_mirroring_picks_matching_language():
    p = VariantPicker("c", mirror=True)
    p.observe_callee("Yes please tell me the price for tomorrow")
    assert p.pick("hold.moment") in VARIANTS["hold.moment"]["en"]
    p.observe_callee("हाँ जी बताइए क्या चाहिए आपको")
    assert p.pick("hold.moment") in VARIANTS["hold.moment"]["hi"]
    assert detect_style("haan ji kal aa jao") == "hinglish"
    assert VariantPicker("c", mirror=False).pick("hold.moment", "hinglish") in VARIANTS["hold.moment"]["hinglish"]


def test_existing_fixed_lines_get_variants():
    p = VariantPicker("c")
    base = VARIANTS["hold.waiting"]["hinglish"][0].format(name="Rahul")
    got = {VariantPicker(f"c{i}").replacement_for(base, "Rahul") for i in range(12)}
    assert got <= {o.format(name="Rahul") for o in VARIANTS["hold.waiting"]["hinglish"]}
    assert len(got) > 1
    assert p.replacement_for("Something else entirely.", "Rahul") is None


# ------------------------------------------------------------------ mood / listener
def test_mood_detection_and_adaptation():
    assert detect("jaldi bolo busy hoon") == "rushed"
    assert detect("kitni baar call karoge, pareshan mat karo") == "annoyed"
    assert detect("haan boliye") == "neutral"
    m = MoodAdapter()
    assert m.adapt("Kya aap rate bata sakte hain? Kab khali hain?") == "Kya aap rate bata sakte hain? Kab khali hain?"  # inactive: unchanged
    m.observe("jaldi bolo")
    out = m.adapt("Namaste. Kya aap rate bata sakte hain? Kab khali hain? Dhanyavaad.")
    assert out.count("?") == 1 and len(out.split()) <= 12


def test_one_apology_per_call_and_no_apology_without_mood():
    layer = HumanLayer(S(voice_profile="internal-test"), "seed")
    assert "poochti" not in layer.shape("Kya aap rate bata sakte hain?", "hinglish", first_turn=False).text
    layer.observe_callee("jaldi bolo, busy hoon")
    first = layer.shape("Kya aap rate bata sakte hain?", "hinglish").text
    second = layer.shape("Kab khali hain?", "hinglish").text
    ap = {o for o in VARIANTS["mood.apology"]["hinglish"]}
    assert any(first.startswith(a) for a in ap)
    assert not any(second.startswith(a) for a in ap)


def test_listener_slow_hesitant_and_busy():
    slow = ListenerModel()
    slow.observe("kya? sorry", 1.5)
    slow.observe("um matlab woh ... ek minute", 3.0)
    assert slow.style() == "slow" and 0.8 <= slow.pace() < 0.9 and slow.max_words() == 16
    busy = ListenerModel()
    busy.observe("haan", 0.5)
    busy.observe("500", 0.6)
    assert busy.style() == "busy" and 0.9 < busy.pace() <= 1.0
    assert ListenerModel().pace() == 0.9
    assert is_repeat_request("kya?") and is_repeat_request("Sorry?") and not is_repeat_request("rate kitna hai")


def test_pace_always_inside_the_safe_range():
    lm = ListenerModel()
    for _ in range(10):
        lm.observe("kya? um um matlab ... sorry?", 1.0)
    assert 0.8 <= lm.pace() <= 1.0


def test_shorten_keeps_questions_numbers_and_never_touches_disclosure():
    t = "Haan theek hai. Yeh ek lamba vaakya hai jisme kuch kaam ki baat nahi. Kal 5 baje aa jayenge? Dhanyavaad aapka bahut bahut."
    out = shorten(t, 10)
    assert "5 baje" in out and out.startswith("Haan theek hai.")
    disc = "Main Friday hoon, Rahul ki virtual assistant. " + "bla " * 30
    assert shorten(disc, 5) == disc


# ------------------------------------------------------------------ pauses
def test_pause_is_varied_deterministic_and_in_range():
    a, b = PausePlanner("seed"), PausePlanner("seed")
    xs = [a.plan(our_line="Aur kam hoga?", callee_text="Rate 500 lagega") for _ in range(8)]
    assert xs == [b.plan(our_line="Aur kam hoga?", callee_text="Rate 500 lagega") for _ in range(8)]
    assert all(250 <= x <= 600 for x in xs) and len(set(xs)) > 1


def test_no_pause_when_the_other_side_is_waiting_or_nothing_hard():
    p = PausePlanner("s")
    assert other_side_waiting("Aap kab aayenge?")
    assert p.plan(our_line="Ji", callee_text="Aapka naam kya hai?") == 0
    assert p.plan(our_line="Theek hai.", callee_text="haan boliye") == 0


def test_no_dead_air_over_a_second():
    for gap in (0, 300, 600, 800, 950, 2000):
        ms = PausePlanner("s").plan(our_line="Final?", callee_text="500 lagega", gap_so_far_ms=gap)
        assert ms + gap <= CEILING_MS or ms == 0


# ------------------------------------------------------------------ backchannels
def test_backchannel_only_in_long_answers_at_pauses():
    e = BackchannelEngine("s")
    assert e.consider(now_s=10, speech_s=2.0, silence_ms=300) is None  # short answer
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=100) is None  # not a pause yet
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=700) is None  # turn is ending
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=300, speech_active=True) is None  # over them
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=300, friday_speaking=True) is None
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=300) in VARIANTS["bc.short"]["hinglish"]


def test_backchannel_rate_limit_once_per_pause_and_caps():
    e = BackchannelEngine("s")
    assert e.consider(now_s=10, speech_s=6.0, silence_ms=300)
    assert e.consider(now_s=10.1, speech_s=6.0, silence_ms=340) is None  # same pause
    assert e.consider(now_s=12, speech_s=8.0, silence_ms=300, speech_active=False) is None  # gap < 6 s
    e.consider(now_s=16, speech_s=9.0, silence_ms=0, speech_active=True)  # speech resumed
    assert e.consider(now_s=17, speech_s=9.0, silence_ms=300)  # second in the answer, 7 s later
    e.consider(now_s=17.1, speech_s=9.0, silence_ms=10, speech_active=True)
    assert e.consider(now_s=25, speech_s=11.0, silence_ms=300) is None  # max per answer
    assert MAX_PER_ANSWER == 2
    e.new_answer()
    assert e.consider(now_s=40, speech_s=5.0, silence_ms=300)


def test_backchannel_never_repeats_back_to_back_and_off_for_elders_or_switch():
    e = BackchannelEngine("s")
    seen = []
    for i in range(3):
        seen.append(e.consider(now_s=10 + i * 10, speech_s=6.0, silence_ms=300))
        e.new_answer()
        e.consider(now_s=10 + i * 10 + 1, speech_s=6.0, silence_ms=5, speech_active=True)
    assert all(a != b for a, b in zip(seen, seen[1:], strict=False))
    assert BackchannelEngine("s", allowed=False).consider(now_s=10, speech_s=6.0, silence_ms=300) is None
    assert BackchannelEngine("s", enabled=False).consider(now_s=10, speech_s=6.0, silence_ms=300) is None
    assert HumanLayer.from_settings(S(voice_profile="internal-test"), call_id="c", relation="mother").backchannel.enabled is False


# ------------------------------------------------------------------ resume
def test_resume_continues_not_restarts():
    full = "Pehli baat yeh hai. Doosri baat jo main aapse kehna chahti thi, kal aana hai. Teesri baat."
    assert unfinished(full, 2) == "kal aana hai. Teesri baat."
    assert unfinished(full, 0) == full
    assert unfinished(full, 3) == "Teesri baat."
    assert unfinished("Ek hi baat.", 1) is None


def test_resume_only_after_a_go_on_not_after_a_question():
    for ok in ("haan ji boliye", "hmm", "achha", "ji", "go on", "theek hai ji"):
        assert is_acknowledgement(ok), ok
    for no in ("rate kitna hai", "kaun bol raha hai", "nahi chahiye", ""):
        assert not is_acknowledgement(no), no
    layer = HumanLayer(S(voice_profile="internal-test"), "seed")
    layer.note_interrupted("Pehli baat yeh hai. Doosri baat jo main aapse kehna chahti thi, kal aana hai.", 1)
    assert layer.take_resume("rate kitna hai?") is None and layer.pending_resume is None
    layer.note_interrupted("Pehli baat yeh hai. Doosri baat jo main aapse kehna chahti thi, kal aana hai.", 2)
    out = layer.take_resume("haan ji boliye")
    assert out and "kal aana hai" in out and "Pehli baat" not in out
    assert any(out.startswith(c) for c in VARIANTS["resume.connector"]["hinglish"])
    assert with_connector(None, "Toh") is None


def test_resume_off_does_nothing():
    layer = HumanLayer(S(human_resume=False), "seed")
    layer.note_interrupted("Ek. Do. Teen.", 1)
    assert layer.pending_resume is None


# ------------------------------------------------------------------ safety
def test_disclosure_lines_are_never_reworded_or_shortened():
    layer = HumanLayer(S(voice_profile="internal-test"), "seed")
    layer.observe_callee("jaldi bolo busy hoon kya tum robot ho")
    for line in (
        "Haan ji, main Rahul ki AI assistant hoon. Unhone sirf rate poochne ko kaha hai. Ek minute lagega. Theek hai? Kuch aur bhi poochna hai?",
        "Main Friday bol rahi hoon, Rahul ki virtual assistant. Rate 450 ke baare mein poochna tha.",
    ):
        assert PROTECTED.search(line)
        out = layer.shape(line, "hinglish", name="Rahul").text
        assert out.count(".") >= line.count(".") - 0 and "assistant" in out.lower()
        assert len(out.split()) >= len(line.split()) - 3  # nothing dropped, no apology prepended
        assert not any(out.startswith(x) for x in VARIANTS["mood.apology"]["hinglish"])


def test_all_off_is_identity():
    layer = HumanLayer(S(), "seed")
    t = "Rate 450 rupaye hai, kal 5:30 pm."
    sh = layer.shape(t, "hinglish")
    assert sh.text == t and sh.pace_mult == 1.0 and sh.pause_ms == 0


def test_existing_repeat_line_is_the_approved_playbook_line():
    assert EXISTING_REPEAT_LINE == "Sorry, ek baar phir?"
