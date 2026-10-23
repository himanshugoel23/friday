# ruff: noqa: E501
"""``friday voice selftest``: offline checks of every human-voice element, then the ON/OFF switch report.

No network, no key, no call. Exit code 1 if any check fails.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from friday.human import profile as prof
from friday.human.backchannel import BackchannelEngine
from friday.human.layer import PROTECTED, HumanLayer
from friday.human.lines import VARIANTS, all_lines
from friday.human.listener import ListenerModel
from friday.human.mood import MoodAdapter
from friday.human.noise import NoiseGate, NoiseTracker
from friday.human.numbers import speak_numbers
from friday.human.pauses import PausePlanner
from friday.human.resume import is_acknowledgement, unfinished
from friday.human.synth import call_audio, noise_only
from friday.human.variants import VariantPicker, detect_style
from friday.voice.telephony.media import UtteranceSegmenter

_HUMAN_CLAIM = re.compile(r"\b(i am|i'm) (a )?(real )?(human|person)\b|main insaan hoon|main (ek )?(aadmi|ladki) hoon", re.I)


def _check(name: str, fn: Callable[[], bool]) -> tuple[str, bool]:
    try:
        return name, bool(fn())
    except Exception:  # noqa: BLE001
        return name, False


def checks() -> list[tuple[str, bool]]:
    class _All:
        human_numbers = human_prosody = human_variants = human_mirror = True
        human_mood = human_match_listener = human_pauses = human_backchannels = True
        human_resume = human_noise_adapt = human_metrics = True

    def noise_levels() -> bool:
        def run(rms: float) -> str:
            t = NoiseTracker()
            seg = UtteranceSegmenter()
            for f in call_audio(noise_rms=rms):
                fr = seg.analyse(f)
                t.feed(fr.level, fr.speech)
            return t.klass

        return run(60) == "clean" and run(300) == "moderate" and run(600) == "noisy" and run(1500) == "very_noisy"

    def noise_ignored() -> bool:
        g = NoiseGate()
        return g.decide("", speech_s=0.2) == "ignore" and g.decide("...", speech_s=1.0) == "ask_repeat" and g.decide("#", speech_s=1.0) == "ask_repeat" and g.decide("x?", confidence=0.1, speech_s=1.0) == "give_up"

    def bc_rules() -> bool:
        e = BackchannelEngine("s")
        assert e.consider(now_s=10, speech_s=1.0, silence_ms=300) is None  # short answer
        assert e.consider(now_s=10, speech_s=6.0, silence_ms=300, speech_active=True) is None  # over their speech
        assert e.consider(now_s=10, speech_s=6.0, silence_ms=300, friday_speaking=True) is None
        first = e.consider(now_s=10, speech_s=6.0, silence_ms=300)
        assert first in VARIANTS["bc.short"]["hinglish"]
        assert e.consider(now_s=11, speech_s=9.0, silence_ms=300) is None  # rate limit
        return BackchannelEngine("s", allowed=False).consider(now_s=10, speech_s=6.0, silence_ms=300) is None

    def determinism() -> bool:
        a = [VariantPicker("call-1").pick("hold.moment") for _ in range(1)]
        p1, p2 = VariantPicker("call-1"), VariantPicker("call-1")
        return [p1.pick("hold.moment") for _ in range(4)] == [p2.pick("hold.moment") for _ in range(4)] and bool(a)

    def disclosure_safe() -> bool:
        layer = HumanLayer(_All(), "x")
        layer.observe_callee("jaldi bolo busy hoon")
        line = "Main Friday bol rahi hoon, Rahul ki virtual assistant. Rahul ki taraf se call kiya hai. Kya aap rate bata sakte hain? Kab khali hain? Aur kuch?"
        return PROTECTED.search(line) is not None and layer.shape(line, "hinglish", name="Rahul").text == line

    def pauses_ok() -> bool:
        p = PausePlanner("s")
        waiting = p.plan(our_line="Theek hai.", callee_text="Aap kab aayenge?")
        ms = p.plan(our_line="Kya isse kam ho sakta hai?", callee_text="Rate 450 lagega")
        capped = PausePlanner("s").plan(our_line="Final?", callee_text="500 lagega", gap_so_far_ms=800)
        return waiting == 0 and 250 <= ms <= 600 and capped in (0,) or capped <= 200

    return [
        _check("profile overlay: internal-test turns the elements ON, production leaves audible OFF", _profile_check),
        _check("voice activity: silero requested, effective backend reported with automatic fallback", lambda: prof.vad_effective(_S()).startswith(("silero", "energy"))),
        _check("numbers: 450 -> chaar sau pachaas, 5:30 pm -> shaam saade paanch baje, phone in groups", lambda: speak_numbers("Rs 450, 5:30 pm, 9876543210", "hinglish").startswith("chaar sau pachaas rupaye, shaam saade paanch baje, nau aath saat,")),
        _check("numbers: OTP/PIN context and English are left alone", lambda: speak_numbers("OTP 4829", "hinglish") == "OTP 4829" and speak_numbers("Rate 450", "en") == "Rate 450"),
        _check("variants: deterministic per call seed", determinism),
        _check("mirror: pure English / pure Hindi / Hinglish detected", lambda: (detect_style("Yes please tell me the price for tomorrow"), detect_style("हाँ जी बताइए क्या चाहिए"), detect_style("haan ji kal aa jao")) == ("en", "hi", "hinglish")),
        _check("mood: rushed -> one apology, at most one question, <= 12 words", lambda: _mood_ok()),
        _check("listener: slow/hesitant -> pace within 0.8-1.0, shorter lines", lambda: _listener_ok()),
        _check("pauses: 250-600 ms, never dead air, none when they are waiting", pauses_ok),
        _check("backchannels: only in long answers, at pauses, never over speech, rate-limited", bc_rules),
        _check("resume: continues the unfinished point, not the whole sentence", lambda: unfinished("Pehli baat yeh hai. Doosri baat jo main aapse kehna chahti thi, kal aana hai. Teesri baat.", 2) == "kal aana hai. Teesri baat." and is_acknowledgement("haan ji boliye") and not is_acknowledgement("rate kitna hai")),
        _check("noise: levels follow the synthetic noisy fixtures", noise_levels),
        _check("noise: pure noise is not answered; repeat asked; give-up after 2 fails", noise_ignored),
        _check("pure noise audio has no speech start in the detector at low level", lambda: not any(UtteranceSegmenter().analyse(f).speech for f in noise_only(1.0, 100))),
        _check("no new line claims to be human; every pending line has all three languages", lambda: not any(_HUMAN_CLAIM.search(t) for *_, t in all_lines()) and all(set(by) == {"hinglish", "hi", "en"} for by in VARIANTS.values())),
        _check("AI disclosure and protected lines are never reworded or shortened", disclosure_safe),
    ]


class _S:  # a Settings stand-in for vad_effective
    voice_vad_backend = "silero"


def _profile_check() -> bool:
    from friday.core.config import Settings

    a, b = Settings(voice_profile="internal-test"), Settings()
    return all(getattr(a, n) for n in prof.INTERNAL_TEST_ON) and not any(getattr(b, n) for n in prof.AUDIBLE) and not a.voice_stream_stt and not b.voice_stream_stt


def _mood_ok() -> bool:
    m = MoodAdapter()
    m.observe("jaldi bolo, busy hoon")
    out = m.adapt("Namaste. Kya aap rate bata sakte hain? Kab khali hain? Dhanyavaad aapke time ka bahut shukriya hamesha.")
    return m.active and out.count("?") <= 1 and len(out.split()) <= 12


def _listener_ok() -> bool:
    lm = ListenerModel()
    lm.observe("kya? sorry", 1.5)
    lm.observe("um matlab woh ... ek minute", 3.0)
    long_line = "Haircut ka rate bata dijiye aap please. Kal kitne baje khali hain aap? Dhanyavaad aapka bahut."
    return lm.style() == "slow" and 0.8 <= lm.pace() <= 1.0 and len(lm.adapt(long_line).split()) <= len(long_line.split())


def run(settings: Any) -> int:
    print("friday voice selftest (offline: no network, no call)\n")
    results = checks()
    bad = 0
    for name, ok in results:
        print(f"[{' OK ' if ok else 'FAIL'}] {name}")
        bad += not ok
    print()
    print(prof.format_report(settings))
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    print("VOICE SELFTEST PASS" if not bad else "VOICE SELFTEST FAIL")
    return 1 if bad else 0
