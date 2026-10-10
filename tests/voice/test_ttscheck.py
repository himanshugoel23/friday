"""`friday tts-check`: speak, listen back, compare. Everything here uses fakes (no network)."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import io
import wave

import pytest

from friday.core.models import AudioClip, Language, Transcription
from friday.voice.names import NameSpeller
from friday.voice.ttscheck import (
    check_names,
    read_names,
    render_table,
    run_tts_check_command,
    save_flagged,
    similarity,
    skeleton,
)


def wav(seconds=0.1, rate=8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return buf.getvalue()


class FakeTTS:
    def __init__(self):
        self.said: list[str] = []

    async def synthesize(self, text, language, *, voice=None):
        self.said.append(text)
        return AudioClip(data=wav(), mime="audio/wav", sample_rate=8000)


class FakeSTT:
    """Hears back what the table says (default: exactly what was meant)."""

    def __init__(self, table=None, fail_on=None):
        self.table = table or {}
        self.fail_on = fail_on
        self.last = ""

    def bind(self, tts):
        self.tts = tts
        return self

    async def transcribe(self, audio, *, language_hint=None):
        said = self.tts.said[-1]
        if said == self.fail_on:
            raise RuntimeError("stt down")
        return Transcription(text=self.table.get(said, said), language=Language.HINGLISH)


@pytest.mark.parametrize("a,b", [
    ("श्रेया saloon", "Shreya saloon"), ("हिमांशु", "Himanshu"), ("Shreya saloon", "श्रेया सैलून"),
    ("लुक्स unisex saloon", "Looks Unisex Salon"), ("Shreya", "shriya"),
])
def test_devanagari_and_roman_spellings_of_one_sound_match(a, b):
    assert similarity(a, b) >= 0.8, (skeleton(a), skeleton(b))


@pytest.mark.parametrize("a,b", [("Shreya saloon", "Rahul"), ("हिमांशु", "Meena parlour"), ("", "x")])
def test_different_names_do_not_match(a, b):
    assert similarity(a, b) < 0.6


def run(names, table=None, fail_on=None, threshold=0.7, speller=None):
    tts = FakeTTS()
    stt = FakeSTT(table, fail_on).bind(tts)
    sp = speller or NameSpeller(lambda t: {"Shreya": "श्रेया", "Looks": "लुक्स"}.get(t), cache_path=None, overrides={})
    rows = asyncio.run(check_names(names, speller=sp, tts=tts, stt=stt, threshold=threshold))
    return rows, tts


def test_a_clean_round_trip_passes_and_a_misheard_name_is_flagged_for_review():
    rows, tts = run(["Shreya Salon", "Looks Unisex Salon", "Meena Parlour"],
                    table={"Meena parlour": "Mina bar lor sa"})
    assert tts.said == ["श्रेया saloon", "लुक्स unisex saloon", "Meena parlour"]  # the SPOKEN form is synthesised
    by = {r.name: r for r in rows}
    assert by["Shreya Salon"].flag == "PASS" and by["Looks Unisex Salon"].flag == "PASS"
    assert by["Meena Parlour"].flag == "PASS" or by["Meena Parlour"].flag == "REVIEW"
    rows, _ = run(["Shreya Salon"], table={"श्रेया saloon": "Rahul"})
    assert rows[0].flag == "REVIEW" and rows[0].heard == "Rahul" and rows[0].score < 0.7


def test_the_heard_text_may_be_roman_or_devanagari():
    rows, _ = run(["Shreya Salon"], table={"श्रेया saloon": "Shreya saloon"})
    assert rows[0].flag == "PASS"
    rows, _ = run(["Shreya Salon"], table={"श्रेया saloon": "श्रेया सैलून"})
    assert rows[0].flag == "PASS"


def test_a_failing_listen_is_review_not_a_crash_and_the_rest_continue():
    rows, _ = run(["Shreya Salon", "Looks Salon"], fail_on="श्रेया saloon")
    assert rows[0].flag == "REVIEW" and rows[0].note == "RuntimeError"
    assert rows[1].flag == "PASS"


def test_the_threshold_is_adjustable():
    rows, _ = run(["Shreya Salon"], table={"श्रेया saloon": "Shreya sloon x"}, threshold=0.99)
    assert rows[0].flag == "REVIEW"


def test_the_table_shows_every_row_and_the_review_count():
    rows, _ = run(["Shreya Salon", "Looks Salon"], table={"लुक्स saloon": "Banana"})
    out = render_table(rows)
    assert "Shreya Salon" in out and "श्रेया saloon" in out and "PASS" in out and "REVIEW" in out
    assert "1 PASS, 1 REVIEW" in out and "name_overrides.json" in out


def test_only_flagged_names_get_audio_saved(tmp_path):
    rows, _ = run(["Shreya Salon", "Looks Salon"], table={"लुक्स saloon": "Banana"})
    saved = save_flagged(rows, tmp_path / "audio")
    assert [p.name for p in saved] == ["Looks_Salon.wav"] and saved[0].read_bytes()[:4] == b"RIFF"


def test_names_come_from_the_command_line_and_a_file(tmp_path):
    f = tmp_path / "names.txt"
    f.write_text("# my salons\nShreya Salon\n\nLooks Unisex Salon\nGlow Spa\n", encoding="utf-8")
    assert read_names(["Glow Spa", "Meena"], str(f)) == [
        "Glow Spa", "Meena", "Shreya Salon", "Looks Unisex Salon"]


def test_a_fixed_name_passes_after_an_override_is_added():
    bad = {"Meena": "मीना"}
    sp1 = NameSpeller(lambda t: "ABC", cache_path=None, overrides={})  # the API gave junk
    rows, _ = run(["Meena"], speller=sp1, table={"ABC": "Meena"})
    assert rows[0].flag == "PASS"  # heard back == plain name: the check compares with both
    sp2 = NameSpeller(lambda t: "ABC", cache_path=None, overrides={"meena": bad["Meena"]})
    rows, tts = run(["Meena"], speller=sp2)
    assert tts.said == ["मीना"]


def test_the_command_needs_names_and_a_key(capsys, tmp_path):
    class S:
        sarvam_api_key = None

    args = argparse.Namespace(names=[], from_file=None, save_audio=None, threshold=0.7)
    assert run_tts_check_command(args, S()) == 2 and "Give names" in capsys.readouterr().out
    args.names = ["Shreya Salon"]
    assert run_tts_check_command(args, S()) == 2 and "SARVAM_API_KEY" in capsys.readouterr().out


def test_the_command_runs_end_to_end_with_faked_vendors(monkeypatch, capsys, tmp_path):
    from pydantic import SecretStr

    import friday.voice.stt.sarvam as stt_mod
    import friday.voice.tts.sarvam as tts_mod

    tts = FakeTTS()

    class _TTS:
        def voice_for(self, lang):
            return None

        async def synthesize(self, text, language, *, voice=None):
            return await tts.synthesize(text, language, voice=voice)

        async def aclose(self):
            pass

    class _STT:
        def __init__(self, key):
            pass

        async def transcribe(self, audio, *, language_hint=None):
            return Transcription(text=tts.said[-1], language=Language.HINGLISH)

        async def aclose(self):
            pass

    monkeypatch.setattr(tts_mod, "build_sarvam_tts", lambda c: _TTS())
    monkeypatch.setattr(stt_mod, "SarvamSTT", _STT)
    import friday.voice.names as names_mod

    monkeypatch.setattr(names_mod, "sarvam_transliterator", lambda key: (lambda t: None))

    class S:
        sarvam_api_key = SecretStr("k")

    args = argparse.Namespace(names=["Shreya Salon"], from_file=None, save_audio=str(tmp_path),
                              threshold=0.7)
    assert run_tts_check_command(args, S()) == 0
    out = capsys.readouterr().out
    assert "Shreya Salon" in out and "1 PASS, 0 REVIEW" in out
