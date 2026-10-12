"""A short answer ends sooner than a long sentence (call speed)."""

from friday.voice.telephony.media import FRAME_MS, UtteranceSegmenter

LOUD = (b"\x00\x40" * 160)  # 20 ms at 8 kHz, constant loud level
QUIET = b"\x00\x00" * 160


def run(seg, speech_frames, silence_frames):
    got, frames_to_end = [], None
    for _ in range(speech_frames):
        got += seg.feed_pcm16(LOUD)
    for i in range(silence_frames):
        got += seg.feed_pcm16(QUIET)
        if got and frames_to_end is None:
            frames_to_end = i + 1
    return got, frames_to_end


def make(short):
    return UtteranceSegmenter(end_silence_ms=900, short_end_silence_ms=short)


def test_short_utterance_closes_at_the_short_wait():
    seg = make(650)
    got, n = run(seg, 20, 60)  # 0.4 s of speech
    assert len(got) == 1 and n is not None and n * FRAME_MS <= 660


def test_long_utterance_keeps_the_long_wait():
    seg = make(650)
    got, n = run(seg, 150, 80)  # 3 s of speech
    assert len(got) == 1 and n is not None and n * FRAME_MS >= 880


def test_off_by_default_and_when_zero():
    got, n = run(make(0), 20, 80)
    assert len(got) == 1 and n * FRAME_MS >= 880
    assert UtteranceSegmenter().short_end_silence_ms == 0
