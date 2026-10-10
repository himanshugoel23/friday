"""`friday playbook preview`: the real script lines, through the names pipeline, into one wav (fake TTS)."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import io
import wave

import pytest

from friday.core.models import AudioClip
from friday.playbooks.model import PlaybookError
from friday.playbooks.preview import friday_lines, join_pcm_wav, render_preview
from friday.voice.names import NameSpeller

SP = NameSpeller(lambda t: {"Shreya": "श्रेया", "Himanshu": "हिमांशु"}.get(t), cache_path=None, overrides={})
COMMON = dict(business="Shreya Salon", user="Himanshu", services="haircut, beard trim",
              when="aaj shaam 5 baje", fallback_when="kal shaam 5 baje", budget=600,
              honorific="sir", speller=SP)
WHO = "Main Friday baat kar rahi hoon, हिमांशु sir ki virtual assistant."


def wav(n_frames: int, rate=8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x02\x00" * n_frames)
    return buf.getvalue()


class FakeTTS:
    def __init__(self):
        self.said: list[str] = []
        self.voices = []

    async def synthesize(self, text, language, *, voice=None):
        self.said.append(text)
        self.voices.append(voice)
        return AudioClip(data=wav(800), mime="audio/wav", sample_rate=8000)  # 0.1 s each


def lines(mode, branch=None, **over):
    kw = {**COMMON, **over}
    if mode == "quote_only":
        kw["when"] = kw["fallback_when"] = None
    return asyncio.run(friday_lines(mode=mode, branch=branch, **kw))


def test_quote_only_script_is_the_real_lines_with_names_and_services():
    got, outcome = lines("quote_only")
    assert outcome == "QUOTE_COLLECTED"
    assert got == [
        "Hello, kya meri baat श्रेया saloon se ho rahi hai?",
        f"{WHO} हिमांशु sir ko haircut aur beard trim karwana hai, toh uske charges ke regarding call kiya hai. Toh sir, ek baar bata sakte hain inke kya charges rahenge?",
        "Theek hai sir, main हिमांशु sir ko bata deti hoon. Thank you.",
    ]


def test_book_mode_busy_then_fallback_script():
    got, outcome = lines("book", "busy_then_fallback")
    assert outcome == "BOOKED"
    assert got[0] == "Hello, kya meri baat श्रेया saloon se ho rahi hai?"
    assert "unki booking ke regarding call kiya hai" in got[1]
    assert got[2:] == [
        "Theek hai sir. Kya aaj shaam 5 baje ka slot mil sakta hai?",
        "Achha, nahi ho sakta. Toh kya kal ka slot available rahega?",
        "Theek hai sir, phir kal shaam 5 baje ka slot book kar lete hain. हिमांशु sir aane se pehle aapko ek baar call kar lenge. Thank you.",
    ]


def test_book_mode_free_script_and_default_branch():
    got, outcome = lines("book")
    assert outcome == "BOOKED" and len(got) == 4
    assert got[-1] == "Theek hai sir, toh aaj shaam 5 baje ka slot book kar lijiye. हिमांशु sir aane se pehle aapko ek baar call kar lenge. Thank you."
    assert lines("book", "free")[0] == got


def test_a_madam_honorific_and_other_services_are_inputs():
    got, _ = lines("quote_only", honorific="madam", services="haircut")
    assert "हिमांशु madam ki virtual assistant" in got[1] and "ko haircut karwana hai" in got[1]


@pytest.mark.parametrize("kw", [
    {"mode": "quote_only", "branch": "free"},  # a branch of the other mode
    {"mode": "book", "branch": "busy_then_fallback", "fallback_when": None},
    {"mode": "nonsense"},
    {"mode": "book", "when": "kal shaam"},  # no specific time
    {"mode": "book", "fallback_when": "kal shaam"},
])
def test_bad_preview_requests_are_refused(kw):
    base = {**COMMON, "mode": "book", "branch": None}
    base.update(kw)
    with pytest.raises(PlaybookError):
        asyncio.run(friday_lines(**base))


def test_the_wav_has_a_silence_wherever_the_salon_would_speak(tmp_path):
    tts = FakeTTS()
    res = asyncio.run(render_preview(tts=tts, voice="V", out_dir=tmp_path, silence_s=1.8,
                                     mode="book", branch="busy_then_fallback", **COMMON))
    assert tts.said == res.lines and len(tts.said) == 5 and set(tts.voices) == {"V"}
    with wave.open(str(res.wav_path)) as w:
        assert w.getframerate() == 8000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        frames = w.getnframes()
    assert frames == 5 * 800 + 4 * int(8000 * 1.8)  # five lines, four gaps
    assert res.wav_path.name == "preview_book_busy_then_fallback.wav"
    assert res.wav_path.with_suffix(".txt").read_text(encoding="utf-8").splitlines() == res.lines
    assert abs(res.seconds - frames / 8000) < 0.01 and res.outcome == "BOOKED"


def test_join_pcm_wav_handles_zero_gap():
    data, rate = join_pcm_wav([wav(10), wav(20)], 0.0)
    assert rate == 8000
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() == 30


def test_the_cli_command_wires_through_to_the_renderer(monkeypatch, tmp_path, capsys):
    from pydantic import SecretStr

    import friday.core.config as config
    import friday.playbooks.cli as cli
    import friday.playbooks.preview as preview
    import friday.voice.tts.sarvam as tts_mod

    seen = {}
    fake = FakeTTS()

    class _TTS:
        def voice_for(self, lang):
            class V:
                speaking_rate = 1.0

                def model_copy(self, update):
                    seen["rate"] = update["speaking_rate"]
                    return self

            return V()

        synthesize = fake.synthesize

        async def aclose(self):
            pass

    class _Settings:
        sarvam_api_key = SecretStr("k")

    monkeypatch.setattr(config, "Settings", _Settings)
    monkeypatch.setattr(tts_mod, "build_sarvam_tts", lambda c: _TTS())
    import friday.voice.names as names_mod

    monkeypatch.setattr(names_mod, "sarvam_transliterator", lambda key: (lambda t: None))
    real = preview.render_preview

    async def spy(**kw):
        seen["kw"] = kw
        return await real(**kw)

    monkeypatch.setattr(preview, "render_preview", spy)
    from friday.cli import main

    rc = main(["playbook", "preview", "salon_booking", "--mode", "book", "--business", "Shreya Salon",
               "--user", "Himanshu", "--services", "haircut, beard trim", "--when", "aaj shaam 5 baje",
               "--fallback-when", "kal shaam 5 baje", "--branch", "busy_then_fallback",
               "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "preview_book_busy_then_fallback.wav" in out and "Outcome of this branch: BOOKED" in out
    assert seen["rate"] == 0.9 and seen["kw"]["silence_s"] == 1.8
    assert (tmp_path / "preview_book_busy_then_fallback.wav").exists()
    assert main(["playbook", "preview", "salon_booking", "--mode", "book", "--business", "X",
                 "--user", "H", "--out", str(tmp_path)]) == 2  # no --when: refused, nothing written
    assert "Cannot preview" in capsys.readouterr().out
    assert cli is not None
